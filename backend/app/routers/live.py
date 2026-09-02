"""Live API WebSocket relay.

The browser NEVER holds the Gemini API key. It opens a WS to
/api/ws/live/{session_id}; this backend opens the matching Gemini Live session
and pipes audio/commands both ways:

  browser -> backend -> Gemini : student speech (base64 PCM16 24k),
                                 text follow-ups, tool results
  backend -> browser           : teacher speech audio (base64 PCM chunks),
                                 teacher tool calls (whiteboard drawing),
                                 interruptions, turn-complete,
                                 checkpoint evaluation results

The live session gets a focused context: lesson topic, current segment,
the checkpoint question + expected answer, recent lesson events, and the
TEACH brain tools:
  evaluate_student  -> structured verdict that ends the checkpoint
  switch_language   -> student asked for another language mid-lesson
  ask_whiteboard    -> draw something live during the conversation
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from google.genai import types as gtypes

from .. import db
from ..config import settings
from ..services.capture import PERSONA_VOICES
from ..services.gemini import client as gemini_client
from ..services.tpm_manager import LIVE, tpm
from ..services.whiteboard import tools_for_live_api

log = logging.getLogger("ws.live")
router = APIRouter()

LANG_NAMES = {"en": "English", "hi": "Hindi", "hinglish": "Hinglish"}

CHECKPOINT_SYSTEM = """You are {persona}, a warm, encouraging teacher in a live voice
conversation with a student in the middle of a lesson. You are at a CHECKPOINT:
the student was just asked a question and is answering by voice right now.

BEHAVIOR:
1. Listen to the student's answer fully. React naturally like a human teacher:
   small acknowledgements ("hmm", "okay"), warmth, encouragement.
2. Then call evaluate_student with your structured verdict. After the call,
   give brief encouraging feedback based on the verdict and continue naturally
   toward wrapping up the checkpoint (1-3 sentences max). Do NOT re-teach the
   whole concept here unless the verdict says re_explain — in that case give
   a short targeted correction.
3. If the student asks to change teaching language, call switch_language,
   then continue speaking the new language.
4. You may call ask_whiteboard to draw something to help the conversation
   (a quick diagram, equation, or note) — keep it simple.
5. Never say you are an AI. Never mention tool calls.
6. Teaching language: {language_name}. If the student speaks another language,
   gently continue in {language_name} unless switch_language was called.
7. Keep responses SHORT — this is a conversation turn, not a lecture.

SESSION CONTEXT (for your awareness):
Lesson topic: {topic}
Current concept: {concept}
Checkpoint question: "{question}"
Expected answer: "{expected}"
Student level: {level}
Recent lesson context: {lesson_context}"""


def _brain_tools() -> list[dict[str, Any]]:
    """Function-calling tools for the live teacher brain."""
    return [
        {"functionDeclarations": [
            {
                "name": "evaluate_student",
                "description": "Submit your structured evaluation of the student's "
                               "answer. Call this exactly once per checkpoint, after "
                               "the student has answered.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "verdict": {"type": "string",
                                    "enum": ["correct", "partially_correct", "incorrect"]},
                        "score": {"type": "number",
                                  "description": "0.0-1.0"},
                        "misconception": {"type": "string",
                                          "description": "short tag or empty string"},
                        "reasoning": {"type": "string",
                                      "description": "one sentence: why this verdict"},
                    },
                    "required": ["verdict", "score", "reasoning"],
                },
            },
            {
                "name": "switch_language",
                "description": "The student requested teaching in another language.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "language": {"type": "string",
                                     "enum": ["en", "hi", "hinglish"],
                                     "description": "New teaching language code."},
                    },
                    "required": ["language"],
                },
            },
        ] + [
            {
                "name": "ask_whiteboard",
                "description": "Draw on the whiteboard during the conversation to "
                               "help explain (keep it simple).",
                "parameters": t["parameters"],
            }
            for t in [
                # only the lightweight tools for live conversation
                d for d in _live_tool_subset()
            ]
        ]}
    ]


def _live_tool_subset() -> list[dict]:
    from ..services.whiteboard import TOOL_DEFINITIONS
    allow = {"write_text", "draw_equation", "plot_graph", "draw_diagram"}
    return [t for t in TOOL_DEFINITIONS if t["name"] in allow]


@router.websocket("/ws/live/{session_id}")
async def live_relay(ws: WebSocket, session_id: str):
    """Full-duplex relay: browser <-> backend <-> Gemini Live."""
    await ws.accept()
    session = db.get_session(session_id)
    if not session:
        await ws.send_text(json.dumps({"type": "error", "message": "Unknown session"}))
        await ws.close()
        return

    # ---- messages from the browser configure the session --------------------
    init: dict[str, Any] = {}
    try:
        raw = await ws.receive_text()
        init = json.loads(raw)
    except Exception:
        pass

    persona = init.get("persona", "Aarav Sir")
    voice = PERSONA_VOICES.get(persona, "Charon")
    language = init.get("language", session.get("language", "en"))
    concept = init.get("concept", "")
    question = init.get("question", "")
    expected = init.get("expected_answer", "")
    seg_id = init.get("seg_id", -1)
    mode = init.get("mode", "checkpoint")      # checkpoint | raise_hand | quiz
    learner_id = session["learner_id"]

    events = db.get_events(session_id)
    recent = [e["payload"] for e in events[-6:]]
    lesson_context = json.dumps(recent, ensure_ascii=False)[:2500]

    system = CHECKPOINT_SYSTEM.format(
        persona=persona,
        language_name=LANG_NAMES.get(language, "English"),
        topic=session["topic"],
        concept=concept,
        question=question,
        expected=expected,
        level=session["level"],
        lesson_context=lesson_context,
    )

    live_cm = None
    model = settings.gemini_live_model
    est = 4000  # per-turn reservation; actuals streamed via record_stream_usage
    try:
        client = gemini_client()
        config = gtypes.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=gtypes.Content(parts=[
                gtypes.Part(text=system)]),
            speech_config=gtypes.SpeechConfig(
                voice_config=gtypes.VoiceConfig(
                    prebuilt_voice_config=gtypes.PrebuiltVoiceConfig(
                        voice_name=voice))),
            tools=_brain_tools(),
            output_audio_transcription={},
        )
        await tpm.acquire(model, est, LIVE)
        # SDK 2.x: connect() is an async context manager
        live_cm = client.aio.live.connect(model=model, config=config)
        live = await live_cm.__aenter__()
    except Exception as e:                                  # noqa: BLE001
        await tpm.release(model, est, None)
        log.error("Live connect failed: %s", e)
        try:
            await ws.send_text(json.dumps({"type": "error",
                                           "message": f"Live connect failed: {e}"}))
            await ws.close()
        except Exception:
            pass
        return

    db.log_event(session_id, "live_open", {
        "seg_id": seg_id, "mode": mode, "concept": concept, "persona": persona,
    })

    async def pump_gemini_to_browser():
        """Forward Gemini messages -> browser WS."""
        try:
            async for msg in live.receive():
                # teacher audio -> browser (msg.data = concatenated PCM bytes)
                data = getattr(msg, "data", None)
                if data:
                    b = base64.b64encode(data).decode()
                    audio_counter[0] += len(data)
                    await ws.send_text(json.dumps({"type": "audio", "data": b}))

                sc = getattr(msg, "server_content", None)
                if sc is not None:
                    # input transcription (what the student said)
                    it = getattr(sc, "input_transcription", None)
                    if it and getattr(it, "text", None):
                        await ws.send_text(json.dumps({"type": "input_transcript",
                                                        "text": it.text}))
                    # output transcription (what the teacher said)
                    ot = getattr(sc, "output_transcription", None)
                    if ot and getattr(ot, "text", None):
                        await ws.send_text(json.dumps({"type": "transcript",
                                                        "text": ot.text}))
                    if getattr(sc, "interrupted", False):
                        await ws.send_text(json.dumps({"type": "interrupted"}))
                    if getattr(sc, "turn_complete", False):
                        await ws.send_text(json.dumps({"type": "turn_complete"}))

                # tool calls -> browser (evaluate_student, whiteboard, language)
                tc = getattr(msg, "tool_call", None)
                if tc:
                    for fc in getattr(tc, "function_calls", None) or []:
                        await ws.send_text(json.dumps({
                            "type": "tool_call",
                            "name": fc.name,
                            "args": dict(fc.args or {}),
                            "id": fc.id,
                        }))
                        # acknowledge the tool call so speech can continue
                        try:
                            await live.send_tool_response(function_responses=[{
                                "id": fc.id,
                                "name": fc.name,
                                "response": {"status": "acknowledged"},
                            }])
                        except Exception:                       # noqa: BLE001
                            pass
        except Exception as e:                              # noqa: BLE001
            log.error("pump_gemini_to_browser: %s", e)
            try:
                await ws.send_text(json.dumps({"type": "error",
                                               "message": str(e)}))
            except Exception:
                pass

    pump_task = None

    audio_counter = [0]

    async def usage_ticker():
        """Record audio tokens into the TPM window as they stream."""
        try:
            while True:
                await asyncio.sleep(2.0)
                if audio_counter[0] > 0:
                    nsec = audio_counter[0] / (24000 * 2)
                    await tpm.record_stream_usage(model, int(nsec * 25))
                    audio_counter[0] = 0
        except asyncio.CancelledError:
            pass

    try:
        pump_task = asyncio.create_task(pump_gemini_to_browser())
        ticker_task = asyncio.create_task(usage_ticker())

        while True:
            raw = await ws.receive_text()
            try:
                msg_in = json.loads(raw)
            except Exception:
                continue

            mtype = msg_in.get("type")
            if mtype == "student_audio":
                # browser -> Gemini: PCM16 24k mono, base64
                pcm = base64.b64decode(msg_in["data"])
                audio_counter[0] += len(pcm)
                await live.send_realtime_input(
                    audio=gtypes.Blob(data=pcm, mime_type="audio/pcm;rate=24000"))
            elif mtype == "student_audio_end":
                await live.send_realtime_input(audio_stream_end=True)
            elif mtype == "student_text":
                text = (msg_in.get("text") or "").strip()
                if text:
                    await live.send(input=text, end_of_turn=True)
            elif mtype == "end":
                break
    except WebSocketDisconnect:
        pass
    except Exception as e:                                  # noqa: BLE001
        log.error("live_relay error: %s", e)
    finally:
        for t in (pump_task, ticker_task):
            if t:
                t.cancel()
        try:
            if live_cm is not None:
                await live_cm.__aexit__(None, None, None)
        except Exception:
            pass
        await tpm.release(model, est, None)
        db.log_event(session_id, "live_close", {"seg_id": seg_id, "mode": mode})
        try:
            await ws.close()
        except Exception:
            pass
