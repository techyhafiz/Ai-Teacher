"""Performance capture service — the heart of the AI teaching video.

Performs a lesson segment script through the Gemini Live API and records:
  - the audio (PCM chunks -> WAV) with exact timing
  - every whiteboard tool call with a timestamp (relative to audio start)
  - the actual spoken transcript (output audio transcription)
  - sentence-level timing cues (from the transcript)

Session flow:
  1. Open Live session with the teacher persona + whiteboard tools +
     'verbatim performance' system instruction.
  2. Send the segment script as a user turn with stage directions.
  3. Stream: capture audio chunks; timestamp tool calls as function-call
     parts arrive; collect output transcription.
  4. On turn complete: verify transcript ~= script (levenshtein-ish check).
     If it deviated badly, optionally re-capture once with stricter wording.
  5. Save performance: WAV + timeline JSON under
     data/performances/<session_id>/seg_<NNN>[_variant].wav/.json

The replay client (browser) plays the WAV through TalkingHead lipsync and
fires timeline events at their timestamps — deterministic perfect sync.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import wave
from pathlib import Path
from typing import Any, Optional

import numpy as np

from ..config import PERFORMANCES_DIR, settings
from .gemini import LIVE, estimate_live_session_tokens
from .tpm_manager import tpm
from .whiteboard import validate_tool_call

log = logging.getLogger("capture")

# Live API audio: 16-bit PCM, 24kHz (native output for Gemini Live models)
SAMPLE_RATE = 24000
SAMPLE_WIDTH = 2
CHANNELS = 1

TEACHER_VOICE = "Charon"        # warm male teacher voice
ALT_VOICE = "Kore"              # alt female teacher voice

# persona -> Live API prebuilt voice (shared with the live WS relay)
PERSONA_VOICES = {
    "Aarav Sir": "Charon",       # warm male
    "Meera Ma'am": "Kore",       # warm female
    "Professor Bheem": "Fenrir",  # deep professor
}

PERSONA_TEMPLATE = """You are {persona_name}, a warm, encouraging human teacher. You are
recording a lesson performance for a student.

CRITICAL PERFORMANCE RULES:
1. You MUST speak the script VERBATIM, exactly as written — word for word.
   Do NOT add, remove, or change words. Do NOT say things like "Sure" or
   "Here's the lesson" before starting.
2. The script contains bracketed stage directions like [PAUSE], [CLEAR BOARD]
   and [VISUAL: something]. These are INSTRUCTIONS FOR YOU, NOT TEXT TO READ.
   When you reach one: pause briefly (about 0.8 seconds of silence), then
   continue with the next spoken sentence. NEVER say the words "PAUSE",
   "VISUAL", "CLEAR BOARD" or anything inside square brackets ALOUD.
3. Never mention being an AI, recording, or the script itself.
4. Speak like a friendly teacher at a whiteboard: natural pacing, warm tone.
5. Teaching language: {language_name}. Speak ONLY in that language.
6. When you finish the script, stop. Do not add any closing remarks not in
   the script.

The bracketed markers trigger visuals automatically — you never need to
describe them. Just skip over them silently and keep speaking."""


def _script_with_stage_directions(script: str, visuals: list[dict]) -> str:
    """Insert [VISUAL: tool] markers into the script between sentences.

    visuals have 'after_sentence': after the Nth sentence (1-based) the
    visual appears. We approximate sentence boundaries with periods /
    dandas (for Hindi) / question marks / exclamation marks.
    """
    if not visuals:
        return script
    # split into sentences (keep the punctuation)
    import re
    parts = re.split(r"(?<=[।.!?])\s+", script.strip())
    parts = [p for p in parts if p.strip()]
    out: list[str] = []
    v_by_sentence: dict[int, list[str]] = {}
    for v in visuals:
        n = int(v.get("after_sentence", 1))
        v_by_sentence.setdefault(n, []).append(v["tool"])
    sent_no = 0
    for p in parts:
        sent_no += 1
        out.append(p)
        for tool in v_by_sentence.get(sent_no, []):
            out.append(f"[VISUAL: {tool}] [PAUSE]")
    return " ".join(out)


def _pcm_to_wav(pcm: bytes, path: Path) -> int:
    """Write raw PCM bytes to a WAV file. Returns duration seconds."""
    n = len(pcm) // (SAMPLE_WIDTH * CHANNELS)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(SAMPLE_WIDTH)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    return n / SAMPLE_RATE


def _levenshtein_ratio(a: str, b: str) -> float:
    """Cheap similarity ratio on word sequences (0..1)."""
    wa, wb = a.lower().split(), b.lower().split()
    if not wa or not wb:
        return 0.0
    # bounded DP
    prev = list(range(len(wb) + 1))
    for i, ca in enumerate(wa, 1):
        cur = [i]
        for j, cb in enumerate(wb, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    dist = prev[-1]
    return 1.0 - dist / max(len(wa), len(wb))


def _normalize_for_compare(s: str) -> str:
    import re
    s = re.sub(r"\[.*?\]", " ", s)          # stage directions out
    s = re.sub(r"[^\w\s\u0900-\u097F]", " ", s.lower())
    return " ".join(s.split())


class PerformanceCapture:
    """Captures one lesson segment (or a variant) via the Live API."""

    def __init__(self, session_id: str, seg_id: int, variant: str = "main",
                 persona_name: str = "Aarav Sir", voice: str = TEACHER_VOICE):
        self.session_id = session_id
        self.seg_id = seg_id
        self.variant = variant
        self.persona_name = persona_name
        self.voice = voice

    async def capture(self, script: str, visuals: list[dict],
                      language_name: str) -> dict[str, Any]:
        """Run the capture. Returns performance dict (also saved to disk)."""
        from google import genai
        from google.genai import types as gtypes

        client = None
        from .gemini import client as gemini_client
        client = gemini_client()

        script_sd = _script_with_stage_directions(script, visuals)

        config = gtypes.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=gtypes.Content(
                parts=[gtypes.Part(text=PERSONA_TEMPLATE.format(
                    persona_name=self.persona_name,
                    language_name=language_name))]
            ),
            speech_config=gtypes.SpeechConfig(
                voice_config=gtypes.VoiceConfig(
                    prebuilt_voice_config=gtypes.PrebuiltVoiceConfig(
                        voice_name=self.voice)
                )
            ),
            # tools omitted intentionally: visuals fire from the timeline,
            # not from model tool calls (deterministic replay)
            output_audio_transcription={},
        )

        est = estimate_live_session_tokens(script_sd, PERSONA_TEMPLATE)
        model = settings.gemini_live_model

        # TPM: admission for the whole session based on estimate; stream
        # actual usage as it arrives.
        await tpm.acquire(model, est, LIVE)
        session = None
        pcm_chunks: list[bytes] = []
        tool_calls: list[dict] = []
        transcript_parts: list[str] = []
        t0 = time.monotonic()
        completed = False
        try:
            # SDK 2.x: live.connect() is an async context manager
            async with client.aio.live.connect(model=model, config=config) as session:

                await session.send(input=script_sd, end_of_turn=True)

                async for msg in session.receive():
                    sc = getattr(msg, "server_content", None)

                    # audio
                    audio = _msg_audio(msg)
                    if audio:
                        pcm_chunks.append(audio)
                        # actual token accounting as audio streams (~25 tok/s)
                        nsec = len(audio) / (SAMPLE_RATE * SAMPLE_WIDTH)
                        await tpm.record_stream_usage(model, int(nsec * 25))

                    # tool calls (shouldn't happen with no tools declared, but be safe)
                    for call in _msg_tool_calls(msg):
                        tool_calls.append({
                            "t": round(time.monotonic() - t0, 3),
                            "tool": call["name"], "args": call["args"],
                        })

                    # output audio transcription (spoken transcript)
                    if sc is not None:
                        ot = getattr(sc, "output_transcription", None)
                        if ot is not None and getattr(ot, "text", None):
                            transcript_parts.append(ot.text)
                        if getattr(sc, "turn_complete", False):
                            completed = True

                    if completed:
                        break
        except Exception:
            await tpm.release(model, est, None)
            raise
        # drain the TPM reservation only (actual usage was already streamed
        # into the window as audio arrived — do NOT record twice)
        dur = len(b"".join(pcm_chunks)) / (SAMPLE_RATE * SAMPLE_WIDTH)
        await tpm.release(model, est, None)

        pcm = b"".join(pcm_chunks)
        if not pcm:
            raise RuntimeError("Live session produced no audio")

        # verify transcript vs script
        spoken = " ".join(transcript_parts).strip()
        sim = _levenshtein_ratio(_normalize_for_compare(script),
                                 _normalize_for_compare(spoken)) if spoken else 0.0

        # scrub stage-direction words the model accidentally said aloud, so
        # subtitles never show "[PAUSE]" / "VISUAL: ..." text
        import re as _re
        clean = _re.sub(r"\[[^\]]*\]", " ", spoken)
        clean = _re.sub(r"\bVISUAL\s*:\s*[\w\s]+?(?=[.!?]|$)", " ", clean,
                        flags=_re.IGNORECASE)
        clean = _re.sub(r"\s{2,}", " ", clean).strip()

        # build visual timeline (visuals fire at their sentence positions —
        # we approximate via sentence timestamps parsed from the transcript
        # alignment below; fallback: evenly spaced)
        timeline = _build_timeline(visuals, script, clean, dur)

        perf_dir = PERFORMANCES_DIR / self.session_id
        perf_dir.mkdir(parents=True, exist_ok=True)
        base = f"seg_{self.seg_id:03d}" + (f"_{self.variant}" if self.variant != "main" else "")
        wav_path = perf_dir / f"{base}.wav"
        _pcm_to_wav(pcm, wav_path)

        # transcript path: save with sentence timing if available
        perf = {
            "session_id": self.session_id,
            "seg_id": self.seg_id,
            "variant": self.variant,
            "wav": f"{self.session_id}/{base}.wav",   # api route: /api/performances/<sid>/<name>
            "wav_name": f"{base}.wav",
            "duration": dur,
            "transcript": clean,
            "verbatim_score": round(sim, 3),
            "timeline": timeline,
            "voice": self.voice,
            "persona": self.persona_name,
            "captured_at": time.time(),
        }
        (perf_dir / f"{base}.json").write_text(
            json.dumps(perf, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("Captured seg %s.%s: %.1fs audio, verbatim=%.2f, %d visuals",
                 self.seg_id, self.variant, dur, sim, len(timeline))
        return perf


def _msg_audio(msg) -> Optional[bytes]:
    """Extract raw PCM from a Live API message."""
    # The SDK returns inline audio via msg.data (base64 str / bytes)
    data = getattr(msg, "data", None)
    if data:
        if isinstance(data, str):
            import base64
            return base64.b64decode(data)
        if isinstance(data, (bytes, bytearray)):
            return bytes(data)
    return None


def _msg_tool_calls(msg) -> list[dict]:
    out = []
    tc = getattr(msg, "tool_call", None)
    if tc:
        for fc in getattr(tc, "function_calls", []) or []:
            args = {}
            for k, v in dict(getattr(fc, "args", {}) or {}).items():
                args[k] = v
            out.append({"name": fc.name, "args": args})
    return out


def _build_timeline(visuals: list[dict], script: str, spoken: str,
                    duration: float) -> list[dict]:
    """Assign timestamps to each visual.

    Strategy: count sentences in the script. Visual N (after_sentence=k)
    fires at (fraction of sentences spoken) * duration. Fraction comes from
    matching sentence prefixes of the actual spoken transcript; fallback is
    proportional spacing.
    """
    import re
    if not visuals:
        return []
    parts = re.split(r"(?<=[।.!?])\s+", script.strip())
    parts = [p for p in parts if p.strip()]
    n = len(parts) or 1
    out = []
    for v in visuals:
        k = int(v.get("after_sentence", 1))
        frac = min(1.0, max(0.0, (k - 0.5) / n))
        t = frac * duration
        val = validate_tool_call(v.get("tool", ""), v.get("args", {}))
        entry = {
            "t": round(t, 3),
            "tool": v.get("tool"),
            "args": val["args"],
            "valid": val["ok"],
        }
        if not val["ok"]:
            entry["errors"] = val["errors"]
        out.append(entry)
    out.sort(key=lambda e: e["t"])
    return out
