"""Optional 'Nano Banana' slide image generation (gemini-2.5-flash-image).

Off by default (``settings.slides_enabled``). Generates a single illustrative
PNG for a lesson segment and stores it under the session's performances dir.
Any failure returns ``None`` so callers fall back cleanly to the deterministic
code-drawn whiteboard (that is the "graceful fallback").
"""
from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any, Optional

from ..config import PERFORMANCES_DIR, settings

log = logging.getLogger("slides")

# Nudge the image model toward board-friendly, low-text illustrations that sit
# naturally on top of the chalkboard.
STYLE_SUFFIX = (
    " — clean educational chalkboard-style illustration, high contrast, "
    "minimal text, one clear labeled diagram, dark green chalkboard background, "
    "colored chalk strokes (white, yellow, cyan, pink, green). No watermark, "
    "no logos, no photorealism."
)


def slides_active() -> bool:
    """True only when slides are enabled AND an API key is configured."""
    return bool(settings.slides_enabled and settings.gemini_api_key)


def _slide_path(session_id: str, seg_id: int) -> Path:
    d = PERFORMANCES_DIR / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d / f"slide_seg_{int(seg_id):03d}.png"


def slide_url(session_id: str, seg_id: int) -> str:
    """Backend URL the frontend loads via the show_image whiteboard tool."""
    return f"/api/performances/{session_id}/slide_seg_{int(seg_id):03d}.png"


async def generate_slide(prompt: str, session_id: str, seg_id: int,
                         *, force: bool = False) -> Optional[str]:
    """Generate one slide PNG for a segment. Returns its URL, or None on any
    failure / when slides are disabled (caller then uses the code board only)."""
    if not slides_active():
        return None
    if not (prompt or "").strip():
        return None

    out = _slide_path(session_id, seg_id)
    if out.exists() and not force:
        return slide_url(session_id, seg_id)

    try:
        from .gemini import client
        c = client()
        full_prompt = prompt.strip() + STYLE_SUFFIX

        resp = await c.aio.models.generate_content(
            model=settings.gemini_image_model,
            contents=full_prompt,
        )
        data = _extract_image_bytes(resp)
        if not data:
            log.warning("slide gen: no image bytes returned for seg %s", seg_id)
            return None
        out.write_bytes(data)
        log.info("slide gen: wrote %s (%d bytes)", out.name, len(data))
        return slide_url(session_id, seg_id)
    except Exception as e:                                   # noqa: BLE001
        log.error("slide gen failed for seg %s: %s", seg_id, e)
        return None


def _extract_image_bytes(resp: Any) -> Optional[bytes]:
    """Pull raw image bytes out of a google-genai image response, tolerating
    SDK shape differences (bytes vs base64 str)."""
    try:
        for cand in (getattr(resp, "candidates", None) or []):
            content = getattr(cand, "content", None)
            for part in (getattr(content, "parts", None) or []):
                inline = getattr(part, "inline_data", None)
                data = getattr(inline, "data", None) if inline is not None else None
                if not data:
                    continue
                if isinstance(data, str):
                    return base64.b64decode(data)
                return bytes(data)
    except Exception as e:                                   # noqa: BLE001
        log.error("slide gen: failed to extract image bytes: %s", e)
    return None
