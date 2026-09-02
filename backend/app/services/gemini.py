"""Gemini API wrapper with TPM admission control.

All text-generation and embedding calls flow through here. The TPM manager
guards every call (queue-and-wait, never fail) and records actual usage.
"""
from __future__ import annotations

try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

import json
import logging
import re
from typing import Any, Optional, Sequence

from ..config import settings
from .tpm_manager import BATCH, LIVE, CAPTURE, tpm, register_default_models

log = logging.getLogger("gemini")

_client = None


def client():
    """Lazy-init the google-genai client (single instance)."""
    global _client
    if _client is None:
        if not settings.gemini_api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Copy backend/.env.example to backend/.env "
                "and paste your key."
            )
        from google import genai
        _client = genai.Client(api_key=settings.gemini_api_key)
        register_default_models()
    return _client


# ---------------------------------------------------------------------------
# Token estimation helpers (chars-based heuristic; actuals come from API)
# ---------------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars/token (safe overestimate)."""
    return max(16, int(len(text) / 3.2) + 8)


def estimate_live_session_tokens(script: str, system: str) -> int:
    """Estimate tokens for a Live performance-capture session.

    Speech runs ~2.5 words/sec and native-audio output costs ~25 tokens/sec,
    so output-audio tokens ~ words*10. Input text ~ words*2. Overestimate on
    purpose; actuals replace the reservation as soon as usage_metadata arrives.
    """
    words = len(script.split()) + len(system.split())
    return int(words * 12) + 600


# ---------------------------------------------------------------------------
# Text generation
# ---------------------------------------------------------------------------

async def generate_text(
    prompt: str,
    *,
    system: Optional[str] = None,
    priority: int = BATCH,
    temperature: float = 0.7,
    max_output_tokens: Optional[int] = None,
    history: Optional[Sequence[Any]] = None,
) -> str:
    """Plain text generation through the text model, TPM-guarded."""
    from google import genai as g
    c = client()

    contents: list[Any] = list(history or [])
    contents.append(g.types.Content(role="user",
                                    parts=[g.types.Part(text=prompt)]))

    cfg = g.types.GenerateContentConfig(
        system_instruction=system,
        temperature=temperature,
    )
    if max_output_tokens:
        cfg.max_output_tokens = max_output_tokens

    est = estimate_tokens(prompt) + estimate_tokens(system or "") + 1024

    async def _call() -> Any:
        return await c.aio.models.generate_content(
            model=settings.gemini_text_model,
            contents=contents,
            config=cfg,
        )

    def _usage(resp: Any) -> Optional[int]:
        try:
            return resp.usage_metadata.total_token_count
        except Exception:                                   # noqa: BLE001
            return None

    resp = await tpm.call(settings.gemini_text_model, est, _call, _usage,
                          priority=priority)
    return (resp.text or "").strip()


async def generate_json(
    prompt: str,
    *,
    system: Optional[str] = None,
    priority: int = BATCH,
    temperature: float = 0.5,
    max_output_tokens: Optional[int] = None,
    history: Optional[Sequence[Any]] = None,
) -> Any:
    """JSON-mode generation with robust extraction + one repair attempt.

    Returns the parsed JSON object. Raises ValueError if unparseable twice.
    """
    from google import genai as g
    c = client()

    contents: list[Any] = list(history or [])
    contents.append(g.types.Content(role="user",
                                    parts=[g.types.Part(text=prompt)]))

    cfg = g.types.GenerateContentConfig(
        system_instruction=system,
        temperature=temperature,
        response_mime_type="application/json",
    )
    if max_output_tokens:
        cfg.max_output_tokens = max_output_tokens

    est = estimate_tokens(prompt) + estimate_tokens(system or "") + 4096

    async def _call() -> Any:
        return await c.aio.models.generate_content(
            model=settings.gemini_text_model,
            contents=contents,
            config=cfg,
        )

    def _usage(resp: Any) -> Optional[int]:
        try:
            return resp.usage_metadata.total_token_count
        except Exception:                                   # noqa: BLE001
            return None

    resp = await tpm.call(settings.gemini_text_model, est, _call, _usage,
                          priority=priority)
    text = (resp.text or "").strip()
    try:
        return _parse_json(text)
    except ValueError:
        log.warning("generate_json: first parse failed (%d chars), repairing",
                    len(text))
        repair_prompt = (
            "The following was supposed to be valid JSON but could not be parsed. "
            "Return ONLY the corrected, valid JSON with the same content — no "
            "commentary, no markdown fences:\n\n" + text[:50_000]
        )
        repaired = await generate_text(
            repair_prompt,
            system="You output only raw valid JSON. No prose. No code fences.",
            temperature=0.0,
            priority=priority,
        )
        return _parse_json(repaired)


def _parse_json(text: str) -> Any:
    """Parse JSON leniently: handles fences and leading junk."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # find outermost JSON object/array
    for start_char, end_char in (("{", "}"), ("[", "]")):
        start = text.find(start_char)
        end = text.rfind(end_char)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError(f"Could not parse JSON from: {text[:200]!r}")


# ---------------------------------------------------------------------------
# Embeddings (for RAG)
# ---------------------------------------------------------------------------

async def embed_texts(texts: Sequence[str], *, task: str = "retrieval_document"
                      ) -> list[list[float]]:
    """Embed texts in batches through the embedding model, TPM-guarded.

    task: 'retrieval_document' for indexing, 'retrieval_query' for queries.
    """
    from google import genai as g
    c = client()

    out: list[list[float]] = []
    batch_size = 90
    for i in range(0, len(texts), batch_size):
        batch = list(texts[i:i + batch_size])
        est = sum(estimate_tokens(t) for t in batch) + 128

        async def _call() -> Any:
            return await c.aio.models.embed_content(
                model=settings.gemini_embedding_model,
                contents=batch,
                config=g.types.EmbedContentConfig(task_type=task),
            )

        def _usage(resp: Any) -> Optional[int]:
            try:
                return resp.metadata.total_token_count
            except Exception:                               # noqa: BLE001
                return None

        resp = await tpm.call(settings.gemini_embedding_model, est, _call,
                              _usage, priority=BATCH)
        for emb in resp.embeddings:
            out.append(list(emb.values))
    return out


# Re-export priorities for convenience
__all__ = [
    "client", "generate_text", "generate_json", "embed_texts",
    "estimate_tokens", "estimate_live_session_tokens",
    "LIVE", "CAPTURE", "BATCH",
]
