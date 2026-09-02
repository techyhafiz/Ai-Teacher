# 🎓 AI Teacher — Build a Human-Like AI Educator That Teaches Through Video

**AI Innovation Hackathon 2026 — Round 2 Technical Assessment · Bharat Academix**

An AI teacher that takes any **topic** or **uploaded learning material** (PDF/DOCX/PPTX/TXT/MD), plans a personalized lesson, and teaches it through a **human-like 3D avatar with natural voice and a live chalk whiteboard** — pausing to ask questions, detecting misconceptions, re-explaining adaptively, and finishing with an assessment and learning report.

```
Upload/Topic → Lesson Plan → Performance Capture (voice + visuals timeline)
            → Classroom Video Playback → Checkpoint Questions (live voice)
            → Misconception Detection → Adaptive Re-explanation → Final Quiz
            → Learning Report → "Download lesson video" (WebM)
```

---

## ✨ What it does

| Capability | How |
|---|---|
| **Teach from material** | Upload PDF/DOCX/PPTX/TXT → structure-aware parsing (headings, chapters, slides) + Gemini vision OCR for scanned pages → RAG (ChromaDB + Gemini embeddings) |
| **Teach any topic** | No material needed — planner builds from model knowledge + learner profile |
| **Personalized** | Learner level (beginner/intermediate/advanced), language, teaching style, time budget (5/20/60 min, 7-day study plan) |
| **Human-like teaching** | Understand → Plan → Explain → Demonstrate → Question → Evaluate → Adapt → Continue; strict gating (never advances on uncorrected wrong answers), skip-ahead on 2 perfect answers |
| **AI teaching video** | "Performance capture & replay": each segment is *performed once* through the Gemini Live API — audio (PCM→WAV) + timestamped whiteboard visuals — then replayed with perfect sync through a Ready Player Me 3D avatar (met4citizen TalkingHead, lip-synced) |
| **Subject-aware visuals** | 9 code-drawn whiteboard primitives: text, LaTeX equations (KaTeX), function graphs, physics/circuit diagrams, timelines, syntax-highlighted code, maps, flowcharts, tables — chosen by the planner per subject |
| **Interactive** | Checkpoints between segments; student answers by **full-duplex live voice** (or typed); teacher listens, evaluates, responds in the same voice |
| **Misconception detection** | Evaluator tags misconceptions (e.g., `thinks_current_increases_with_resistance`) and generates a *targeted* re-explanation with a new analogy + re-check |
| **Multilingual** | English, Hindi (Devanagari), and Hinglish — picker at setup + natural mid-lesson switching via voice (`switch_language` tool) |
| **Assessment + report** | Final quiz (MCQ cards + typed/spoken answers) → report card: score, strong areas, needs improvement, misconceptions, recommendations, next topic, homework |
| **Learner profiles** | SQLite persistence: mastery per concept (EMA-tracked), session history, "welcome back" personalization |
| **Learning paths** | Broad topics → milestone paths; 7-day study/revision plans |
| **Lesson video export** | Whole classroom (avatar + whiteboard) recorded via MediaRecorder → downloadable WebM |
| **TPM manager** | Every Gemini call passes a token-per-minute guard: rolling 60s windows, priority lanes (live > capture > batch), queue-and-wait, 429 backoff — never blows your quota. Live usage at `/api/metrics` |

Everything runs **locally** — the only external calls are to the Gemini API. All JS libraries (three.js, TalkingHead, KaTeX) are vendored into `web/libs/`.

---

## 🚀 Quick start

### Prerequisites
- Python 3.11+ 
- A Gemini API key (with access to a Live API model + a text model + embeddings)
- Chrome/Edge (for microphone + WebGL)

### Setup

```bash
cd ai-teacher/backend

# 1. install dependencies
pip install -r requirements.txt

# 2. configure your key
copy .env.example .env
#    edit .env: GEMINI_API_KEY=...  (and model ids if yours differ)

# 3. run
python run.py
```

Open **http://127.0.0.1:8000** in your browser.

### Try it

1. **Setup screen** — create a learner, pick language/level/time/teacher persona
2. **Topic tab**: type e.g. `Explain Ohm's Law to a Class 8 student` — *or*
   **Material tab**: drop a PDF (e.g. a textbook) and set focus `Chapter 4`
3. **Start Lesson** — the system plans, then *captures* the teacher's performance per segment (progress shown)
4. **Classroom** — avatar teaches with synchronized whiteboard visuals + subtitles; answer checkpoint questions by voice (mic) or typing; use 🤚 **Ask** anytime for free-form Q&A
5. **Quiz + Report** — final assessment, then the learning report card with recommendations; download the lesson video

### Configuration (`.env`)

| Key | Default | Notes |
|---|---|---|
| `GEMINI_API_KEY` | — | **required** |
| `GEMINI_TEXT_MODEL` | `gemini-3.5-flash-lite` | planning, scripts, evaluation, OCR, grading |
| `GEMINI_LIVE_MODEL` | `gemini-2.5-flash-native-audio-preview` | voice capture + live conversations |
| `GEMINI_EMBEDDING_MODEL` | `text-embedding-004` | RAG embeddings |
| `TPM_TEXT_MODEL` | `250000` | your quota's tokens-per-minute |
| `TPM_LIVE_MODEL` | `60000` | your Live API quota |
| `PORT` | `8000` | server port |

---

## 🏗️ Architecture

```
┌────────────────────── BROWSER (web/, no build step) ──────────────────────┐
│  Setup screen → Classroom → Report screen                                  │
│  · TalkingHead (Ready Player Me GLB avatar, three.js, viseme lip-sync)    │
│  · Chalk whiteboard canvas (9 drawing primitives, KaTeX equations)       │
│  · Playback engine: cached WAV + timeline → perfect A/V sync              │
│  · Live full-duplex voice (mic → PCM 24k → WS; WS → PCM → avatar stream)  │
│  · MediaRecorder → WebM lesson video download                              │
└────────────┬──────────────────────────────────────────────┬───────────────┘
             │ REST                                          │ WebSocket
┌────────────▼───────────── FastAPI backend ────────────────▼───────────────┐
│  /api/upload    parse (PyMuPDF/python-docx/python-pptx) + Gemini OCR        │
│  /api/sessions  plan (segments + variants + checkpoints + quiz)            │
│  /api/.../capture-one  performance capture via Live API → WAV + timeline   │
│  /api/.../checkpoint   evaluate answer, detect misconception, decide move  │
│  /api/.../regen         misconception-targeted re-explanation script       │
│  /api/.../quiz, /report grading + learning report                          │
│  /api/ws/live  relay: browser ⇄ Gemini Live (key never in browser)        │
│  TPM manager guards every call (rolling windows, priority, backoff)       │
└──────┬──────────────┬────────────────┬──────────────────┬────────────────┘
  ChromaDB       data/uploads     data/performances     data/db
  (RAG store)    (materials)      (WAV + timelines)     (SQLite)
```

### The teaching state machine (strict gating)

```
PLAN → INTRO → TEACH segment → CHECKPOINT ─ correct ─→ praise, ADVANCE
                                  │                partially ─→ RE-EXPLAIN (variant), re-check
                                  │                incorrect ─→ misconception analysis →
                                  │                             targeted RE-GEN (new analogy), re-check
                                  └ 2 perfect in a row → SKIP AHEAD
        … → RECAP → QUIZ → LEARNING REPORT
```

### Performance capture & replay (the video core)

At lesson start each segment script is sent to the Live API with strict verbatim
instructions + stage directions (`[VISUAL: tool] [PAUSE]`). We record:
- the audio stream (PCM 16-bit 24 kHz → WAV),
- the *actual spoken transcript* (output transcription → subtitle truth),
- a visual timeline (visual k fires after sentence k).

Replay is deterministic: audio drives the avatar's lip-sync; timeline events
draw the whiteboard at exact timestamps. Verbatim score (word-level Levenshtein)
verifies fidelity. **Zero tokens during playback** — the Live session is only
opened on demand at checkpoints (fresh session per checkpoint, full duplex).

---

## 📁 Repository layout

```
ai-teacher/
├─ backend/
│  ├─ app/
│  │  ├─ config.py            paths, models, TPM limits (.env overridable)
│  │  ├─ db.py                SQLite: learners, sessions, events, mastery, quiz
│  │  ├─ main.py              FastAPI app, static serving, routers
│  │  ├─ routers/
│  │  │  ├─ api.py            learners/upload/plan/capture/checkpoint/quiz/report/metrics
│  │  │  └─ live.py           Gemini Live WebSocket relay (full-duplex voice)
│  │  └─ services/
│  │     ├─ tpm_manager.py    token-per-minute guard (priority lanes)
│  │     ├─ gemini.py         text/JSON/embeddings via TPM manager
│  │     ├─ parser.py         PDF/DOCX/PPTX/TXT + OCR + structure detection
│  │     ├─ rag.py            structure-aware chunking, ChromaDB, hybrid retrieval
│  │     ├─ whiteboard.py     9-primitive tool schema + validation
│  │     ├─ planner.py        lesson plans, study plans (7-day), learning paths
│  │     ├─ capture.py        performance capture (Live API → WAV + timeline)
│  │     └─ brain.py          evaluation, misconceptions, regen, grading, reports
│  ├─ scripts/                test PDF generator, SDK inspection helpers
│  ├─ requirements.txt
│  └─ run.py
├─ web/                       (vanilla JS, no build step)
│  ├─ index.html              4 screens: setup / classroom / report / (study plan)
│  ├─ css/style.css           warm classroom theme
│  ├─ js/api.js               REST client
│  ├─ js/setup.js             learner + preferences + upload + kick-off
│  ├─ js/classroom.js         playback engine, checkpoints, live voice, recording
│  ├─ js/whiteboard.js        chalk canvas renderer (9 primitives)
│  └─ libs/                   vendored three.js, TalkingHead + lipsync, KaTeX
├─ docs/                      architecture + submission documentation
└─ data/                      uploads / processed / plans / performances /
                              recordings / db (SQLite) / chroma — all local
```

---

## 🔌 Third-party services & disclosure

| Component | Technology | License / cost |
|---|---|---|
| LLM (planning, evaluation, OCR, grading) | Gemini Flash Lite (user's API key) | paid API, per-token |
| Voice + Live conversations | Gemini Live API (native audio) | paid API, per-token |
| Embeddings (RAG) | Gemini text-embedding | free tier available |
| 3D avatars | Ready Player Me (GLB models, fetched once) | free tier |
| Avatar rendering + lip-sync | met4citizen **TalkingHead** (MIT), three.js (MIT) | open source |
| Math rendering | KaTeX (MIT) | open source |
| Vector store | ChromaDB (Apache-2.0) | open source, local |
| Document parsing | PyMuPDF (AGPL), python-docx (MIT), python-pptx (MIT) | open source |
| Backend | FastAPI/uvicorn (MIT) | open source |

No other external services. No data leaves the machine except Gemini API calls.

## ⚠️ Known limitations

- Verbatim capture can occasionally drift a word or two (we verify with a
  transcript-similarity score and fall back to the spoken words as truth).
- Recording is canvas+composite based → WebM (VP8/VP9); no H.264 MP4.
- Hindi lip-sync uses the English viseme model (works acceptably; Devanagari
  pauses are respected).
- Live voice requires Chrome/Edge + HTTPS or localhost (mic access policy).
- Large uploads (>60 MB) are rejected; scanned-PDF OCR is capped at 40 pages.

---

**Hackathon**: AI Innovation Hackathon 2026 · Task 1 (AI Teaching Video) + Task 2 (Interactive & Adaptive AI Teacher)
