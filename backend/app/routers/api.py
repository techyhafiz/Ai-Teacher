"""API routers: learners, documents, planning, sessions, checkpoints, quiz,
reports, TPM metrics.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import db
from ..config import PERFORMANCES_DIR, UPLOADS_DIR
from ..services import brain, parser, planner, rag
from ..services.capture import PerformanceCapture, PERSONA_VOICES
from ..services.tpm_manager import tpm
log = logging.getLogger("api")
router = APIRouter()

ALLOWED_UPLOAD_EXT = {".pdf", ".docx", ".pptx", ".txt", ".md", ".markdown"}
MAX_UPLOAD_MB = 60


# ---------------------------------------------------------------------------
# Learners
# ---------------------------------------------------------------------------

class LearnerIn(BaseModel):
    name: str
    language: str = "en"
    level: str = "beginner"
    learner_id: Optional[str] = None


@router.post("/learners")
async def create_learner(body: LearnerIn):
    return db.upsert_learner(body.name, body.language, body.level,
                             body.learner_id)


@router.get("/learners")
async def get_learners():
    return db.list_learners()


@router.get("/learners/{learner_id}")
async def get_learner(learner_id: str):
    l = db.get_learner(learner_id)
    if not l:
        raise HTTPException(404, "Learner not found")
    l["mastery"] = db.get_mastery(learner_id)
    l["profile_summary"] = db.learner_profile_summary(learner_id)
    return l


# ---------------------------------------------------------------------------
# Document upload + processing + RAG ingest
# ---------------------------------------------------------------------------

@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    learner_id: str = Form(...),
    language_hint: str = Form("en"),
):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXT:
        raise HTTPException(400, f"Unsupported format '{ext}'. Allowed: "
                                 f"{sorted(ALLOWED_UPLOAD_EXT)}")

    learner_dir = UPLOADS_DIR / learner_id
    learner_dir.mkdir(parents=True, exist_ok=True)
    dest = learner_dir / f"{int(time.time())}_{Path(file.filename).name}"
    size = 0
    with dest.open("wb") as out:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD_MB << 20:
                raise HTTPException(413, f"File too large (max {MAX_UPLOAD_MB}MB)")
            out.write(chunk)

    from ..services import parser as parser_svc
    try:
        record = await parser_svc.process_document(dest, file.filename,
                                                   language_hint=language_hint)
    except Exception as e:                                  # noqa: BLE001
        raise HTTPException(500, f"Document parsing failed: {e}") from e

    try:
        ingest = await rag.ingest_document(record["doc_id"])
        record["ingest"] = ingest
    except RuntimeError as e:                # missing API key etc.
        record["ingest"] = {"error": str(e),
                            "hint": "Set GEMINI_API_KEY in backend/.env for RAG embeddings"}
    except Exception as e:                                  # noqa: BLE001
        record["ingest"] = {"error": str(e)}
    return record


@router.get("/documents/{doc_id}")
async def get_document(doc_id: str):
    doc = parser.load_document(doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    return doc


# ---------------------------------------------------------------------------
# Session creation + planning
# ---------------------------------------------------------------------------

class PlanIn(BaseModel):
    learner_id: str
    mode: str                        # 'topic' | 'upload'
    topic: str
    language: str = "en"             # en | hi | hinglish
    level: str = "beginner"          # beginner | intermediate | advanced
    time_budget: str = "20min"       # 5min | 20min | 60min | 7days
    doc_id: Optional[str] = None
    doc_focus: Optional[str] = None  # e.g. 'chapter 4'
    persona: str = "Aarav Sir"      # Aarav Sir | Meera Ma'am | Professor Bheem


@router.post("/sessions")
async def create_and_plan_session(body: PlanIn):
    if body.mode not in ("topic", "upload"):
        raise HTTPException(400, "mode must be 'topic' or 'upload'")
    if body.language not in ("en", "hi", "hinglish"):
        raise HTTPException(400, "language must be en|hi|hinglish")
    if body.level not in ("beginner", "intermediate", "advanced"):
        raise HTTPException(400, "invalid level")
    if body.time_budget not in ("5min", "20min", "60min", "7days"):
        raise HTTPException(400, "time_budget must be 5min|20min|60min|7days")

    session_id = db.create_session(body.learner_id, body.mode, body.topic,
                                   body.language, body.level, body.time_budget,
                                   body.doc_id)
    try:
        plan = await planner.plan_lesson(
            session_id,
            learner_id=body.learner_id,
            mode=body.mode,
            topic_request=body.topic,
            language=body.language,
            level=body.level,
            time_budget=body.time_budget,
            doc_id=body.doc_id,
            doc_focus=body.doc_focus,
            persona=body.persona,
        )
    except Exception as e:                                  # noqa: BLE001
        db.set_status(session_id, "failed")
        raise HTTPException(500, f"Planning failed: {e}") from e

    return {"session_id": session_id, "plan": plan}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    s = db.get_session(session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    s["events"] = db.get_events(session_id)
    s["quiz_results"] = db.get_quiz_results(session_id)
    return s


# ---------------------------------------------------------------------------
# Performance capture (run for all segments; status polled via session events)
# ---------------------------------------------------------------------------

class CaptureIn(BaseModel):
    session_id: str
    variant: str = "main"           # main | simpler | deeper | regen


@router.post("/sessions/{session_id}/capture")
async def capture_session(session_id: str, variant: str = "main"):
    """Capture performances for ALL segments of the session plan."""
    s = db.get_session(session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    if variant not in ("main", "simpler", "deeper", "regen"):
        raise HTTPException(400, "variant must be main|simpler|deeper|regen")
    plan = json.loads(s["plan"] or "{}")
    if not plan:
        raise HTTPException(400, "Session has no plan")

    lang_name = {"en": "English", "hi": "Hindi", "hinglish": "Hinglish"}[
        plan.get("language", "en")]
    persona = plan.get("persona", "Aarav Sir")
    voice = PERSONA_VOICES.get(persona, "Charon")

    results = []
    for seg in plan["segments"]:
        if seg.get("kind") == "assessment_intro":
            continue
        script = (seg.get("script") or {}).get(variant) or \
                 (seg.get("script") or {}).get("main") or ""
        if not script.strip():
            continue
        cap = PerformanceCapture(session_id, seg["seg_id"], variant,
                                 persona_name=persona, voice=voice)
        perf = await cap.capture(script, seg.get("visuals", []), lang_name)
        results.append(perf)

    db.set_status(session_id, "teaching")
    return {"session_id": session_id, "performances": results}


class CaptureOneIn(BaseModel):
    seg_id: int
    variant: str = "main"
    script_override: Optional[str] = None
    visuals_override: Optional[list] = None


@router.post("/sessions/{session_id}/capture-one")
@router.post("/sessions/{session_id}/capture_one")
async def capture_one(session_id: str, body: CaptureOneIn):
    """Capture a single segment (used for re-explanations / language re-render)."""
    s = db.get_session(session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    plan = json.loads(s["plan"] or "{}")
    seg = next((x for x in plan.get("segments", [])
                if x["seg_id"] == body.seg_id), None)
    if not seg:
        raise HTTPException(404, f"Segment {body.seg_id} not found")

    script = body.script_override or (seg.get("script") or {}).get(
        body.variant) or (seg.get("script") or {}).get("main") or ""
    visuals = body.visuals_override if body.visuals_override is not None \
        else seg.get("visuals", [])
    lang_name = {"en": "English", "hi": "Hindi", "hinglish": "Hinglish"}[
        plan.get("language", "en")]
    persona = plan.get("persona", "Aarav Sir")
    voice = PERSONA_VOICES.get(persona, "Charon")

    cap = PerformanceCapture(session_id, body.seg_id, body.variant,
                             persona_name=persona, voice=voice)
    perf = await cap.capture(script, visuals, lang_name)
    db.log_event(session_id, "captured", {
        "seg_id": body.seg_id, "variant": body.variant,
        "duration": perf["duration"], "verbatim": perf["verbatim_score"],
    })
    return perf


@router.get("/performances/{session_id}")
async def list_performances(session_id: str):
    perf_dir = PERFORMANCES_DIR / session_id
    if not perf_dir.exists():
        return {"performances": []}
    out = []
    for p in sorted(perf_dir.glob("seg_*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:                                   # noqa: BLE001
            pass
    return {"performances": out}


@router.get("/performances/{session_id}/{wav_name}")
async def get_performance_audio(session_id: str, wav_name: str):
    path = (PERFORMANCES_DIR / session_id / wav_name).resolve()
    if not str(path).startswith(str(PERFORMANCES_DIR.resolve())) or \
            not path.exists() or path.suffix != ".wav":
        raise HTTPException(404, "Not found")
    return FileResponse(str(path), media_type="audio/wav")


# ---------------------------------------------------------------------------
# Checkpoints (teaching brain)
# ---------------------------------------------------------------------------

class CheckpointIn(BaseModel):
    seg_id: int
    concept: str
    question: str
    expected_answer: str
    student_answer: str
    attempt: int = 1
    language: str = "en"


@router.post("/sessions/{session_id}/checkpoint")
async def checkpoint(session_id: str, body: CheckpointIn):
    s = db.get_session(session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    result = await brain.evaluate_checkpoint(
        session_id,
        seg_id=body.seg_id,
        concept=body.concept,
        question=body.question,
        expected_answer=body.expected_answer,
        student_answer=body.student_answer,
        language=body.language or s["language"],
        learner_id=s["learner_id"],
        attempt=body.attempt,
    )
    return result


class RegenIn(BaseModel):
    seg_id: int
    concept: str
    original_script: str
    misconception: str
    misconception_explanation: str = ""
    student_answer: str = ""
    question: str
    used_variants: list[str] = None
    language: str = "en"


@router.post("/sessions/{session_id}/regen")
async def regen_re_explanation(session_id: str, body: RegenIn):
    s = db.get_session(session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    plan = json.loads(s["plan"] or "{}")
    seg = next((x for x in plan.get("segments", [])
                if x["seg_id"] == body.seg_id), None)
    if not seg:
        raise HTTPException(404, f"Segment {body.seg_id} not found")
    regen = await brain.generate_re_explanation(
        session_id,
        concept=body.concept,
        original_script_main=body.original_script,
        misconception=body.misconception,
        misconception_explanation=body.misconception_explanation,
        student_answer=body.student_answer,
        question=body.question,
        language=body.language or s["language"],
        used_variants=body.used_variants or [],
    )
    return regen


# ---------------------------------------------------------------------------
# Quiz
# ---------------------------------------------------------------------------

class QuizAnswerIn(BaseModel):
    question: str
    expected_answer: str
    student_answer: str
    concept: str
    options: Optional[list[str]] = None
    answer_index: Optional[int] = None
    points: float = 1.0


@router.post("/sessions/{session_id}/quiz")
async def quiz_answer(session_id: str, body: QuizAnswerIn):
    s = db.get_session(session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    return await brain.grade_quiz_answer(
        session_id,
        question=body.question,
        expected_answer=body.expected_answer,
        student_answer=body.student_answer,
        concept=body.concept,
        language=s["language"],
        options=body.options,
        answer_index=body.answer_index,
        points=body.points,
        learner_id=s["learner_id"],
    )


@router.post("/sessions/{session_id}/report")
async def make_report(session_id: str):
    s = db.get_session(session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    return await brain.generate_report(session_id, s["language"])


# ---------------------------------------------------------------------------
# Learning path (broad topics)
# ---------------------------------------------------------------------------

class PathIn(BaseModel):
    topic: str
    language: str = "en"
    learner_id: Optional[str] = None


@router.post("/learning-path")
async def learning_path(body: PathIn):
    return await planner.plan_learning_path(body.topic, body.language,
                                            body.learner_id)


# ---------------------------------------------------------------------------
# TPM metrics (transparency endpoint)
# ---------------------------------------------------------------------------

@router.get("/metrics")
async def metrics():
    return tpm.metrics()
