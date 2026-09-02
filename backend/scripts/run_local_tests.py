"""Run all local (no-API-key) tests: parser, RAG, whiteboard, TPM, db.

Usage:  python scripts/run_local_tests.py
"""
import asyncio
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS = ["test_parser.py", "test_rag_local.py", "test_whiteboard.py",
         "test_tpm.py"]

# db test inline (fast)
DB_TEST = """
import sys; sys.path.insert(0, r'{root}')
from app import db
db.init_db()
lid = db.upsert_learner('Local Test Learner', 'en', 'beginner')['id']
sid = db.create_session(lid, 'topic', "Ohm's Law", 'en', 'beginner', '20min')
db.set_plan(sid, {{'lesson_title': 'T'}})
db.log_event(sid, 'live_open', {{'seg_id': 0}})
db.update_mastery(lid, 'ohms_law', 0.4)
db.update_mastery(lid, 'ohms_law', 0.9)
db.add_quiz_result(sid, 'V=IR check', 'V=IR', 'V=IR', True, None, 1.0, 1.0)
db.set_report(sid, {{'score_pct': 88}})
stats = db.session_stats(sid)
assert stats['questions'] == 1 and stats['correct'] == 1, stats
assert stats['pct'] == 100.0, stats
prof = db.learner_profile_summary(lid)
assert "Ohm's Law" in prof or "Session" in prof, prof
print('DB: ALL PASSED')
print(prof)
"""

root = HERE.parent
code = DB_TEST.format(root=str(root).replace("\\", "\\\\"))
r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                   cwd=str(root))
print(r.stdout.strip())
if r.returncode != 0:
    print(r.stderr)
    sys.exit(1)

failures = 0
for t in TESTS:
    print(f"\n===== {t} =====")
    r = subprocess.run([sys.executable, str(HERE / t)],
                       capture_output=True, text=True, cwd=str(root))
    print(r.stdout.strip())
    if r.returncode != 0:
        print(r.stderr[-1500:])
        failures += 1

print("\n" + "=" * 50)
print("ALL LOCAL TESTS PASSED" if failures == 0 else f"{failures} TEST(S) FAILED")
sys.exit(1 if failures else 0)
