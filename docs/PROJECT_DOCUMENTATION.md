# AI Teacher — Project Documentation

**AI Innovation Hackathon 2026 — "AI Teacher: Build a Human-Like AI Educator That Teaches Through Video"**

Team submission for Task 1 (AI Teaching Video) and Task 2 (Interactive & Adaptive AI Teacher).

---

## 1. Problem Statement

Traditional digital learning platforms provide pre-recorded lectures or text-based AI assistants that fail to deliver the personalized interaction and adaptive teaching of a real teacher. The challenge is to build an AI-powered virtual teacher that:

- understands uploaded learning material (books, textbooks, PDFs, notes, DOC/DOCX, PPT/PPTX, research papers) or accepts a topic directly,
- creates a structured, personalized lesson (adapted to learner level, available time, preferred language),
- teaches through an AI-generated **video experience** — human-like avatar, natural voice, on-screen text, subject-appropriate visuals,
- behaves like a real teacher: plans, explains, demonstrates, **asks questions**, evaluates answers, identifies **misconceptions**, re-explains, adapts difficulty, confirms understanding before moving on,
- assesses at the end and produces a **learning report** (score, strong areas, weak areas, recommendations, next topic),
- supports **multiple languages** (English, Hindi, Hinglish in our build) including mid-lesson switching and cross-language material (English textbook → Hindi teaching).

A basic chatbot, a static video, or a talking avatar reading a script is explicitly **not** sufficient.

## 2. Solution Overview

**AI Teacher** is a web application in which a 3D human-like teacher (Ready Player Me avatar rendered with three.js/TalkingHead, lip-synced) stands beside a large chalk whiteboard and teaches a personalized lesson as a video-like experience. The heart of the system is **performance capture & replay**:

1. **Plan** — a Gemini Flash Lite planner generates a lesson plan of ordered segments (concept, narration script with easier/deeper variants, whiteboard visuals, checkpoint question), grounded in the uploaded material via RAG, adapted to level, time budget and language.
2. **Capture** — each segment script is *performed* through the Gemini Live API exactly once: we record the spoken audio (PCM → WAV), the actual spoken transcript, and a timestamped timeline of whiteboard visuals.
3. **Replay** — the classroom plays each performance deterministically: the avatar speaks with lip-sync while whiteboard visuals fire at their exact timestamps, subtitles show the spoken words. Zero API usage during playback.
4. **Interact** — at checkpoints the lesson pauses and opens a fresh **full-duplex live voice session** (via our backend relay, so the API key never reaches the browser). The student speaks; the teacher listens, evaluates with function calling (`evaluate_student`), responds warmly, and may draw on the board (`ask_whiteboard`) or switch language (`switch_language`).
5. **Adapt** — evaluation results drive a strict-gating state machine: wrong answers trigger misconception-tagged re-explanations (pre-planned simpler/deeper variants, or a live-generated new-analogy script + new re-check question), two consecutive perfect answers skip ahead.
6. **Assess & report** — a final quiz (MCQ + short answers) is graded, then a learning report is generated (score, strong/weak areas, misconceptions, recommendations, homework, next topic) and shown as a report card. The whole classroom session is recordable to a downloadable video (WebM).

Everything runs locally; the only external service is the Gemini API. All frontend libraries are vendored.

## 3. Key Features

- Upload PDF / DOCX / PPTX / TXT / MD; structure-aware parsing with heading/chapter/slide detection; **Gemini vision OCR** for scanned pages; chapter-focus requests ("teach me Chapter 4")
- Topic-based teaching with no material
- Learner profiles (SQLite): level, language, mastery per concept (EMA), session history, "welcome back" personalization
- Lesson plans adapted to 5 / 20 / 60 minutes; **7-day personalized study & revision plan** mode; learning paths for broad topics (milestones with prerequisites)
- Human-like avatar with natural voice (Gemini Live), lip-sync, gestures, blinking; three teacher personas (Aarav Sir / Meera Ma'am / Professor Bheem)
- Subject-aware chalk whiteboard: LaTeX equations (KaTeX), function plots, physics/circuit/geometric diagrams, history timelines, syntax-highlighted code with output, flowcharts, tables, simplified maps with markers
- Checkpoints between segments: MCQ / short-answer / problem-solving / application / explain-in-your-own-words; answered by **live voice** or text
- Misconception detection → targeted re-explanation with a different analogy → re-check before advancing (strict gating), skip-ahead on repeated mastery
- Mid-lesson language switching (EN/Hindi/Hinglish) by voice; cross-language teaching (English source → Hindi lesson)
- Final quiz + learning report card; recommendations and next-topic chaining
- "Raise hand" free-form Q&A anytime during the lesson
- Session recording → downloadable lesson video (WebM)
- TPM manager with live usage metrics (`/api/metrics`) guarding all API calls

## 4. System Architecture

See `README.md` for the architecture diagram and repository layout. Components:

- **Frontend (web/)** — vanilla JS SPA with 4 screens (setup, classroom, report, study-plan). No build step. Renders the avatar (TalkingHead + three.js), the whiteboard canvas (custom chalk renderer with 9 primitives + KaTeX), playback engine, live-voice client (mic capture → PCM 24 kHz over WebSocket; incoming PCM → TalkingHead streaming API), MediaRecorder session capture.
- **Backend (FastAPI)** — 17 REST endpoints + 1 WebSocket relay. Serves the frontend statically; keeps the Gemini key server-side.
- **TPM manager** — single chokepoint for all Gemini calls: per-model rolling 60-second token windows, admission control with priority lanes (LIVE=0 > CAPTURE=1 > BATCH=2), queue-and-wait throttling, actual-usage accounting from response metadata, 429 exponential backoff.
- **Storage (all local)** — SQLite (profiles, sessions, event trace, mastery, quiz), ChromaDB persistent vector store, WAV performance files + timeline JSON, uploaded materials, recordings.

### Why performance capture & replay?

A pre-rendered static video cannot pause for questions or adapt. Real-time generation cannot guarantee narration↔visual sync. Capture-and-replay gives both: the *experience* of video (perfectly synced avatar voice + animated whiteboard) with *interactivity* (deterministic replay pauses anywhere; live sessions open on demand).

## 5. AI/ML Models Used

| Role | Model | Why |
|---|---|---|
| Lesson planning, scripts, quiz generation, checkpoint evaluation, misconception analysis, quiz grading, OCR, report writing | **Gemini Flash Lite (3.5)** — text model | fast, cheap, 250k TPM; structured JSON outputs |
| Performance narration + live full-duplex conversation | **Gemini Live API (native audio)** | most natural speech, Hindi/Hinglish support, function calling during conversation, input/output transcription |
| RAG embeddings | **Gemini text-embedding** | multilingual (Hindi↔English retrieval), shared key |
| Lip-sync | met4citizen TalkingHead viseme engine (client-side, rule-based) | offline, no GPU |

No fine-tuning is used; all model behavior is steered via system prompts, JSON schemas, and function calling.

## 6. RAG Implementation

1. **Parsing** — PyMuPDF (PDF, with font-size-based heading detection), python-docx (heading styles + tables), python-pptx (slide titles + notes), plain text (markdown headings). Pages with <100 extractable characters are rendered to PNG and OCR'd by Gemini vision (up to 40 pages), including descriptions of figures (`[FIGURE: …]`).
2. **Chunking** — structure-aware: sections (heading → next heading) are the base unit; long sections split at paragraph boundaries with overlap (400 chars), target ~1200 tokens/chunk. Each chunk keeps `title` and `source` (page/slide) metadata.
3. **Index** — Gemini embeddings (`retrieval_document`) → ChromaDB persistent collection per document (cosine space).
4. **Hybrid retrieval** — for chapter-focused requests ("Chapter 4"), a TOC matcher resolves the chapter scope (numeric/word/roman numerals) and injects the matched sections as full context; otherwise vector search (top-k). Small materials are injected directly (long-context grounding); large ones use vector chunks. Every lesson segment carries citations back to pages/slides.
5. **Anti-hallucination** — planner is instructed to teach from the source and not contradict it; expected answers cite the material; quiz grading is anchored to expected answers.

## 7. Prompt / Agent Architecture

- **Planner** — system prompt (lesson-planner persona, JSON-only) + user prompt (request, level notes, language rule, time budget, learner history, grounded material, tool cheatsheet) → plan JSON (segments × scripts × visuals × checkpoints + quiz + homework + recommendations).
- **Capture** — Live API system instruction ("performance rules"): speak verbatim, obey `[VISUAL: …] [PAUSE]` stage directions, never mention being an AI; scripts embed stage directions computed from the visual timeline.
- **Teacher brain (checkpoints)** — evaluation prompt returns strict JSON: verdict, score, misconception tag + explanation, a spoken `teacher_reply` (warm, constructive), and a `teaching_move` (advance / re_explain / simplify / go_deeper / skip_ahead). Strict gating is enforced in code (never advance on uncorrected wrong answers).
- **Re-generation agent** — produces a misconception-targeted re-explanation (different analogy, new visual, new re-check question) when pre-planned variants are exhausted.
- **Live conversation agent** — Live API session with function calling: `evaluate_student` (structured verdict; one per checkpoint), `switch_language` (mid-lesson language change), `ask_whiteboard` (live drawings). Behavior rules: listen fully, short conversational turns, no AI mentions, target language discipline.
- **Quiz grader / report writer** — strict JSON prompts anchored on expected answers; MCQs graded exactly, short answers semantically.

## 8. Personalization Approach

- **Explicit**: level (beginner/intermediate/advanced → planner depth rules + script variants), language, time budget, teacher persona.
- **Implicit / historical**: SQLite profile summary (topics studied, per-concept mastery bands, weak concepts) is injected into every planning prompt; follow-up sessions adapt ("last time you struggled with resistance — we'll revise it first"); revision lessons can be built from mastery data; report recommendations chain into the next session with one click.
- **Runtime**: each segment has main/simpler/deeper script variants — the teaching move selects one without regenerating; live regen targets the exact misconception detected.

## 9. Assessment Methodology

- **Checkpoints** during the lesson (per concept segment): 5 question types (MCQ, short answer, problem-solving, application, explain-in-your-words), evaluated by the teacher brain with misconception tagging; re-checks after re-explanations.
- **Mastery tracking**: exponential moving average per concept (α=0.4) updated by every checkpoint and quiz answer.
- **Final quiz**: 3–7 questions (time-budget dependent), mixed MCQ + short answers; MCQs graded exactly; short answers graded semantically (partial credit).
- **Learning report**: score %, question stats, strong areas, needs improvement, misconceptions (tag + fix), summary, recommendations (specific: revise X, do 2 practice problems on Y), suggested next topic, homework tasks.

## 10. Multilingual Implementation

- Languages: **English, Hindi (Devanagari), Hinglish** (Roman-script code-mixing, as spoken in India).
- All spoken content is generated in the target language (planner language rules per language, including code-mixing instructions for Hinglish); concept keys stay English for mastery tracking.
- Voice: the Live model speaks all three natively (Hindi text input → Hindi speech).
- Subtitles: derived from the *output transcription* — they reflect the actually spoken words in whatever language was spoken.
- Cross-language: material language ≠ teaching language works naturally (retrieval is language-agnostic via multilingual embeddings; scripts are written in the teaching language).
- Mid-lesson switching: language picker + the live agent's `switch_language` tool; session state updates; subsequent segments render in the new language.
- Whiteboard text (titles, labels) follows the teaching language; code stays as-is.

## 11. Voice Implementation

- **Lesson narration**: performed once per segment via the Live API (24 kHz PCM captured → WAV). Voice selection per persona (Charon/Kore/Fenrir prebuilt voices). Verbatim verification compares spoken transcript to the script (word-level Levenshtein ratio).
- **Live checkpoints**: fresh Live session per checkpoint over our WebSocket relay; student mic → PCM 16-bit 24 kHz → relay → `send_realtime_input`; teacher audio streams back through TalkingHead's streaming playback (AudioWorklet) with lip-sync.
- **Echo/feedback control**: mic capture with browser AEC; teacher audio plays through TalkingHead's graph.
- **Lip-sync**: word timings (from transcripts) drive the viseme engine for cached playback; streaming mode uses TalkingHead's chunk-driven visemes.

## 12. Avatar / Video Generation Approach

- **Avatar**: Ready Player Me full-body GLB avatars (three selectable teacher personas) rendered client-side by three.js via met4citizen TalkingHead — ARKit viseme blendshapes, blinking, idle motion, head movement, gestures.
- **Teaching video**: the classroom *is* the video engine — avatar + chalk whiteboard composite, synchronized by the captured timeline. This makes the "video" adaptive (it pauses, questions, re-explains) rather than a static MP4.
- **Export**: MediaRecorder captures the composited classroom (canvas stream of avatar + whiteboard) as WebM during the session; "Download lesson video" appears on the report screen.
- **Whiteboard visuals are code-drawn** (no image generation): 9 primitives (text, KaTeX equations, graphs, diagrams incl. circuit symbols & vectors, timelines, code blocks, maps, flowcharts, tables) — all rendered as chalk-style canvas graphics.

## 13. APIs and Third-Party Services

- **Gemini API** (user-provided key): text model (planning/evaluation/OCR/grading), Live API (voice), embeddings (RAG). The only external service.
- **Ready Player Me** — avatar GLB files (fetched once at runtime, may be cached).
- Open-source libraries (all vendored or local): FastAPI, uvicorn, ChromaDB, PyMuPDF, python-docx, python-pptx, numpy, three.js, met4citizen TalkingHead (+ lipsync modules + AudioWorklet), KaTeX.
- No analytics, no databases in the cloud, no other APIs.

## 14. Setup Instructions

See `README.md` — Quick start: `pip install -r requirements.txt`, copy `.env.example` → `.env` with `GEMINI_API_KEY` (model ids configurable), `python run.py`, open http://127.0.0.1:8000 (Chrome/Edge recommended for mic + WebGL).

## 15. Deployment Instructions

- **Local demo** (default): `python run.py` serves API + frontend on 127.0.0.1:8000. All storage under `ai-teacher/data/`.
- **LAN/HTTPS deployment**: run uvicorn with `--host 0.0.0.0` behind an HTTPS reverse proxy (mic access requires a secure context; localhost is exempt). Example: Caddy/nginx → `http://127.0.0.1:8000`. The Gemini key stays server-side in `.env`.
- No other infrastructure is required; state is fully portable (copy the `data/` directory).

## 16. Known Limitations

1. Verbatim narration can drift slightly; we measure it and accept the spoken words as canonical (subtitles always match the actual audio).
2. Lesson export is WebM (VP8/VP9) — not MP4/H.264 (browser codec licensing).
3. Hindi lip-sync uses the English viseme engine (approximate mouth shapes; pauses respected).
4. OCR capped at 40 scanned pages per document; uploads capped at 60 MB.
5. Live voice requires a quiet environment and Chrome/Edge (WebGL2 + AudioWorklet + mic permissions).
6. Long lessons (60 min) take a few minutes to capture up front ( TPM-paced); progress is shown.
7. Maps are simplified outlines (teaching aid, not cartography).

---

## Demo video script (3–7 min)

1. **[0:00]** Setup: create learner, pick *Hindi*, beginner, 20 minutes, upload a textbook PDF, focus "Chapter 4".
2. **[0:30]** Show planning progress; explain capture ("the teacher records his performance — audio + visuals timeline").
3. **[0:50]** Classroom: avatar teaches Ohm's law; whiteboard draws equation `V = IR`, circuit diagram, then a graph — synchronized with narration; subtitles in Hindi.
4. **[2:00]** Checkpoint: answer by voice (mic); teacher evaluates and responds; **deliberately answer wrong** → show the reasoning badge ("misconception: thinks current increases with resistance") → teacher re-explains with the water-pipe analogy, new drawing, re-check question.
5. **[3:30]** Language switch: say "ab English mein samjhao" → teacher continues in English (badge logs the switch).
6. **[4:00]** Raise hand: ask a free-form question; teacher answers by voice with a quick sketch.
7. **[4:40]** Final quiz: two MCQs + one typed answer.
8. **[5:10]** Learning report: score, strong/weak areas, misconceptions, recommendations, next topic; click "Download lesson video" → WebM plays.
9. **[5:40]** TPM metrics screen (`/api/metrics`): live token usage per model — quota-safe by design.
