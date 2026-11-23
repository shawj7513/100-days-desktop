"""
Tests for the API (src/server.py), using a throwaway database in a temp
folder, so real data is never touched. Run with:

    uv run python tests/test_server.py
"""

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Must happen BEFORE importing the app: point the data folder at a temp dir.
os.environ["TRACKER_DATA_DIR"] = tempfile.mkdtemp(prefix="tracker-test-")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fastapi.testclient import TestClient  # noqa: E402

import db  # noqa: E402
import server  # noqa: E402

db.init_db()
client = TestClient(server.app)


def iso(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def hours_ago(hours):
    return datetime.now(timezone.utc) - timedelta(hours=hours)


def reset():
    assert client.post("/api/reset", json={"confirm": "RESET"}).status_code == 200
    client.put("/api/settings", json={"min_session_minutes": 20})


def test_fresh_install():
    reset()
    days = client.get("/api/days").json()
    assert len(days) == 100
    assert all(d["is_complete"] == 0 and d["total_minutes"] == 0 for d in days)
    assert client.get("/api/sessions/current").json()["session"] is None
    stats = client.get("/api/stats?tz=America/Chicago").json()
    assert stats["days_complete"] == 0 and stats["current_streak"] == 0
    assert stats["projected_finish_date"] is None


def test_day_not_found():
    assert client.get("/api/days/0").status_code == 404
    assert client.get("/api/days/101").status_code == 404


def test_start_pause_resume_and_too_short():
    reset()
    assert client.post("/api/sessions/start", json={"day_number": 1}).status_code == 200
    assert client.post("/api/sessions/start", json={"day_number": 2}).status_code == 409  # one at a time
    assert client.post("/api/sessions/pause").status_code == 200
    assert client.post("/api/sessions/pause").status_code == 409
    assert client.post("/api/sessions/resume").status_code == 200
    stop = client.post("/api/sessions/stop")
    assert stop.status_code == 409 and "at least 20" in stop.json()["detail"]
    assert client.post("/api/sessions/discard").status_code == 200
    assert client.get("/api/sessions/current").json()["session"] is None


def test_min_minutes_setting_changes_the_rule():
    reset()
    assert client.put("/api/settings", json={"min_session_minutes": 1}).status_code == 200
    client.post("/api/sessions/start", json={"day_number": 1})
    # started just now, so well under 1 active minute: still refused
    assert client.post("/api/sessions/stop").status_code == 409
    client.post("/api/sessions/discard")
    # a past session of 5 minutes is fine at a 1-minute minimum, refused at 20
    body = {"day_number": 1, "started_at": iso(hours_ago(3)), "ended_at": iso(hours_ago(3) + timedelta(minutes=5))}
    assert client.post("/api/sessions", json=body).status_code == 200
    client.put("/api/settings", json={"min_session_minutes": 20})
    body["started_at"] = iso(hours_ago(5))
    body["ended_at"] = iso(hours_ago(5) + timedelta(minutes=5))
    assert client.post("/api/sessions", json=body).status_code == 422


def test_past_session_rules_and_totals():
    reset()
    start, end = hours_ago(5), hours_ago(5) - timedelta(minutes=-60)
    body = {"day_number": 3, "started_at": iso(start), "ended_at": iso(end), "paused_minutes": 15}
    assert client.post("/api/sessions", json=body).status_code == 200
    assert client.post("/api/sessions", json=body).status_code == 409          # overlaps itself
    day = client.get("/api/days/3").json()
    assert day["session_count"] == 1 and day["total_minutes"] == 45.0
    future = {"day_number": 3, "started_at": iso(hours_ago(-1)), "ended_at": iso(hours_ago(-2))}
    assert client.post("/api/sessions", json=future).status_code == 422
    stats = client.get("/api/stats?tz=UTC").json()
    assert stats["total_hours"] == 0.8      # 45 minutes
    assert stats["hardest_day"] == 3


def test_complete_toggle():
    reset()
    assert client.post("/api/days/5/toggle-complete").json()["is_complete"] == 1
    assert client.post("/api/sessions/start", json={"day_number": 5}).status_code == 409  # complete
    assert client.post("/api/days/5/toggle-complete").json()["is_complete"] == 0


def test_settings_validation():
    assert client.put("/api/settings", json={"theme": "neon"}).status_code == 422
    assert client.put("/api/settings", json={"min_session_minutes": 0}).status_code == 422
    assert client.put("/api/settings", json={"course_start_date": "2099-01-01"}).status_code == 422
    assert client.put("/api/settings", json={"course_name": "   "}).status_code == 422
    assert client.put("/api/settings", json={"bogus": 1}).status_code == 422
    saved = client.put("/api/settings", json={"theme": "forest", "course_name": "My Course"}).json()
    assert saved["theme"] == "forest" and saved["course_name"] == "My Course"
    client.put("/api/settings", json={"theme": "system", "course_name": "100 Days of Code"})


def test_reset_needs_confirmation():
    assert client.post("/api/reset", json={}).status_code == 422


def test_export_and_backup():
    reset()
    start = hours_ago(4)
    client.post("/api/sessions", json={"day_number": 2, "started_at": iso(start),
                                       "ended_at": iso(start + timedelta(minutes=30))})
    export = client.get("/api/export.csv")
    lines = export.text.strip().splitlines()
    assert lines[0].startswith("course_day,") and len(lines) == 2 and lines[1].startswith("2,")
    backup = client.get("/api/backup")
    assert backup.status_code == 200 and backup.content[:15] == b"SQLite format 3"


def test_page_is_served():
    page = client.get("/")
    assert page.status_code == 200 and "100 Days" in page.text
    assert client.get("/api/about").json()["course_url"].startswith("https://www.udemy.com/")


def run_all():
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_")]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception as error:
            failed += 1
            print(f"FAIL  {name}: {type(error).__name__}: {error}")
    print(f"\n{len(tests) - failed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
