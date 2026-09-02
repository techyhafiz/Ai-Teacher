"""SQLite database layer: learner profiles, sessions, event trace, mastery.

Schema mirrors the discussion:
    learners        - persistent learner profiles
    sessions        - teaching sessions (topic or upload mode)
    session_events  - full auditable event trace (plan/checkpoint/decision/...)
    concept_mastery - per-learner per-concept mastery
    quiz_results    - final assessment records
    profile_summary - compact LLM-readable profile for personalization
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from .config import DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS learners (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    language      TEXT NOT NULL DEFAULT 'en',
    level         TEXT NOT NULL DEFAULT 'beginner',
    created_at    REAL NOT NULL,
    last_active   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id            TEXT PRIMARY KEY,
    learner_id    TEXT NOT NULL REFERENCES learners(id),
    mode          TEXT NOT NULL,              -- 'topic' | 'upload'
    topic         TEXT NOT NULL,
    doc_id        TEXT,                       -- set when mode='upload'
    language      TEXT NOT NULL,
    level         TEXT NOT NULL,
    time_budget   TEXT NOT NULL,              -- '5min' | '20min' | '60min' | '7days'
    status        TEXT NOT NULL DEFAULT 'planned',  -- planned|capturing|teaching|assessing|done
    plan          TEXT,                        -- full plan JSON
    report        TEXT,                        -- final report JSON
    created_at    REAL NOT NULL,
    finished_at   REAL
);

CREATE TABLE IF NOT EXISTS session_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT NOT NULL REFERENCES sessions(id),
    ts            REAL NOT NULL,
    type          TEXT NOT NULL,              -- plan|checkpoint_eval|decision|adapt|language_switch|quiz|report|...
    payload       TEXT NOT NULL               -- JSON
);

CREATE TABLE IF NOT EXISTS concept_mastery (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id    TEXT NOT NULL REFERENCES learners(id),
    concept       TEXT NOT NULL,
    mastery       REAL NOT NULL DEFAULT 0.0,  -- 0..1
    attempts      INTEGER NOT NULL DEFAULT 0,
    first_seen    REAL NOT NULL,
    last_seen     REAL NOT NULL,
    UNIQUE (learner_id, concept)
);

CREATE TABLE IF NOT EXISTS quiz_results (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT NOT NULL REFERENCES sessions(id),
    ts            REAL NOT NULL,
    question      TEXT NOT NULL,
    expected      TEXT,
    given         TEXT,
    correct       INTEGER NOT NULL,           -- 0/1
    misconception TEXT,                       -- tag or NULL
    points        REAL NOT NULL DEFAULT 1.0,
    scored        REAL NOT NULL DEFAULT 0.0
);

CREATE INDEX IF NOT EXISTS idx_events_session ON session_events(session_id);
CREATE INDEX IF NOT EXISTS idx_mastery_learner ON concept_mastery(learner_id);
"""


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as c:
        c.executescript(_SCHEMA)


# ---------------------------------------------------------------------------
# Learners
# ---------------------------------------------------------------------------

def upsert_learner(name: str, language: str = "en", level: str = "beginner",
                   learner_id: Optional[str] = None) -> dict[str, Any]:
    now = time.time()
    lid = learner_id or uuid.uuid4().hex[:12]
    with _conn() as c:
        c.execute(
            "INSERT INTO learners (id, name, language, level, created_at, last_active) "
            "VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
            "name=excluded.name, language=excluded.language, level=excluded.level, "
            "last_active=excluded.last_active",
            (lid, name, language, level, now, now),
        )
    return get_learner(lid)


def get_learner(learner_id: str) -> dict[str, Any]:
    with _conn() as c:
        row = c.execute("SELECT * FROM learners WHERE id=?", (learner_id,)).fetchone()
        return dict(row) if row else None


def list_learners() -> list[dict[str, Any]]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM learners ORDER BY last_active DESC").fetchall()
        return [dict(r) for r in rows]


def learner_profile_summary(learner_id: str) -> str:
    """Compact, LLM-readable learner profile (personalization context)."""
    with _conn() as c:
        mastery = c.execute(
            "SELECT concept, mastery, attempts, last_seen FROM concept_mastery "
            "WHERE learner_id=? ORDER BY last_seen DESC LIMIT 40",
            (learner_id,),
        ).fetchall()
        sessions = c.execute(
            "SELECT topic, level, time_budget, created_at, status FROM sessions "
            "WHERE learner_id=? ORDER BY created_at DESC LIMIT 10",
            (learner_id,),
        ).fetchall()
    if not mastery and not sessions:
        return "New learner - no history yet."
    lines = ["Learner history (most recent first):"]
    for s in sessions:
        lines.append(f"- Session on '{s['topic']}' ({s['level']}, {s['time_budget']}) status={s['status']}")
    for m in mastery:
        band = "strong" if m["mastery"] >= 0.75 else ("developing" if m["mastery"] >= 0.4 else "weak")
        lines.append(f"- Concept '{m['concept']}': {band} (mastery={m['mastery']:.2f}, attempts={m['attempts']})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def create_session(learner_id: str, mode: str, topic: str, language: str,
                   level: str, time_budget: str, doc_id: Optional[str] = None) -> str:
    sid = uuid.uuid4().hex[:14]
    with _conn() as c:
        c.execute(
            "INSERT INTO sessions (id, learner_id, mode, topic, doc_id, language, level, "
            "time_budget, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (sid, learner_id, mode, topic, doc_id, language, level, time_budget,
             "planned", time.time()),
        )
    return sid


def get_session(sid: str) -> Optional[dict[str, Any]]:
    with _conn() as c:
        row = c.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
        return dict(row) if row else None


def set_plan(sid: str, plan: dict) -> None:
    with _conn() as c:
        c.execute("UPDATE sessions SET plan=?, status='planned' WHERE id=?",
                  (json.dumps(plan, ensure_ascii=False), sid))


def set_status(sid: str, status: str) -> None:
    with _conn() as c:
        c.execute("UPDATE sessions SET status=? WHERE id=?", (status, sid))


def set_report(sid: str, report: dict) -> None:
    with _conn() as c:
        c.execute("UPDATE sessions SET report=?, status='done', finished_at=? WHERE id=?",
                  (json.dumps(report, ensure_ascii=False), time.time(), sid))


def list_sessions(learner_id: Optional[str] = None) -> list[dict[str, Any]]:
    with _conn() as c:
        if learner_id:
            rows = c.execute("SELECT * FROM sessions WHERE learner_id=? ORDER BY created_at DESC",
                             (learner_id,)).fetchall()
        else:
            rows = c.execute("SELECT * FROM sessions ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Event trace (the auditable "teacher's reasoning")
# ---------------------------------------------------------------------------

def log_event(session_id: str, type_: str, payload: dict) -> None:
    with _conn() as c:
        c.execute("INSERT INTO session_events (session_id, ts, type, payload) VALUES (?,?,?,?)",
                  (session_id, time.time(), type_, json.dumps(payload, ensure_ascii=False)))


def get_events(session_id: str) -> list[dict[str, Any]]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM session_events WHERE session_id=? ORDER BY id",
                         (session_id,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["payload"] = json.loads(d["payload"])
            except Exception:
                pass
            out.append(d)
        return out


# ---------------------------------------------------------------------------
# Mastery tracking
# ---------------------------------------------------------------------------

def update_mastery(learner_id: str, concept: str, score: float) -> None:
    """Update mastery with an exponential moving average (score in 0..1)."""
    now = time.time()
    with _conn() as c:
        row = c.execute("SELECT mastery, attempts FROM concept_mastery "
                        "WHERE learner_id=? AND concept=?", (learner_id, concept)).fetchone()
        if row:
            m = row["mastery"]
            a = row["attempts"]
            new_m = m + 0.4 * (score - m)     # EMA alpha=0.4
            c.execute("UPDATE concept_mastery SET mastery=?, attempts=?, last_seen=? "
                      "WHERE learner_id=? AND concept=?",
                      (new_m, a + 1, now, learner_id, concept))
        else:
            c.execute("INSERT INTO concept_mastery (learner_id, concept, mastery, attempts, "
                      "first_seen, last_seen) VALUES (?,?,?,?,?,?)",
                      (learner_id, concept, 0.4 + 0.6 * score, 1, now, now))


def get_mastery(learner_id: str) -> list[dict[str, Any]]:
    with _conn() as c:
        rows = c.execute("SELECT concept, mastery, attempts, first_seen, last_seen "
                         "FROM concept_mastery WHERE learner_id=? ORDER BY last_seen DESC",
                         (learner_id,)).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Quiz results
# ---------------------------------------------------------------------------

def add_quiz_result(session_id: str, question: str, expected: Optional[str],
                    given: Optional[str], correct: bool,
                    misconception: Optional[str], points: float, scored: float) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO quiz_results (session_id, ts, question, expected, given, correct, "
            "misconception, points, scored) VALUES (?,?,?,?,?,?,?,?,?)",
            (session_id, time.time(), question, expected, given, int(correct),
             misconception, points, scored),
        )


def get_quiz_results(session_id: str) -> list[dict[str, Any]]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM quiz_results WHERE session_id=? ORDER BY id",
                         (session_id,)).fetchall()
        return [dict(r) for r in rows]


def session_stats(session_id: str) -> dict[str, Any]:
    with _conn() as c:
        row = c.execute(
            "SELECT COUNT(*) AS n, SUM(correct) AS ncorrect, SUM(points) AS points, "
            "SUM(scored) AS scored FROM quiz_results WHERE session_id=?",
            (session_id,),
        ).fetchone()
    n = row["n"] or 0
    return {
        "questions": n,
        "correct": row["ncorrect"] or 0,
        "points": row["points"] or 0.0,
        "scored": row["scored"] or 0.0,
        "pct": (100.0 * (row["scored"] or 0.0) / row["points"]) if row["points"] else None,
    }
