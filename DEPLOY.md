# Deploying AI Teacher for FREE (beginner guide)

This app is **one service**, not two. The FastAPI backend (in `backend/`) also serves
the frontend (the `web/` folder) *and* the live-voice WebSocket — all from a single web
address. So you deploy **one thing**, and both the "frontend" and "backend" come with it.

We'll use **Render** (https://render.com). It's the easiest free option: it connects to
your GitHub repo and redeploys automatically every time you push.

---

## Before you start

You need three things:

1. A **GitHub account** with this project pushed to it (you already have this:
   `github.com/techyhafiz/Ai-Teacher`).
2. A **Render account** — sign up free at https://render.com with your GitHub login.
3. Your **Gemini API key** (the `AQ.…` string in your local `backend/.env`).
   ⚠️ You will paste this into Render's dashboard — **never** commit it to GitHub.

Your `.env` file is already in `.gitignore`, so your key stays private. Good.

---

## Option A — Deploy with the Blueprint (easiest, uses `render.yaml`)

This repo already contains a `render.yaml` that describes everything.

1. Push your latest code to GitHub (see "Pushing your code" below if unsure).
2. Go to https://dashboard.render.com → click **New +** → **Blueprint**.
3. Pick your `Ai-Teacher` repository. Render reads `render.yaml` and shows the service.
4. It will ask you to fill in **`GEMINI_API_KEY`** (because it's marked secret). Paste
   your `AQ.…` key there.
5. Click **Apply** / **Create**. Render installs dependencies and starts the app.
6. When it says **Live**, click the URL (looks like `https://ai-teacher-xxxx.onrender.com`).
   That's your whole app — open it and use it like localhost.

Done. Skip to "Everyday use" below.

---

## Option B — Deploy manually through the dashboard (if the Blueprint gives trouble)

1. Go to https://dashboard.render.com → **New +** → **Web Service**.
2. Connect GitHub and select your `Ai-Teacher` repo.
3. Fill in these settings **exactly**:
   - **Root Directory:** `backend`
   - **Runtime / Language:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - **Instance Type:** `Free`
4. Scroll to **Environment Variables** and add these (click "Add" for each):

   | Key                      | Value                                   |
   |--------------------------|-----------------------------------------|
   | `GEMINI_API_KEY`         | *(your `AQ.…` key)*                     |
   | `GEMINI_TEXT_MODEL`      | `gemini-3.5-flash-lite`                 |
   | `GEMINI_LIVE_MODEL`      | `gemini-2.5-flash-native-audio-latest`  |
   | `GEMINI_EMBEDDING_MODEL` | `gemini-embedding-001`                  |
   | `GEMINI_IMAGE_MODEL`     | `gemini-2.5-flash-image`                |
   | `SLIDES_ENABLED`         | `false`                                 |
   | `TPM_TEXT_MODEL`         | `250000`                                |
   | `TPM_LIVE_MODEL`         | `60000`                                 |
   | `PYTHON_VERSION`         | `3.11.9`                                |

5. Click **Create Web Service**. Wait for the build (first build is slow — a few minutes).
6. When status is **Live**, open the URL at the top. That's your app.

> You do **not** upload your `.env` file to Render. The env vars above replace it.
> On your own PC the app reads `backend/.env`; on Render it reads these dashboard values.

---

## Pushing your code (if you're not sure how)

From the project folder in a terminal:

```bash
git add .
git commit -m "Deploy config + avatar/caption fixes"
git push
```

(Your `.env` won't be pushed — it's ignored.) Every future `git push` makes Render
rebuild and redeploy automatically.

---

## Everyday use

- **Open your app:** just visit your `https://…onrender.com` URL.
- **Update it:** push to GitHub → Render redeploys on its own.
- **Change the key or a setting:** edit the env var in the Render dashboard →
  **Manual Deploy** → **Clear build cache & deploy** (or just Save, then redeploy).

---

## Important free-tier limits (please read)

The free plan is great for a personal project / demo, but:

1. **It sleeps after ~15 minutes of no visitors.** The next visit takes ~30–60 seconds
   to "wake up." After that it's fast again. (Paid plans stay awake.)
2. **Storage is temporary.** Render's free disk resets on every restart/redeploy. This
   app saves lessons, audio, and its SQLite/ChromaDB data under `backend/data/`, so
   **those reset too.** Generated lessons won't persist across restarts. For a teaching
   demo that's usually fine. If you later want lessons to persist, the options are a
   Render **paid persistent disk**, or moving the database to a free hosted service —
   ask me and I'll wire that up.
3. **Microphone needs HTTPS** — Render gives you HTTPS automatically, so live voice works.
   (It would NOT work over plain `http://`, which is why localhost is special-cased.)

---

## If something goes wrong

- **Build fails / "No module named app":** check **Root Directory** is `backend` and the
  start command is `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
- **App starts then crashes / 500 on use:** you probably forgot `GEMINI_API_KEY`, or it
  has a typo/extra space. Re-check it in the dashboard.
- **Live voice won't connect:** make sure you're on the `https://` URL (not http), and
  that `GEMINI_LIVE_MODEL` is set to `gemini-2.5-flash-native-audio-latest`.
- **See the logs:** Render dashboard → your service → **Logs** tab. Copy any red error
  line and I can help.

---

## Other free options (not needed, just so you know)

- **Hugging Face Spaces** (Docker) — great for AI demos, free, but needs a Dockerfile.
- **Google Cloud Run** — generous free tier and doesn't sleep as aggressively, but needs
  Docker + the `gcloud` tool (more setup — not beginner-friendly).

Render is the right first choice. Come back to these only if you outgrow it.
