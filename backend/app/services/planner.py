"""Lesson planner — generates the teaching session plan.

Plan structure (per locked architecture):
  {
    session_id, topic, language, level, time_budget,
    learner_context: <compact profile summary>,
    grounding: {mode, citations[], ocr_used}          # RAG evidence
    segments: [
      {
        seg_id, kind: 'intro'|'concept'|'example'|'recap'|'assessment_intro',
        concept,                                      # concept taught
        script: {main, simpler, deeper},              # narration variants
        visuals: [ {tool, args, after_sentence: n} ]  # whiteboard calls
        checkpoint: {question, expected_answer, question_type, hint} | null
      }, ...
    ],
    quiz: [ {q, options[], answer_index, explanation, points, concept} ],
    homework: [ ... ],
    recommendations: [ ... ],
    est_duration_min
  }

Time budgets (adaptive structure):
  5 min  -> 1-2 segments, concise core concepts, 1-2 checkpoints
  20 min -> 4-6 segments, key concepts + examples, checkpoint per segment
  60 min -> 8-12 segments, deep explanations + worked examples + recap,
            checkpoints per segment + quiz of 6-8 questions
  7 days -> study_plan mode: day-by-day schedule (NOT captured as video)
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from .. import db
from ..config import settings
from .gemini import BATCH, generate_json, generate_text, estimate_tokens
from .rag import retrieve, retrieve_for_focus
from .whiteboard import TOOL_DEFINITIONS

log = logging.getLogger("planner")

LANG_NAMES = {"en": "English", "hi": "Hindi", "hinglish": "Hinglish (Hindi-English mix, "
             "Roman script, natural code-mixing)"}

TIME_BUDGETS = {
    "5min": {"segments": 2, "quiz_questions": 3, "depth_note":
             "concise: only the most important concepts, brief examples"},
    "20min": {"segments": 5, "quiz_questions": 4, "depth_note":
             "structured: key concepts with one example each"},
    "60min": {"segments": 9, "quiz_questions": 7, "depth_note":
              "deep: thorough explanations, worked examples, connections between concepts"},
    "7days": {"segments": 0, "quiz_questions": 0, "depth_note": "study plan mode"},
}


def _tools_cheatsheet() -> str:
    lines = []
    for t in TOOL_DEFINITIONS:
        req = t["parameters"].get("required", [])
        lines.append(f"- {t['name']}: {t['description']} (required: {', '.join(req)})")
    return "\n".join(lines)


def _language_rule(language: str) -> str:
    if language == "hi":
        return ("Write ALL scripts in Hindi (Devanagari script). Use simple, warm "
                "teacher Hindi. Technical terms may keep English names in Roman "
                "script where natural (e.g. 'current', 'resistance') — the way "
                "Indian teachers actually speak.")
    if language == "hinglish":
        return ("Write ALL scripts in Hinglish: natural Hindi-English code-mixing "
                "in Roman script, exactly how Indian students speak "
                "('Toh dekho, current ko flow of charge kehte hain...'). Keep it "
                "warm, friendly and natural — never artificial.")
    return "Write ALL scripts in clear, warm, simple English."


async def plan_lesson(
    session_id: str,
    *,
    learner_id: str,
    mode: str,                       # 'topic' | 'upload'
    topic_request: str,              # what the user asked for
    language: str,                   # 'en' | 'hi' | 'hinglish'
    level: str,                      # 'beginner' | 'intermediate' | 'advanced'
    time_budget: str,                # '5min' | '20min' | '60min' | '7days'
    doc_id: Optional[str] = None,
    doc_focus: Optional[str] = None, # e.g. 'chapter 4'
    persona: str = "Aarav Sir",
) -> dict[str, Any]:
    """Generate the full lesson plan. Returns the plan dict."""
    lang_name = LANG_NAMES.get(language, "English")
    budget = TIME_BUDGETS.get(time_budget, TIME_BUDGETS["20min"])

    learner_context = db.learner_profile_summary(learner_id)

    # ---------------- grounding ----------------
    grounding_ctx = ""
    citations: list[str] = []
    ground_mode = "none"
    if mode == "upload" and doc_id:
        try:
            if doc_focus:
                res = await retrieve_for_focus(doc_id, doc_focus, topic_request)
            else:
                res = await retrieve(doc_id, topic_request, k=10)
            ground_mode = res["mode"]
            if res.get("full_text"):
                grounding_ctx = (
                    "=== SOURCE MATERIAL (authoritative — teach from this, cite it, "
                    "do not contradict it) ===\n" + res["full_text"][:180_000]
                )
                citations = res.get("citations", [])
            else:
                chunks_txt = "\n\n".join(
                    f"[{c['title']} — {c['source']}]\n{c['text']}"
                    for c in res.get("chunks", [])
                )
                grounding_ctx = (
                    "=== SOURCE MATERIAL EXCERPTS (authoritative — teach from "
                    "these, cite them, do not contradict them) ===\n" + chunks_txt
                )
                citations = [f"{c['title']} ({c['source']})" for c in res.get("chunks", [])]
        except Exception as e:                              # noqa: BLE001
            log.error("Grounding failed, continuing without: %s", e)

    # ---------------- study plan mode (7 days) ----------------
    if time_budget == "7days":
        return await _plan_study_schedule(session_id, learner_id, topic_request,
                                          language, level, learner_context,
                                          grounding_ctx)

    # ---------------- main planner prompt ----------------
    n_seg = budget["segments"]
    n_quiz = budget["quiz_questions"]

    tools_cheatsheet = _tools_cheatsheet()
    lang_rule = _language_rule(language)

    level_note = {
        "beginner": ("Learner is a BEGINNER: use simple terminology, everyday "
                     "analogies, avoid jargon (define it when needed), focus on "
                     "fundamental intuition."),
        "intermediate": ("Learner is INTERMEDIATE: balance intuition with "
                         "technical explanation, include practical examples."),
        "advanced": ("Learner is ADVANCED: use precise technical terminology, "
                     "include mathematics/implementation details, advanced "
                     "examples and edge cases."),
    }[level]

    system = (
        "You are an expert lesson planner for an AI teacher that teaches through "
        "a talking avatar with a chalk whiteboard. You produce ONLY valid JSON "
        "matching the requested schema. Be concrete and practical; every segment "
        "must have a clear teaching purpose."
    )

    prompt = f"""Create a personalized lesson plan.

LEARNER REQUEST: "{topic_request}"
TEACHING LANGUAGE: {lang_name}
LEVEL: {level}
TIME BUDGET: {time_budget} ({budget['depth_note']}) — target ~{n_seg} teaching segments
(brief intro + concepts + recap; the model may merge concepts if genuinely needed).
{level_note}

{learner_context}

{grounding_ctx}

RULES:
1. {lang_rule} (applies to ALL script text, questions, quiz, everything spoken)
2. Segments: each teaches ONE concept. First segment is a short intro, last is a
   recap. Every 'concept' segment (not intro/recap) gets a checkpoint question
   (mix types: mcq, short_answer, problem_solving, application, explain_own_words).
3. Each script variant: main / simpler / deeper. Each is spoken narration
   (~{max(40, 60 // max(1, n_seg // 3))}-{120 // max(1, n_seg // 4) + 60} words for main
   per segment, adjusted to fit the time budget: {time_budget} total).
4. visuals: Whiteboard visuals MUST BE CREATIVE AND MULTI-LAYERED!
   NEVER output just plain text for concepts.
   - For SCIENCE/PHYSICS/ENGINEERING: Use 'draw_diagram' with at least 3-5 shapes (battery, resistor, bulb, vectors, arrows, boxes with labels, wires).
   - For MATHEMATICS/CALCULUS: Use 'draw_equation' with step-by-step LaTeX derivations and 'plot_graph' with labeled functions and points.
   - For PROCESSES/FLOWS: Use 'draw_flowchart' with nodes and labeled edges.
   - For COMPARISONS: Use 'show_table' or 'draw_diagram' with side-by-side concept cards.
   Each visual should use chalk colors: 'yellow', 'blue', 'pink', 'green', 'white'.

VISUAL EXAMPLES FOR INSPIRATION:
- Circuit: {{"tool": "draw_diagram", "args": {{"title": "Ohm's Law Circuit", "shapes": [{{"kind": "battery", "x": 20, "y": 50, "voltage": 12, "label": "12V", "chalk": "yellow"}}, {{"kind": "wire", "points": [20, 42, 20, 20, 80, 20, 80, 42], "chalk": "blue"}}, {{"kind": "resistor", "x": 80, "y": 50, "label": "R = 6 Ω", "chalk": "pink"}}, {{"kind": "wire", "points": [80, 58, 80, 80, 20, 80, 20, 58], "chalk": "blue"}}, {{"kind": "arrow", "x": 45, "y": 20, "x2": 55, "y2": 20, "label": "Current I = 2A →", "chalk": "green"}}]}}}}
- Forces: {{"tool": "draw_diagram", "args": {{"title": "Free Body Diagram", "shapes": [{{"kind": "line", "points": [15, 65, 85, 65], "chalk": "white"}}, {{"kind": "rect", "x": 50, "y": 55, "w": 20, "h": 16, "label": "Mass m", "chalk": "yellow", "fill": true}}, {{"kind": "vector", "x": 50, "y": 55, "x2": 50, "y2": 78, "label": "Gravity mg", "chalk": "pink"}}, {{"kind": "vector", "x": 50, "y": 55, "x2": 50, "y2": 32, "label": "Normal N", "chalk": "blue"}}, {{"kind": "vector", "x": 50, "y": 55, "x2": 75, "y2": 55, "label": "Force F →", "chalk": "green"}}]}}}}
- Calculus: {{"tool": "plot_graph", "args": {{"title": "f(x) = x² - 2x", "functions": [{{"fn": "x**2 - 2*x", "label": "f(x)", "color": "yellow"}}, {{"fn": "2*x - 4", "label": "Tangent (Slope = 2)", "color": "pink"}}], "x_range": [-2, 4], "x_label": "x", "y_label": "f(x)"}}}}

5. checkpoint: the question the teacher asks, expected_answer, question_type
   (mcq|short_answer|problem_solving|application|explain_own_words),
   options (for mcq: 2-4 options), answer_index (for mcq), hint.
6. quiz: {n_quiz} final assessment questions (mix mcq + short_answer), each
   mapped to a concept with explanation.
7. Concept names must be in English (used for mastery tracking), all spoken
   content in {lang_name}.

Available whiteboard tools:
{tools_cheatsheet}

Return JSON with EXACTLY this structure:
{{
  "lesson_title": "short lesson title",
  "est_duration_min": <number>,
  "segments": [
    {{
      "seg_id": <int starting 0>,
      "kind": "intro|concept|example|recap",
      "concept": "<concept name in English>",
      "script": {{"main": "<spoken text>", "simpler": "<simpler variant>",
                  "deeper": "<deeper variant>"}},
      "visuals": [{{"tool": "<tool name>", "args": {{...}}, "after_sentence": <int>}}],
      "checkpoint": {{"question": "...", "expected_answer": "...",
                      "question_type": "mcq|short_answer|problem_solving|application|explain_own_words",
                      "options": ["..."], "answer_index": <int or null>,
                      "hint": "..."}} or null,
    }}
  ],
  "quiz": [
    {{"q": "...", "options": ["..."] or null, "answer_index": <int or null>,
      "expected_answer": "...", "explanation": "...", "points": 1.0,
      "concept": "<concept name>"}}
  ],
  "homework": ["2-3 practice tasks"],
  "recommendations": ["what to learn/revise next, 2-3 items"]
}}"""

    plan = await generate_json(prompt, system=system, temperature=0.6,
                               priority=BATCH)

    # normalize + attach metadata
    plan["session_id"] = session_id
    plan["mode"] = mode
    plan["doc_id"] = doc_id
    plan["topic"] = topic_request
    plan["language"] = language
    plan["level"] = level
    plan["time_budget"] = time_budget
    plan["learner_id"] = learner_id
    plan["persona"] = persona
    plan["grounding"] = {"mode": ground_mode, "citations": citations[:20]}
    if not plan.get("segments"):
        raise ValueError("Planner returned no segments")
    for i, seg in enumerate(plan["segments"]):
        seg["seg_id"] = i
        seg.setdefault("visuals", [])
        seg.setdefault("checkpoint", None)
        # Guarantee rich visual diagrams on every concept segment
        enrich_segment_visuals(seg, topic_request)
    plan.setdefault("quiz", [])
    plan.setdefault("homework", [])
    plan.setdefault("recommendations", [])

    db.set_plan(session_id, plan)
    db.log_event(session_id, "plan", {
        "title": plan.get("lesson_title"),
        "segments": len(plan["segments"]),
        "quiz": len(plan["quiz"]),
        "language": language, "level": level, "time_budget": time_budget,
        "grounding": ground_mode, "citations": citations[:20],
    })
    return plan


def enrich_segment_visuals(seg: dict, topic: str) -> None:
    """Ensure every segment has creative, colorful whiteboard visuals.
    Synthesizes schematic diagrams, formulas, or graphs when LLM output is sparse."""
    visuals = seg.get("visuals", [])
    has_diagram = any(
        v.get("tool") in ("draw_diagram", "plot_graph", "draw_flowchart")
        for v in visuals
    )
    has_equation = any(v.get("tool") == "draw_equation" for v in visuals)
    if has_diagram and has_equation:
        return

    concept = seg.get("concept", topic or "Core Concept")
    script = seg.get("script", {}).get("main", "")
    corpus = (concept + " " + script + " " + topic).lower()

    # 1. Circuits & Electricity
    if any(k in corpus for k in ["circuit", "ohm", "volt", "current", "resistor", "battery", "ampere", "electricity"]):
        seg.setdefault("visuals", []).append({
            "tool": "draw_diagram",
            "after_sentence": 1,
            "args": {
                "title": f"{concept}: Circuit Diagram",
                "clear_first": False,
                "shapes": [
                    {"kind": "battery", "x": 20, "y": 50, "voltage": 12, "label": "12V Battery", "chalk": "yellow"},
                    {"kind": "wire", "points": [20, 42, 20, 22, 80, 22, 80, 42], "chalk": "blue"},
                    {"kind": "resistor", "x": 80, "y": 50, "label": "R = 6 Ω", "chalk": "pink"},
                    {"kind": "wire", "points": [80, 58, 80, 78, 20, 78, 20, 58], "chalk": "blue"},
                    {"kind": "arrow", "x": 42, "y": 22, "x2": 58, "y2": 22, "label": "Current I →", "chalk": "green"}
                ]
            }
        })
        seg["visuals"].append({
            "tool": "draw_equation",
            "after_sentence": 2,
            "args": {
                "label": "Ohm's Law Formula",
                "latex": "V = I \\times R \\quad \\implies \\quad I = \\frac{V}{R} = \\frac{12\\text{V}}{6\\,\\Omega} = 2\\text{A}",
                "chalk": "yellow"
            }
        })
        return

    # 2. Mechanics, Forces, Newton, Gravity
    if any(k in corpus for k in ["force", "newton", "gravity", "friction", "motion", "velocity", "acceleration", "mass"]):
        seg.setdefault("visuals", []).append({
            "tool": "draw_diagram",
            "after_sentence": 1,
            "args": {
                "title": f"{concept}: Free-Body Diagram",
                "clear_first": False,
                "shapes": [
                    {"kind": "line", "points": [10, 68, 90, 68], "chalk": "white"},
                    {"kind": "rect", "x": 50, "y": 54, "w": 22, "h": 16, "label": "Mass (m)", "chalk": "yellow", "fill": True},
                    {"kind": "vector", "x": 50, "y": 54, "x2": 50, "y2": 80, "label": "F_g = mg", "chalk": "pink"},
                    {"kind": "vector", "x": 50, "y": 54, "x2": 50, "y2": 28, "label": "F_N (Normal)", "chalk": "blue"},
                    {"kind": "vector", "x": 50, "y": 54, "x2": 76, "y2": 54, "label": "Applied Force →", "chalk": "green"},
                    {"kind": "vector", "x": 50, "y": 54, "x2": 30, "y2": 54, "label": "← Friction", "chalk": "pink"}
                ]
            }
        })
        seg["visuals"].append({
            "tool": "draw_equation",
            "after_sentence": 2,
            "args": {
                "label": "Newton's Second Law",
                "latex": "\\sum \\vec{F} = m \\cdot \\vec{a} \\implies \\vec{a} = \\frac{\\vec{F}_{\\text{net}}}{m}",
                "chalk": "yellow"
            }
        })
        return

    # 3. Math, Calculus, Functions, Derivatives
    if any(k in corpus for k in ["calculus", "derivative", "integral", "slope", "graph", "function", "quadratic", "trig", "sine"]):
        seg.setdefault("visuals", []).append({
            "tool": "plot_graph",
            "after_sentence": 1,
            "args": {
                "title": f"{concept}: Geometric Graph",
                "functions": [
                    {"fn": "x**2 - 2", "label": "f(x) = x² - 2", "color": "yellow"},
                    {"fn": "2*x - 3", "label": "Tangent Line (Slope = 2x)", "color": "pink"}
                ],
                "x_range": [-3, 3],
                "x_label": "x",
                "y_label": "f(x)"
            }
        })
        seg["visuals"].append({
            "tool": "draw_equation",
            "after_sentence": 2,
            "args": {
                "label": "Derivative Definition",
                "latex": "\\frac{df}{dx} = \\lim_{h \\to 0} \\frac{f(x+h) - f(x)}{h}",
                "chalk": "yellow"
            }
        })
        return

    # 4. Computer Science, Logic, Algorithms
    if any(k in corpus for k in ["algorithm", "loop", "array", "binary", "tree", "sort", "search", "stack", "code", "programming"]):
        seg.setdefault("visuals", []).append({
            "tool": "draw_flowchart",
            "after_sentence": 1,
            "args": {
                "title": f"{concept}: Logic Flow",
                "nodes": [
                    {"id": "start", "text": "Start / Input", "shape": "pill", "x": 50, "y": 15, "chalk": "blue"},
                    {"id": "cond", "text": "Condition Met?", "shape": "diamond", "x": 50, "y": 42, "chalk": "yellow"},
                    {"id": "proc", "text": "Execute Step", "shape": "rect", "x": 50, "y": 70, "chalk": "white"},
                    {"id": "done", "text": "Output Result", "shape": "pill", "x": 82, "y": 42, "chalk": "green"}
                ],
                "edges": [
                    {"from": "start", "to": "cond", "chalk": "white"},
                    {"from": "cond", "to": "proc", "label": "True", "chalk": "green"},
                    {"from": "cond", "to": "done", "label": "False", "chalk": "pink"}
                ]
            }
        })
        return

    # 5. Universal Conceptual Diagram: 3-Box Architecture
    seg.setdefault("visuals", []).append({
        "tool": "draw_diagram",
        "after_sentence": 1,
        "args": {
            "title": f"Key Model: {concept}",
            "clear_first": False,
            "shapes": [
                {"kind": "rect", "x": 20, "y": 50, "w": 22, "h": 22, "label": "1. Input / Foundation", "chalk": "blue"},
                {"kind": "arrow", "x": 31, "y": 50, "x2": 44, "y2": 50, "label": "Drives", "chalk": "white"},
                {"kind": "rect", "x": 55, "y": 50, "w": 22, "h": 22, "label": f"2. {concept[:16]}", "chalk": "yellow", "fill": True},
                {"kind": "arrow", "x": 66, "y": 50, "x2": 79, "y2": 50, "label": "Yields", "chalk": "white"},
                {"kind": "rect", "x": 88, "y": 50, "w": 18, "h": 22, "label": "3. Result", "chalk": "green"}
            ]
        }
    })


# ---------------------------------------------------------------------------
# 7-day study planner
# ---------------------------------------------------------------------------

async def _plan_study_schedule(session_id: str, learner_id: str, topic_request: str,
                               language: str, level: str, learner_context: str,
                               grounding_ctx: str) -> dict[str, Any]:
    lang_name = LANG_NAMES.get(language, "English")
    system = (
        "You are a study-planner for an AI teacher. Produce ONLY valid JSON."
    )
    prompt = f"""Create a personalized 7-day study + revision schedule.

GOAL: "{topic_request}"
LANGUAGE for all schedule notes: {lang_name}
LEVEL: {level}

{learner_context}

{grounding_ctx}

Return JSON:
{{
  "lesson_title": "schedule title",
  "kind": "study_plan",
  "days": [
    {{"day": 1, "focus": "<topic area>", "activities": ["..."],
      "revision_of": ["<past weak concept or null>"], "minutes": <int>}}
  ],
  "weekly_goal": "...",
  "recommendations": ["..."]
}}"""
    plan = await generate_json(prompt, system=system, temperature=0.5,
                               priority=BATCH)
    plan["session_id"] = session_id
    plan["kind"] = "study_plan"
    plan["topic"] = topic_request
    plan["language"] = language
    plan["level"] = level
    plan["time_budget"] = "7days"
    plan["learner_id"] = learner_id
    db.set_plan(session_id, plan)
    db.log_event(session_id, "study_plan", {"title": plan.get("lesson_title"),
                                            "days": len(plan.get("days", []))})
    return plan


# ---------------------------------------------------------------------------
# Broad-topic learning path (§15)
# ---------------------------------------------------------------------------

async def plan_learning_path(topic_request: str, language: str,
                             learner_id: Optional[str] = None) -> dict[str, Any]:
    """Ordered milestone path for broad topics ('Machine Learning', 'Physics')."""
    learner_context = db.learner_profile_summary(learner_id) if learner_id else ""
    system = ("You are a curriculum designer for an AI teacher. Produce ONLY "
              "valid JSON.")
    prompt = f"""Design a learning path for the broad topic: "{topic_request}"
Language for path titles/descriptions: {LANG_NAMES.get(language, 'English')}
{learner_context}

Return JSON:
{{
  "path_title": "...",
  "milestones": [
    {{"id": <int>, "title": "...", "description": "...",
      "prerequisites": ["..."]}}
  ]
}}"""
    return await generate_json(prompt, system=system, temperature=0.4,
                                priority=BATCH)
