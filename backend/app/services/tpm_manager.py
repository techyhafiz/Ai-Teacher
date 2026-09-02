"""Token-Per-Minute (TPM) manager.

A single chokepoint between ALL components and the Gemini API. Every Gemini
call is admitted through here so we never blow past rolling 60-second token
windows, with priority lanes so live student-facing moments are never starved.

Design:
  - Per-model rolling 60s windows: deque of (timestamp, tokens)
  - Admission control BEFORE each call: estimate token need, reserve it;
    if projected window > limit * headroom, the call QUEUES (async) until
    the window drains (queue-and-wait, never fail)
  - Priority lanes: LIVE (0) > CAPTURE (1) > BATCH (2)  — lower first
  - After each call completes, the reservation is replaced by ACTUAL usage
    taken from the response's usage_metadata (includes audio/image tokens)
  - 429 RESOURCE_EXHAUSTED -> exponential backoff + re-admit, never crash
  - /api/metrics exposes live usage per model
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from ..config import settings

log = logging.getLogger("tpm")

# Priority lanes
LIVE = 0      # live full-duplex checkpoints with a waiting student
CAPTURE = 1   # performance capture (lesson audio generation)
BATCH = 2     # planning, OCR, embeddings, reports, etc.

_LANE_NAMES = {LIVE: "live", CAPTURE: "capture", BATCH: "batch"}


@dataclass
class _Waiter:
    prio: int
    seq: int
    future: "asyncio.Future[None]"
    tokens: int


@dataclass
class ModelWindow:
    """Rolling 60s token window for one model."""
    name: str
    limit: int
    headroom: float
    used: deque[tuple[float, int]] = field(default_factory=deque)
    reserved: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    waiters: list[_Waiter] = field(default_factory=list)
    _seq: int = 0
    # stats
    total_calls: int = 0
    total_tokens: int = 0
    throttled_count: int = 0
    last_429: Optional[float] = None

    def _prune(self) -> None:
        cutoff = time.monotonic() - 60.0
        while self.used and self.used[0][0] <= cutoff:
            self.used.popleft()

    def window_used(self) -> int:
        self._prune()
        return sum(t for _, t in self.used)

    def projected(self, extra: int = 0) -> int:
        return self.window_used() + self.reserved + extra

    def capacity(self) -> int:
        return int(self.limit * self.headroom)


class TPMManager:
    """Admission control + accounting for all Gemini calls.

    Correctness properties:
      - Queue-and-wait: calls NEVER fail on quota; they wait.
      - Priority: LIVE > CAPTURE > BATCH. A call is admitted only when no
        waiter of equal-or-higher priority is queued (strict lanes, FIFO
        within a lane).
      - Liveness: waiters re-check admission on a short timer (recheck_s),
        so a window that drains purely by TIME (entries expiring) also
        unblocks queued calls — no reliance on other calls finishing.
      - Accounting: admission reserves an ESTIMATE; actual usage from the
        API response replaces it. Streaming calls record actuals directly.
    """

    def __init__(self, recheck_s: float = 2.0) -> None:
        self._models: dict[str, ModelWindow] = {}
        self._concurrency_sem: dict[str, asyncio.Semaphore] = {}
        self._global_seq: int = 0
        self._shutdown = False
        self._recheck_s = max(0.05, recheck_s)

    # -- setup ---------------------------------------------------------------

    def register_model(self, key: str, limit: int, max_concurrency: int = 4,
                       headroom: Optional[float] = None) -> ModelWindow:
        w = ModelWindow(key, limit, headroom or settings.tpm_headroom)
        self._models[key] = w
        self._concurrency_sem[key] = asyncio.Semaphore(max_concurrency)
        return w

    def _win(self, key: str) -> ModelWindow:
        if key not in self._models:
            # Lazy default registration (should be explicit, but be safe)
            log.warning("TPM: model '%s' not registered; using default limit", key)
            self.register_model(key, limit=1_000_000)
        return self._models[key]

    # -- admission -----------------------------------------------------------

    async def acquire(self, key: str, est_tokens: int, priority: int = BATCH) -> None:
        """Wait until `est_tokens` fit in the model's window. Queue-and-wait.

        Admitted only when (a) the window has capacity and (b) no
        equal-or-higher priority waiter is ahead of us (strict lanes).
        """
        w = self._win(key)
        loop = asyncio.get_running_loop()
        seq = None
        fut = None
        while True:
            if self._shutdown:
                raise RuntimeError("TPM manager is shut down; rejecting new calls")
            async with w.lock:
                w._prune()
                # strict priority: do not jump ahead of queued higher lanes
                has_higher = any(waiter.prio < priority for waiter in w.waiters)
                if not has_higher and w.projected(est_tokens) <= w.capacity():
                    w.reserved += est_tokens
                    w.total_calls += 1
                    if seq is not None:
                        # dequeue ourselves (wake path may have done it)
                        for i, waiter in enumerate(w.waiters):
                            if waiter.seq == seq:
                                w.waiters.pop(i)
                                break
                    return
                # register as a waiter ATOMICALLY with the failed check, so a
                # lower-priority newcomer can never slip in ahead of us
                if seq is None:
                    self._global_seq += 1
                    seq = self._global_seq
                    fut = loop.create_future()
                    w.waiters.append(_Waiter(priority, seq, fut, est_tokens))
                    w.throttled_count += 1
                    log.info("TPM[%s]: queuing %d tokens (prio=%s, window=%d/%d cap)",
                             key, est_tokens, _LANE_NAMES.get(priority, priority),
                             w.window_used(), w.capacity())

            # Wake EITHER when another call releases capacity OR on the
            # recheck timer (so pure time-based window expiry unblocks too).
            done, pending = await asyncio.wait(
                {asyncio.ensure_future(fut)},
                timeout=self._recheck_s,
            )
            for p in pending:
                p.cancel()
            # loop and re-check admission

    def _wake_waiters_locked(self, w: ModelWindow) -> None:
        """Wake waiters in priority order while capacity allows.

        Caller MUST hold w.lock. Does NOT add reservations — the woken
        waiter adds its own reservation when it re-checks in acquire().
        """
        w._prune()
        w.waiters.sort(key=lambda x: (x.prio, x.seq))
        for waiter in w.waiters:
            if w.projected(waiter.tokens) > w.capacity():
                break
            if not waiter.future.done():
                waiter.future.set_result(None)

    async def _wake_waiters(self, w: ModelWindow) -> None:
        """Convenience wrapper for callers NOT holding the lock."""
        async with w.lock:
            self._wake_waiters_locked(w)

    def _drain_reservation(self, w: ModelWindow, tokens: int) -> None:
        if w.reserved >= tokens:
            w.reserved -= tokens
        else:
            w.reserved = 0

    async def release(self, key: str, est_tokens: int, actual_tokens: Optional[int]) -> None:
        """Replace reservation with actual usage, record, and wake waiters."""
        w = self._win(key)
        async with w.lock:
            self._drain_reservation(w, est_tokens)
            if actual_tokens is not None:
                if actual_tokens > 0:
                    w.used.append((time.monotonic(), actual_tokens))
                    w.total_tokens += actual_tokens
            self._wake_waiters_locked(w)

    async def record_stream_usage(self, key: str, tokens: int) -> None:
        """Record incremental usage for streaming calls (Live sessions) without a reservation."""
        w = self._win(key)
        async with w.lock:
            if tokens > 0:
                w.used.append((time.monotonic(), tokens))
                w.total_tokens += tokens
            self._wake_waiters_locked(w)

    # -- guarded call helper ---------------------------------------------------

    async def call(self, key: str, est_tokens: int, fn: Callable[[], Awaitable[Any]],
                   actual_tokens_fn: Optional[Callable[[Any], Optional[int]]] = None,
                   priority: int = BATCH, max_retries: int = 4) -> Any:
        """Run an async Gemini call under TPM admission control.

        fn: zero-arg coroutine returning the SDK result.
        actual_tokens_fn: extracts usage.token_count-like int from result.
        On 429 RESOURCE_EXHAUSTED: exponential backoff then re-admit.
        """
        w = self._win(key)
        attempt = 0
        while True:
            await self.acquire(key, est_tokens, priority)
            sem = self._concurrency_sem.get(key)
            try:
                if sem:
                    async with sem:
                        result = await fn()
                else:
                    result = await fn()
                actual = actual_tokens_fn(result) if actual_tokens_fn else None
                await self.release(key, est_tokens, actual)
                return result
            except Exception as e:                                  # noqa: BLE001
                await self._safe_release(key, est_tokens)
                if _is_429(e) and attempt < max_retries:
                    attempt += 1
                    w.last_429 = time.time()
                    delay = min(2 ** attempt, 45) + (attempt * 0.5)
                    log.warning("TPM[%s]: 429 hit, backoff %.1fs (attempt %d)",
                                key, delay, attempt)
                    await asyncio.sleep(delay)
                    continue
                raise

    async def _safe_release(self, key: str, est_tokens: int) -> None:
        try:
            await self.release(key, est_tokens, None)
        except Exception:                                           # noqa: BLE001
            pass

    # -- introspection ---------------------------------------------------------

    def metrics(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, w in self._models.items():
            used = w.window_used()
            out[key] = {
                "limit": w.limit,
                "headroom_capacity": w.capacity(),
                "used_last_60s": used,
                "reserved": w.reserved,
                "queued": len(w.waiters),
                "total_calls": w.total_calls,
                "total_tokens": w.total_tokens,
                "throttled_count": w.throttled_count,
                "last_429": w.last_429,
            }
        return out

    def shutdown(self) -> None:
        """Unblock all queued waiters so the event loop can drain cleanly."""
        self._shutdown = True
        for w in self._models.values():
            for waiter in w.waiters:
                if not waiter.future.done():
                    waiter.future.set_result(None)
            w.waiters.clear()


def _is_429(e: BaseException) -> bool:
    text = str(e).lower()
    return ("429" in text or "resource_exhausted" in text
            or "resourceexhausted" in text or "quota" in text)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

tpm = TPMManager()

_registered_defaults = False


def register_default_models() -> None:
    """Register the project's models with configured limits."""
    global _registered_defaults
    if _registered_defaults:
        return
    tpm.register_model(settings.gemini_text_model, settings.tpm_text_model,
                       max_concurrency=6)
    tpm.register_model(settings.gemini_live_model, settings.tpm_live_model,
                       max_concurrency=max(1, settings.max_parallel_captures + 1))
    tpm.register_model(settings.gemini_embedding_model, settings.tpm_embedding_model,
                       max_concurrency=6)
    _registered_defaults = True
