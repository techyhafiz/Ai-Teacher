"""Teacher brain — evaluation, misconception detection, adaptive decisions.

Handles:
  - checkpoint evaluation: grade a student answer, detect misconception,
    decide the teaching move (praise/advance, re-explain variant, live
    regen, simplify, go deeper, skip ahead)
  - strict gating: re-explain -> re-check -> advance (never advance on an
    uncorrected wrong answer)
  - quiz grading (MCQ exact + short answers semantic)
  - learning report generation (report-card format from the problem statement)
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from .. import db
from .gemini import BATCH, LIVE, generate_json
from .planner import LANG_NAMES

log = logging.getLogger("brain")


# ---------------------------------------------------------------------------
# Checkpoint evaluation
# ---------------------------------------------------------------------------

EVAL_SYSTEM = """You are the pedagogy engine of an AI teacher (the student never sees this
output — the on-screen teacher uses it to decide what to say next).

Evaluate the student's answer against the expected answer for the checkpoint
question of the given lesson concept. Detect the misconception if wrong.

Return STRICT JSON:
{
  "verdict": "correct" | "partially_correct" | "incorrect",
  "score": <0.0-1.0>,
  "misconception": "<short tag or null, e.g. 'thinks_current_increases_with_resistance'>",
  "misconception_explanation": "<why the student likely thinks this, 1 sentence, or null>",
  "teacher_reply": "<2-4 sentences the teacher SAYS to the student: warm, constructive; if correct - praise briefly and add one insight; if wrong - acknowledge effort, gently correct, no answer giveaway yet",
  "teaching_move": "advance" | "re_explain" | "simplify" | "go_deeper" | "skip_ahead",
  "re_explain_reason": "<which variant to use and why, 1 sentence, or null>"
}"""

LANG_SUFFIX = {
    "en": "Write teacher_reply in English.",
    "hi": "Write teacher_reply in Hindi (Devanagari).",
    "hinglish": "Write teacher_reply in Hinglish (Roman script Hindi-English mix).",
}


async def evaluate_checkpoint(
    session_id: str,
    *,
    seg_id: int,
    concept: str,
    question: str,
    expected_answer: str,
    student_answer: str,
    language: str,
    learner_id: str,
    attempt: int = 1,
) -> dict[str, Any]:
    """Evaluate a checkpoint answer and decide the next teaching move."""
    prompt = f"""Concept: {concept}
Checkpoint question: {question}
Expected answer: {expected_answer}
Student answer: "{student_answer}"
Attempt number: {attempt} (attempt 2+ means the student already got a re-explanation)
{LANG_SUFFIX.get(language, '')}"""

    result = await generate_json(prompt, system=EVAL_SYSTEM, temperature=0.3,
                                 priority=LIVE)

    # normalize verdict/move
    verdict = result.get("verdict", "incorrect")
    if verdict not in ("correct", "partially_correct", "incorrect"):
        verdict = "incorrect" if result.get("score", 0) < 0.5 else "correct"
    move = result.get("teaching_move", "advance")
    score = float(result.get("score", 0.0) or 0.0)
    if verdict == "correct" and score < 0.7:
        score = 0.9
    if verdict == "incorrect" and score > 0.4:
        score = 0.2

    # strict gating enforcement: never advance on uncorrected wrong answers
    if move == "advance" and verdict == "incorrect":
        move = "re_explain"
    if move == "advance" and verdict == "partially_correct" and attempt < 2:
        move = "re_explain"

    # update mastery + log the decision
    db.update_mastery(learner_id, concept, score)
    db.log_event(session_id, "checkpoint_eval", {
        "seg_id": seg_id, "concept": concept, "attempt": attempt,
        "student_answer": student_answer, "verdict": verdict, "score": score,
        "misconception": result.get("misconception"),
        "teaching_move": move,
        "teacher_reply": result.get("teacher_reply"),
    })

    return {
        "verdict": verdict,
        "score": score,
        "misconception": result.get("misconception"),
        "misconception_explanation": result.get("misconception_explanation"),
        "teacher_reply": result.get("teacher_reply", ""),
        "teaching_move": move,
        "re_explain_reason": result.get("re_explain_reason"),
    }


# ---------------------------------------------------------------------------
# Live regen: misconception-targeted re-explanation script
# ---------------------------------------------------------------------------

REGEN_SYSTEM = """You are a scriptwriter for an AI teacher re-explaining a concept to a
student who just answered incorrectly. Return STRICT JSON:
{
  "script": "<60-120 words the teacher speaks, a DIFFERENT angle than before:
             new analogy, new example, smaller steps>",
  "visuals": [ {"tool": "<whiteboard tool>", "args": {...}, "after_sentence": <int>} ],
  "new_checkpoint": {"question": "...", "expected_answer": "...",
                     "question_type": "short_answer", "options": null,
                     "answer_index": null, "hint": "..."}
}"""

REGEN_TOOLS_NOTE = "Available whiteboard tools: write_text, draw_equation, plot_graph, draw_diagram, draw_timeline, write_code, draw_map, draw_flowchart, show_table"


async def generate_re_explanation(
    session_id: str,
    *,
    concept: str,
    original_script_main: str,
    misconception: str,
    misconception_explanation: str,
    student_answer: str,
    question: str,
    language: str,
    used_variants: list[str],
) -> dict[str, Any]:
    """Live-regen a targeted re-explanation segment (mistake-driven teaching)."""
    lang_name = LANG_NAMES.get(language, "English")
    lang_rule = {
        "en": "Write the script in English.",
        "hi": "Write the script in Hindi (Devanagari).",
        "hinglish": "Write the script in Hinglish (Roman script code-mixing).",
    }[language]
    prompt = f"""Concept: {concept}
Previous explanation the student heard (did NOT work):
\"\"\"{original_script_main[:1500]}\"\"\"
Checkpoint question: {question}
Student's incorrect answer: "{student_answer}"
Detected misconception: {misconception} — {misconception_explanation}
Variants already used: {used_variants}
{lang_rule}
{REGEN_TOOLS_NOTE}

Write a re-explanation that attacks THIS misconception directly with a
completely different analogy/example, then a NEW checkpoint to re-verify.
Return the JSON described."""

    result = await generate_json(prompt, system=REGEN_SYSTEM, temperature=0.6,
                                 priority=LIVE)
    db.log_event(session_id, "regen_re_explain", {
        "concept": concept,
        "misconception": misconception,
        "used_variants": used_variants,
        "new_question": (result.get("new_checkpoint") or {}).get("question"),
    })
    return result


# ---------------------------------------------------------------------------
# Quiz grading
# ---------------------------------------------------------------------------

async def grade_quiz_answer(
    session_id: str,
    *,
    question: str,
    expected_answer: str,
    student_answer: str,
    concept: str,
    language: str,
    options: Optional[list[str]] = None,
    answer_index: Optional[int] = None,
    points: float = 1.0,
    learner_id: str = "",
) -> dict[str, Any]:
    """Grade one quiz answer (MCQ exact-match or short-answer semantic)."""
    # MCQ: frontend sends the selected index (int-like string) or option text
    if options and answer_index is not None:
        chosen = -1
        s = (student_answer or "").strip()
        if s.isdigit() and int(s) < len(options):
            chosen = int(s)
        else:
            for i, opt in enumerate(options):
                if _normalize(opt) == _normalize(s):
                    chosen = i
                    break
        correct = chosen == answer_index
        scored = points if correct else 0.0
        expected_text = options[answer_index]
        misconception = None
        explanation = None
        db.add_quiz_result(session_id, question, expected_text,
                           options[chosen] if chosen >= 0 else student_answer,
                           correct, misconception, points, scored)
        if learner_id:
            db.update_mastery(learner_id, concept, 1.0 if correct else 0.0)
        db.log_event(session_id, "quiz_answer", {
            "question": question, "concept": concept, "given": student_answer,
            "chosen": chosen, "correct": correct, "mode": "mcq",
        })
        return {"correct": correct, "scored": scored, "points": points,
                "expected": expected_text, "explanation": explanation,
                "chosen": chosen}

    # short answer: semantic grading
    system = """Grade a student's short quiz answer. Return STRICT JSON:
{"correct": <bool>, "score": <0.0-1.0>, "misconception": "<tag or null>",
 "explanation": "<1-2 sentence explanation of the correct answer>"}"""
    prompt = f"""Question: {question}
Expected answer: {expected_answer}
Student answer: "{student_answer}"
Concept: {concept}"""
    result = await generate_json(prompt, system=system, temperature=0.2,
                                 priority=BATCH)
    correct = bool(result.get("correct", False))
    score = float(result.get("score", 0.0) or 0.0)
    scored = points * score if not correct else points
    if correct and score == 0:
        score = 1.0
        scored = points
    misconception = result.get("misconception")
    explanation = result.get("explanation")
    db.add_quiz_result(session_id, question, expected_answer, student_answer,
                       correct, misconception, points, scored)
    if learner_id:
        db.update_mastery(learner_id, concept, score)
    db.log_event(session_id, "quiz_answer", {
        "question": question, "concept": concept, "given": student_answer,
        "correct": correct, "score": score, "mode": "short_answer",
        "misconception": misconception,
    })
    return {"correct": correct, "scored": scored, "points": points,
            "expected": expected_answer, "explanation": explanation,
            "misconception": misconception, "score": score}


def _normalize(s: str) -> str:
    import re
    s = s.lower().strip()
    s = re.sub(r"^\s*(option\s*)?[a-d][).:-]\s*", "", s)
    s = re.sub(r"[^\w\s\u0900-\u097F]", " ", s)
    return " ".join(s.split())


# ---------------------------------------------------------------------------
# Learning report
# ---------------------------------------------------------------------------

REPORT_SYSTEM = """You are the assessment engine of an AI teacher. Using the session's
checkpoint and quiz data, produce a personalized learning report. Return
STRICT JSON:
{
  "summary": "<2-3 sentence overall assessment in {LANG}>",
  "strong_areas": ["..."],
  "needs_improvement": ["..."],
  "misconceptions": ["<tag + one-line fix>"],
  "recommendations": ["<specific: 'Revise X and do 2 practice problems on Y'>"],
  "next_topic": "<what to learn next>",
  "homework": ["<1-3 concrete tasks>"]
}"""


async def generate_report(session_id: str, language: str) -> dict[str, Any]:
    """Compile the learning report for a finished session."""
    session = db.get_session(session_id)
    if not session:
        raise ValueError("Unknown session")
    quiz = db.get_quiz_results(session_id)
    stats = db.session_stats(session_id)
    events = db.get_events(session_id)

    # collect checkpoint outcomes from the event trace
    checkpoints = [e["payload"] for e in events if e["type"] == "checkpoint_eval"]
    concepts = {}
    for cp in checkpoints:
        c = cp.get("concept", "?")
        concepts.setdefault(c, []).append(cp.get("score", 0.0))

    lang_name = LANG_NAMES.get(language, "English")
    system = REPORT_SYSTEM.replace("{LANG}", lang_name)
    data = {
        "topic": session["topic"],
        "score_pct": stats["pct"],
        "quiz": [{"q": r["question"], "given": r["given"],
                  "expected": r["expected"], "correct": bool(r["correct"]),
                  "misconception": r["misconception"]} for r in quiz],
        "checkpoint_concepts": {k: (sum(v) / len(v)) for k, v in concepts.items()},
        "language": language,
    }
    prompt = "Session data:\n" + _json_of(data)
    result = await generate_json(prompt, system=system, temperature=0.4,
                                 priority=BATCH)

    report = {
        "session_id": session_id,
        "topic": session["topic"],
        "score_pct": stats["pct"],
        "questions": stats["questions"],
        "correct": stats["correct"],
        "strong_areas": result.get("strong_areas", []),
        "needs_improvement": result.get("needs_improvement", []),
        "misconceptions": result.get("misconceptions", []),
        "summary": result.get("summary", ""),
        "recommendations": result.get("recommendations", []),
        "next_topic": result.get("next_topic", ""),
        "homework": result.get("homework", []),
        "concept_scores": concepts,
    }
    db.set_report(session_id, report)
    db.log_event(session_id, "report", {"score_pct": stats["pct"],
                                        "next_topic": report["next_topic"]})
    return report


def _json_of(x: Any) -> str:
    import json
    return json.dumps(x, ensure_ascii=False, indent=1)
