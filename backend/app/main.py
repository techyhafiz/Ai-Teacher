"""FastAPI application assembly: routers, static frontend, WebSocket live relay.

The frontend is plain static files under web/ (no build step). The API key
NEVER reaches the browser — all Gemini calls go through this backend.
"""
from __future__ import annotations

try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import db
from .config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    db.init_db()
    # pre-register TPM model windows (judge-visible at /api/metrics)
    from .services.tpm_manager import register_default_models
    register_default_models()
    logging.getLogger("app").info("AI Teacher backend ready.")
    yield
    # shutdown
    from .services.tpm_manager import tpm
    tpm.shutdown()


app = FastAPI(title="AI Teacher", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- API routers ----------------------------------------------------------
from .routers import api, live as live_router  # noqa: E402

app.include_router(api.router, prefix="/api")
app.include_router(live_router.router, prefix="/api")


@app.get("/api/health")
async def health():
    return {"ok": True}


# ---- static frontend (served at /) ----------------------------------------
from pathlib import Path  # noqa: E402

web_dir = Path(settings.web_dir)
if web_dir.exists():
    app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")
