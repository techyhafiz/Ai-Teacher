"""Central configuration for the AI Teacher backend.

All values can be overridden via environment variables (.env file next to backend/).
"""
from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BACKEND_DIR = Path(__file__).resolve().parent.parent          # ai-teacher/backend
PROJECT_DIR = BACKEND_DIR.parent                              # ai-teacher/
DATA_DIR = PROJECT_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
PROCESSED_DIR = DATA_DIR / "processed"
PLANS_DIR = DATA_DIR / "plans"
PERFORMANCES_DIR = DATA_DIR / "performances"
RECORDINGS_DIR = DATA_DIR / "recordings"
DB_DIR = DATA_DIR / "db"
CHROMA_DIR = DATA_DIR / "chroma"

for _d in (DATA_DIR, UPLOADS_DIR, PROCESSED_DIR, PLANS_DIR,
           PERFORMANCES_DIR, RECORDINGS_DIR, DB_DIR, CHROMA_DIR):
    _d.mkdir(parents=True, exist_ok=True)

DB_PATH = DB_DIR / "ai_teacher.sqlite"


class Settings(BaseSettings):
    """Runtime settings, overridable by .env."""

    # --- Gemini API -------------------------------------------------------
    # NOTE: model ids are plain strings so they can be swapped from .env
    # without touching code (user has: text model "flash lite 3.5" +
    # a Live preview model; ids may differ per console region).
    gemini_api_key: str = ""
    gemini_text_model: str = "gemini-3.5-flash-lite"          # planning / evals / OCR
    gemini_live_model: str = "gemini-2.5-flash-native-audio-preview"  # voice capture + live
    gemini_embedding_model: str = "text-embedding-004"

    # --- TPM limits (tokens per rolling 60s window) ------------------------
    tpm_text_model: int = 250_000
    tpm_live_model: int = 60_000
    tpm_embedding_model: int = 8_000_000   # free-tier is request-limited, tokens are generous
    # Fraction of the window we may commit before queueing (safety headroom)
    tpm_headroom: float = 0.85
    # Max concurrent performance captures (each holds a Live session)
    max_parallel_captures: int = 2
    # Max concurrent OCR page jobs
    max_parallel_ocr: int = 4

    # --- Server ------------------------------------------------------------
    host: str = "127.0.0.1"
    port: int = 8000
    web_dir: str = str(PROJECT_DIR / "web")

    class Config:
        env_file = str(BACKEND_DIR / ".env")
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()


def as_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")
