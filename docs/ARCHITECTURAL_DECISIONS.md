# AI Teacher — Architectural Decisions & Overnight Autonomy Log

**Date:** 2026-09-03  
**Status:** In Progress / Overnight Autonomous Execution  
**Goal:** Build, test, and complete the full AI Teacher application end-to-end.

---

## 1. Context & User Directives
* **User Directive:** "see im sleeping now, you have few hours. i want you to build test and complete the full app, the avatar,and everything very correct. also fix any ui problems or any app problems,do audit as many times as you want. Also it generates very basic board,tell it to use full creative animation shapes or whatever it can... try multiple tries with different prompts, or different tech stack for it to generate the board. in final do all e2e testing + browser interaction as normal user all testing... do not stop for qna, make decisions if ambiguous and note it in a md file."
* **Model Constraints:** Text model is `gemini-3.5-flash-lite`, Live model is `gemini-3.1-flash-live-preview`, Embedding model is `gemini-embedding-001`.

---

## 2. Key Decisions Made

### Decision 1: Chalkboard Visuals — Hybrid LLM + Deterministic Pedagogical Visual Synthesizer
* **Problem:** `gemini-3.5-flash-lite` often outputs minimal visual calls (e.g. 1-2 plain `write_text` bullets) because it lacks rich few-shot context.
* **Solution:**
  1. Provide comprehensive multi-modal few-shot visual examples in `planner.py` (circuit schematics, physics free-body diagrams, calculus derivative curves, optics ray tracing, biology cell structures, algorithms flowcharts).
  2. Implement an automatic **Pedagogical Visual Synthesizer (`enrich_segment_visuals`)**: if the LLM produces fewer than 2 visuals or no diagram/equation for a concept segment, the synthesizer automatically analyzes the concept and script keywords to construct multi-shape geometric diagrams (`draw_diagram` with boxes, arrows, vectors, colored chalk labels, formulas) so every segment is visually rich and creative.

### Decision 2: Chalkboard Renderer — Deep Green Slate & Animated Chalk Reveals
* **Problem:** Previous canvas used a light parchment background (`#f4ead8`) with brown ink, looking like a dull paper box rather than an inspiring schoolroom chalkboard.
* **Solution:**
  1. Updated canvas background to authentic dark forest blackboard green (`#16241b`) with slate gradient and organic chalk dust smudges.
  2. Vibrant luminous chalk palette: Pure White (`#f8fafc`), Sunny Yellow (`#fde047`), Cyan (`#38bdf8`), Pink (`#f472b6`), Mint Green (`#4ade80`), and Orange (`#fb923c`).
  3. Added **Chalk Stroke Animation Engine**: Diagrams and shapes trace their paths dynamically (boxes trace edges, arrows sweep forward, circles orbit, formulas fade in with chalk bloom) matching the teacher's narration timeline.

### Decision 3: Resilient Avatar Architecture — 3D Three.js + 2D High-Fidelity Fallback
* **Problem:** If a client browser lacks WebGL2 or hardware acceleration, the 3D model could stall.
* **Solution:**
  `Avatar3DEngine` initializes automatically with local GLTF models (`aarav.glb`, `meera.glb`, `bheem.glb`). If WebGL initialization fails, it seamlessly falls back to `TeacherAvatar2D`, maintaining voice lip-sync, blinking, and breathing without interruption.

### Decision 4: Checkpoint & Diagnostic Flow
* Checkpoints support both voice recording and typed input.
* Final quiz dynamically computes mastery percentage per concept and generates a comprehensive learning diagnostic report.

---

## 3. Implementation Phases
* **Phase A:** Visual Planner prompt upgrade & Pedagogical Visual Synthesizer (`planner.py`).
* **Phase B:** Dark chalkboard aesthetic & animated stroke rendering (`whiteboard.js` & `style.css`).
* **Phase C:** Classroom & Avatar integration audit (`classroom.js`).
* **Phase D:** Automated end-to-end testing with real headless Chromium browser simulation.
* **Phase E:** Verification and final audit.
