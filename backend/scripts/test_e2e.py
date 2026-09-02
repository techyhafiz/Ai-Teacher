"""End-to-end API test WITH a real Gemini key: embedding, planning, capture.

Usage:  python scripts/test_e2e.py [topic]
"""
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db                                             # noqa: E402
from app.services import gemini, planner, brain                # noqa: E402
from app.services.capture import PerformanceCapture           # noqa: E402
from app.config import PERFORMANCES_DIR, settings             # noqa: E402

TOPIC = sys.argv[1] if len(sys.argv) > 1 else "Ohm's Law for a Class 8 student"


async def step(name, coro):
    print(f"\n=== {name} ===")
    res = await coro
    print(json.dumps(res, ensure_ascii=False)[:800] if not isinstance(res, str) else res[:800])
    return res


async def main():
    print("models:", settings.gemini_text_model, "|", settings.gemini_live_model)
    print("key set:", bool(settings.gemini_api_key))

    # 1. text call (planning uses this path)
    txt = await step("TEXT: simple generate",
                     gemini.generate_text("Reply with exactly: HELLO_TEACHER"))
    assert "HELLO_TEACHER" in txt, txt

    # 2. embeddings (RAG path)
    emb = await step("EMBED", gemini.embed_texts(["Ohm's law says V equals I times R"]))
    assert len(emb) == 1 and len(emb[0]) > 100, "embedding shape wrong"

    # 3. plan a lesson
    db.init_db()
    lid = db.upsert_learner("E2E Test Learner", "en", "beginner")["id"]
    sid = db.create_session(lid, "topic", TOPIC, "en", "beginner", "5min")
    plan = await step(f"PLAN: {TOPIC}", planner.plan_lesson(
        session_id=sid, learner_id=lid, mode="topic", topic_request=TOPIC,
        language="en", level="beginner", time_budget="5min", doc_id=None))
    segs = plan["segments"]
    print(f"plan: {len(segs)} segments, {len(plan['quiz'])} quiz questions")
    assert 1 <= len(segs) <= 3, "5min budget should produce ~2 segments"
    assert plan["quiz"], "quiz missing"

    # 4. capture one segment through the LIVE API
    cap = PerformanceCapture(session_id=sid, seg_id=segs[0]["seg_id"],
                             persona_name="Aarav Sir", voice="Charon")
    perf = await step("CAPTURE seg 0 (Live API)", cap.capture(
        script=segs[0]["script"]["main"], visuals=segs[0].get("visuals", []),
        language_name="English"))
    print(f"audio: {perf['duration']}s, verbatim={perf['verbatim_score']:.3f}, "
          f"visuals={len(perf['timeline'])}")
    assert perf["wav_name"], "wav missing"
    assert "[PAUSE]" not in perf["transcript"].upper(), "stage words leaked into transcript"
    wav = PERFORMANCES_DIR / sid / perf["wav_name"]
    print("wav size:", wav.stat().st_size if wav.exists() else "MISSING", "bytes")
    assert wav.exists() and wav.stat().st_size > 10000, "wav too small"

    # 5. evaluate a checkpoint answer (find a segment with a checkpoint)
    cseg = next(s for s in segs if s.get("checkpoint"))
    cp = cseg["checkpoint"]
    ev = await step("CHECKPOINT eval (wrong answer)",
                    brain.evaluate_checkpoint(
                        session_id=sid, learner_id=lid, seg_id=cseg["seg_id"],
                        concept=cseg["concept"],
                        question=cp["question"],
                        expected_answer=cp["expected_answer"],
                        student_answer="current increases with resistance",
                        language="en"))
    print("verdict:", ev["verdict"], "| move:", ev["teaching_move"])
    assert ev["verdict"] in {"correct", "partially_correct", "incorrect"}

    # 6. regen a re-explanation
    regen = await step("REGEN re-explanation", brain.generate_re_explanation(
        session_id=sid, concept=segs[0]["concept"],
        original_script_main=segs[0]["script"]["main"],
        misconception=ev.get("misconception") or "confusion",
        misconception_explanation=ev.get("misconception_explanation") or "",
        student_answer="current increases with resistance",
        question=cp["question"], language="en", used_variants=["main"]))
    assert regen["script"], "regen script missing"
    assert regen.get("new_checkpoint", {}).get("question"), "regen re-check missing"

    # 7. grade a quiz answer
    q = next(x for x in plan["quiz"] if x.get("q"))
    grade = await step("QUIZ grade", brain.grade_quiz_answer(
        session_id=sid, question=q["q"],
        expected_answer=q.get("expected_answer") or "",
        student_answer=q["options"][q["answer_index"]] if q.get("options")
            else (q.get("expected_answer") or ""),
        concept=q.get("concept", "general"), language="en",
        options=q.get("options"), answer_index=q.get("answer_index")))
    print("correct:", grade["correct"], "scored:", grade.get("scored"))
    assert grade["correct"] is True

    # 8. learning report
    report = await step("REPORT", brain.generate_report(session_id=sid, language="en"))
    assert "score_pct" in report or "summary" in report, report

    print("\n" + "=" * 60)
    print("END-TO-END WITH REAL GEMINI: ALL STEPS PASSED")
    print(f"session: {sid}  (perf WAV at data/performances/{sid}/)")


asyncio.run(main())
