"""Hindi multilingual capture test: plan + capture in Hindi."""
import asyncio
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db                                       # noqa: E402
from app.services import planner                        # noqa: E402
from app.services.capture import PerformanceCapture     # noqa: E402
from app.config import PERFORMANCES_DIR                 # noqa: E402

TOPIC = "न्यूटन का पहला नियम कक्षा 8 के लिए"


async def main():
    db.init_db()
    lid = db.upsert_learner("Hindi Test Learner", "hi", "beginner")["id"]
    sid = db.create_session(lid, "topic", TOPIC, "hi", "beginner", "5min")
    plan = await planner.plan_lesson(
        session_id=sid, learner_id=lid, mode="topic", topic_request=TOPIC,
        language="hi", level="beginner", time_budget="5min",
        persona="Meera Ma'am")
    seg = plan["segments"][0]
    print("lesson:", plan["lesson_title"])
    print("script[0] (hi):", seg["script"]["main"][:160])

    # capture in Hindi with Meera Ma'am voice (Kore)
    cap = PerformanceCapture(sid, 0, "main", persona_name="Meera Ma'am",
                             voice="Kore")
    perf = await cap.capture(seg["script"]["main"], seg.get("visuals", []),
                             language_name="Hindi")
    print(f"captured: {perf['duration']}s verbatim={perf['verbatim_score']:.3f}")
    print("transcript:", perf["transcript"][:160])
    wav = PERFORMANCES_DIR / sid / perf["wav_name"]
    assert wav.exists() and wav.stat().st_size > 10000
    assert perf["verbatim_score"] > 0.7, "hindi verbatim too low"
    print("HINDI MULTILINGUAL CAPTURE: PASSED")
    print("session:", sid)


asyncio.run(main())
