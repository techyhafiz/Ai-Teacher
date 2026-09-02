"""TPM manager stress test: rolling windows, admission, priorities (asyncio)."""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.tpm_manager import TPMManager, LIVE, CAPTURE, BATCH  # noqa: E402


async def main():
    tpm = TPMManager(recheck_s=0.15)
    # tiny window so we can observe throttling quickly
    tpm.register_model("test", limit=1000, max_concurrency=3, headroom=1.0)

    # 1. basic admission + accounting
    t1 = time.monotonic()
    await tpm.acquire("test", 400, BATCH)
    tpm_recorded = time.monotonic()
    await tpm.release("test", 400, 450)   # actual > est
    print("acquire 400 -> instant:", round(tpm_recorded - t1, 3), "s")
    w = tpm._win("test")
    assert w.window_used() == 450, w.window_used()

    # 2. should queue when window full (est 600 + used 450 > 1000)
    t2 = time.monotonic()
    task = asyncio.create_task(tpm.acquire("test", 600, BATCH))
    await asyncio.sleep(0.2)
    assert not task.done(), "acquire should be queued"
    # simulate window drain: replace usage with expired entries
    w.used.clear()
    w.used.append((time.monotonic() - 61.0, 450))
    w._prune()
    await asyncio.sleep(0.3)
    assert task.done(), "acquire should proceed after window drains"
    await tpm.release("test", 600, 500)
    print("queued admission works; waited", round(time.monotonic() - t2, 2), "s")

    # 3. priority: LIVE should be admitted ahead of queued BATCH
    tpm2 = TPMManager(recheck_s=0.15)
    tpm2.register_model("prio", limit=1000, max_concurrency=5, headroom=1.0)
    await tpm2.acquire("prio", 900, BATCH)
    await tpm2.release("prio", 900, 950)
    # now window full: start a BATCH waiter then a LIVE waiter
    batch_task = asyncio.create_task(tpm2.acquire("prio", 950, BATCH))
    await asyncio.sleep(0.1)
    live_task = asyncio.create_task(tpm2.acquire("prio", 100, LIVE))
    await asyncio.sleep(0.1)
    # drain the window
    w2 = tpm2._win("prio")
    w2.used.clear()
    w2.used.append((time.monotonic() - 61.0, 950))
    w2._prune()
    await asyncio.sleep(0.4)
    assert live_task.done(), "LIVE should be admitted first"
    assert not batch_task.done(), "BATCH should still wait (950+100 > 1000)"
    print("priority lanes: LIVE admitted before BATCH")

    # 4. guarded call helper with actual usage extraction
    calls = []

    async def fake_call():
        calls.append(1)
        return {"usage_metadata": {"total_token_count": 77}}

    res = await tpm2.call("prio", 50, fake_call,
                          actual_tokens_fn=lambda r: r["usage_metadata"]["total_token_count"],
                          priority=LIVE)
    assert res["usage_metadata"]["total_token_count"] == 77
    assert calls == [1]
    used = tpm2._win("prio").window_used()
    assert used == 77, f"actual usage should be recorded: {used}"  # est 50 drained
    print("guarded call with actual usage: OK (window:", used, "tokens)")

    # 5. metrics shape
    m = tpm2.metrics()
    assert "prio" in m and m["prio"]["total_calls"] >= 1
    print("metrics:", m["prio"])

    print("\nTPM MANAGER: ALL TESTS PASSED")


asyncio.run(main())
