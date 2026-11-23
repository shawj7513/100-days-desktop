"""
The API behind the window. The page (public/app.js) asks THIS file for data by
calling URLs like /api/days; each URL is one function below. Everything runs on
her own PC (127.0.0.1): no internet, no accounts.

Layout:
  1. Helpers (time, database, settings, validation)
  2. Routes: days, sessions, settings, stats, export/backup/reset
  3. The page itself (public/) is served last, from "/"
"""

import csv
import io
import sqlite3
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

import db as database
from paths import COURSE_TITLE, COURSE_URL, VERSION, app_dir, data_dir, db_path
from stats import build_stats

app = FastAPI(title="100 Days Tracker")

MAX_SESSION_MINUTES = 12 * 60   # sanity cap for sessions entered by hand
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
THEMES = ("system", "light", "dark", "ocean", "forest", "sunset", "contrast")


# ---------------------------------------------------------------------------
# HELPERS: time
# ---------------------------------------------------------------------------

def now_utc():
    """Current time as the text we store: 2026-11-22T14:05:00Z."""
    return datetime.now(timezone.utc).strftime(TIMESTAMP_FORMAT)


def parse_ts(text):
    """Turn ISO text into a UTC datetime. Raises ValueError if unusable."""
    if not isinstance(text, str):
        raise ValueError("timestamps must be text like 2026-11-22T14:05:00Z")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"'{text}' is not a timestamp like 2026-11-22T14:05:00Z")
    if parsed.tzinfo is None:
        raise ValueError("timestamps need a timezone, e.g. a trailing Z")
    return parsed.astimezone(timezone.utc)


def format_ts(moment):
    """The reverse of parse_ts: a datetime back into stored text."""
    return moment.astimezone(timezone.utc).strftime(TIMESTAMP_FORMAT)


# ---------------------------------------------------------------------------
# HELPERS: database
# ---------------------------------------------------------------------------

def get_db():
    """One database connection per request, closed afterwards."""
    conn = database.connect()
    try:
        yield conn
    finally:
        conn.close()


def fetch_all(conn, sql, *params):
    """Run a SELECT and return every row as a dict. Values always go in through
    `params` (the ? marks), never into the SQL text."""
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def fetch_one(conn, sql, *params):
    rows = fetch_all(conn, sql, *params)
    return rows[0] if rows else None


def execute(conn, sql, *params):
    """Run an INSERT, UPDATE or DELETE and save it."""
    conn.execute(sql, params)
    conn.commit()


# Minutes of pause inside session `s`. Only closed pauses are counted.
PAUSED_MINUTES_SQL = """COALESCE((
    SELECT SUM((julianday(p.resumed_at) - julianday(p.paused_at)) * 1440)
    FROM pauses p
    WHERE p.session_id = s.id AND p.resumed_at IS NOT NULL
), 0)"""

# Active minutes of a FINISHED session `s`: start to stop, minus pauses.
# These snippets are fixed text written here, not user input, so joining them
# into bigger queries is safe.
ACTIVE_MINUTES_SQL = (
    "(julianday(s.ended_at) - julianday(s.started_at)) * 1440 - " + PAUSED_MINUTES_SQL
)

# Active minutes if the running session stopped at a given moment. An open
# pause is treated as ending at that moment too.
MINUTES_IF_STOPPED_SQL = """SELECT ROUND(
    (julianday(?) - julianday(s.started_at)) * 1440 - COALESCE((
        SELECT SUM((julianday(COALESCE(p.resumed_at, ?)) - julianday(p.paused_at)) * 1440)
        FROM pauses p WHERE p.session_id = s.id
    ), 0), 1) AS minutes
FROM sessions s WHERE s.id = ?"""


# ---------------------------------------------------------------------------
# HELPERS: settings
# ---------------------------------------------------------------------------

def read_settings(conn):
    """All settings as a dict, with numbers as numbers."""
    rows = fetch_all(conn, "SELECT key, value FROM settings")
    values = {row["key"]: row["value"] for row in rows}
    return {
        "course_name": values.get("course_name", "100 Days of Code"),
        "course_start_date": values.get("course_start_date", date.today().isoformat()),
        "min_session_minutes": int(values.get("min_session_minutes", "20")),
        "theme": values.get("theme", "system"),
    }


def clean_settings(changes):
    """Check the settings being saved. Returns {key: text} or raises ValueError."""
    allowed = {"course_name", "course_start_date", "min_session_minutes", "theme"}
    unknown = set(changes) - allowed
    if unknown:
        raise ValueError(f"Unknown setting: {sorted(unknown)[0]}")
    clean = {}
    if "course_name" in changes:
        name = str(changes["course_name"]).strip()
        if not 1 <= len(name) <= 60:
            raise ValueError("The course name must be 1 to 60 characters")
        clean["course_name"] = name
    if "course_start_date" in changes:
        try:
            start = date.fromisoformat(str(changes["course_start_date"]))
        except ValueError:
            raise ValueError("The start date must look like 2026-11-22")
        if start > date.today() + timedelta(days=1):
            raise ValueError("The start date can't be in the future")
        clean["course_start_date"] = start.isoformat()
    if "min_session_minutes" in changes:
        minutes = changes["min_session_minutes"]
        if isinstance(minutes, bool) or not isinstance(minutes, int) or not 1 <= minutes <= 180:
            raise ValueError("The minimum session length must be a whole number from 1 to 180")
        clean["min_session_minutes"] = str(minutes)
    if "theme" in changes:
        if changes["theme"] not in THEMES:
            raise ValueError("That isn't one of the available themes")
        clean["theme"] = changes["theme"]
    return clean


# ---------------------------------------------------------------------------
# HELPERS: requests and validation
# ---------------------------------------------------------------------------

async def read_json(request):
    """The request body as a dict, or a 422 error if it isn't one."""
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Body must be JSON")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Body must be a JSON object")
    return payload


def require_day(conn, day_number):
    """Return the course_days row, or raise 422 (not a number) / 404 (no such day)."""
    if isinstance(day_number, bool) or not isinstance(day_number, int):
        raise HTTPException(status_code=422, detail="day_number must be a whole number")
    day = fetch_one(
        conn,
        "SELECT day_number, is_complete, completed_at FROM course_days WHERE day_number = ?",
        day_number,
    )
    if day is None:
        raise HTTPException(status_code=404, detail=f"There is no course day {day_number}")
    return day


def check_past_session(started, ended, paused_minutes, now, min_minutes):
    """Rules for a session typed in by hand. Raises ValueError with a message
    for the first rule broken. Pure Python: no database, easy to test."""
    if ended <= started:
        raise ValueError("The stop time must be after the start time")
    if ended > now:
        raise ValueError("That session ends in the future")
    total_minutes = (ended - started).total_seconds() / 60
    if total_minutes > MAX_SESSION_MINUTES:
        raise ValueError(f"A session can't be longer than {MAX_SESSION_MINUTES // 60} hours")
    if isinstance(paused_minutes, bool) or not isinstance(paused_minutes, (int, float)):
        raise ValueError("paused_minutes must be a number")
    if paused_minutes < 0 or paused_minutes >= total_minutes:
        raise ValueError("paused_minutes must be between 0 and the session length")
    active_minutes = total_minutes - paused_minutes
    if active_minutes < min_minutes:
        raise ValueError(
            f"That is only {active_minutes:.0f} active minutes; "
            f"a session needs at least {min_minutes}"
        )


def running_session(conn):
    """The session being timed right now (with its pauses), or None."""
    session = fetch_one(
        conn, "SELECT id, day_number, started_at FROM sessions WHERE ended_at IS NULL"
    )
    if session is None:
        return None
    pauses = fetch_all(
        conn,
        "SELECT paused_at, resumed_at FROM pauses WHERE session_id = ? ORDER BY paused_at",
        session["id"],
    )
    session["pauses"] = pauses
    session["paused"] = any(p["resumed_at"] is None for p in pauses)
    return session


# ---------------------------------------------------------------------------
# ROUTES: about and settings
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/about")
def about():
    return {
        "version": VERSION,
        "data_folder": str(data_dir()),
        "database": str(db_path()),
        "course_title": COURSE_TITLE,
        "course_url": COURSE_URL,
    }


@app.get("/api/settings")
def get_settings(conn: sqlite3.Connection = Depends(get_db)):
    return read_settings(conn)


@app.put("/api/settings")
async def save_settings(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    """Save one or more settings. Body example: {"theme": "dark"}."""
    changes = await read_json(request)
    try:
        clean = clean_settings(changes)
    except ValueError as problem:
        raise HTTPException(status_code=422, detail=str(problem))
    for key, value in clean.items():
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
    conn.commit()
    return read_settings(conn)


# ---------------------------------------------------------------------------
# ROUTES: read days
# ---------------------------------------------------------------------------

def list_days_rows(conn):
    """All 100 days in order, with session count and total active minutes.
    Days with no sessions still appear (that's the LEFT JOIN)."""
    return fetch_all(
        conn,
        "WITH finished AS ("
        "  SELECT s.id, s.day_number, " + ACTIVE_MINUTES_SQL + " AS minutes"
        "  FROM sessions s WHERE s.ended_at IS NOT NULL"
        ") "
        "SELECT d.day_number, d.is_complete, d.completed_at,"
        "       COUNT(f.id) AS session_count,"
        "       COALESCE(ROUND(SUM(f.minutes), 1), 0) AS total_minutes "
        "FROM course_days d "
        "LEFT JOIN finished f ON f.day_number = d.day_number "
        "GROUP BY d.day_number "
        "ORDER BY d.day_number",
    )


@app.get("/api/days")
def list_days(conn: sqlite3.Connection = Depends(get_db)):
    return list_days_rows(conn)


@app.get("/api/days/{day_number}")
def get_day(day_number: int, conn: sqlite3.Connection = Depends(get_db)):
    """One day: its sessions (each with active minutes) plus totals."""
    day = require_day(conn, day_number)
    sessions = fetch_all(
        conn,
        "SELECT s.id, s.started_at, s.ended_at,"
        "  (SELECT COUNT(*) FROM pauses p WHERE p.session_id = s.id) AS pause_count,"
        "  ROUND(" + PAUSED_MINUTES_SQL + ", 1) AS paused_minutes,"
        "  CASE WHEN s.ended_at IS NULL THEN NULL"
        "       ELSE ROUND(" + ACTIVE_MINUTES_SQL + ", 1) END AS active_minutes "
        "FROM sessions s WHERE s.day_number = ? ORDER BY s.started_at",
        day_number,
    )
    finished = [s for s in sessions if s["active_minutes"] is not None]
    day["sessions"] = sessions
    day["session_count"] = len(finished)
    day["total_minutes"] = round(sum(s["active_minutes"] for s in finished), 1)
    return day


# ---------------------------------------------------------------------------
# ROUTES: write sessions
# ---------------------------------------------------------------------------

@app.get("/api/sessions/current")
def current_session(conn: sqlite3.Connection = Depends(get_db)):
    """The running session (or null) plus the server's clock, so the timer
    survives a reload and isn't fooled by a wrong clock."""
    return {"session": running_session(conn), "server_now": now_utc()}


@app.post("/api/sessions/start")
async def start_session(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    """Start timing a course day. Body: {"day_number": 10}. The SERVER stamps the time."""
    payload = await read_json(request)
    day = require_day(conn, payload.get("day_number"))
    if day["is_complete"]:
        raise HTTPException(status_code=409, detail="That day is already complete")
    if running_session(conn) is not None:
        raise HTTPException(status_code=409, detail="A session is already running")
    execute(
        conn,
        "INSERT INTO sessions (day_number, started_at) VALUES (?, ?)",
        day["day_number"],
        now_utc(),
    )
    return running_session(conn)


@app.post("/api/sessions/pause")
def pause_session(conn: sqlite3.Connection = Depends(get_db)):
    session = running_session(conn)
    if session is None:
        raise HTTPException(status_code=409, detail="No session is running")
    if session["paused"]:
        raise HTTPException(status_code=409, detail="Already paused")
    execute(
        conn, "INSERT INTO pauses (session_id, paused_at) VALUES (?, ?)", session["id"], now_utc()
    )
    return running_session(conn)


@app.post("/api/sessions/resume")
def resume_session(conn: sqlite3.Connection = Depends(get_db)):
    session = running_session(conn)
    if session is None:
        raise HTTPException(status_code=409, detail="No session is running")
    if not session["paused"]:
        raise HTTPException(status_code=409, detail="Not paused")
    execute(
        conn,
        "UPDATE pauses SET resumed_at = ? WHERE session_id = ? AND resumed_at IS NULL",
        now_utc(),
        session["id"],
    )
    return running_session(conn)


@app.post("/api/sessions/stop")
def stop_session(conn: sqlite3.Connection = Depends(get_db)):
    """Stop the running session. Under the minimum it is refused (409) and
    keeps running; she can carry on or discard it."""
    session = running_session(conn)
    if session is None:
        raise HTTPException(status_code=409, detail="No session is running")
    minimum = read_settings(conn)["min_session_minutes"]
    stopped_at = now_utc()
    row = fetch_one(conn, MINUTES_IF_STOPPED_SQL, stopped_at, stopped_at, session["id"])
    if row["minutes"] < minimum:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Only {row['minutes']:.0f} active minutes so far; a session needs "
                f"at least {minimum}. Keep going, or discard it."
            ),
        )
    execute(
        conn,
        "UPDATE pauses SET resumed_at = ? WHERE session_id = ? AND resumed_at IS NULL",
        stopped_at,
        session["id"],
    )
    execute(conn, "UPDATE sessions SET ended_at = ? WHERE id = ?", stopped_at, session["id"])
    return {"stopped": True, "active_minutes": row["minutes"]}


@app.post("/api/sessions/discard")
def discard_session(conn: sqlite3.Connection = Depends(get_db)):
    session = running_session(conn)
    if session is None:
        raise HTTPException(status_code=409, detail="No session is running")
    execute(conn, "DELETE FROM pauses WHERE session_id = ?", session["id"])
    execute(conn, "DELETE FROM sessions WHERE id = ?", session["id"])
    return {"discarded": True}


@app.post("/api/sessions")
async def add_past_session(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    """Add a finished session by hand (she forgot to tap Start).
    Body: {"day_number", "started_at", "ended_at", "paused_minutes" (optional)}."""
    payload = await read_json(request)
    day = require_day(conn, payload.get("day_number"))
    if day["is_complete"]:
        raise HTTPException(status_code=409, detail="That day is already complete")
    paused_minutes = payload.get("paused_minutes", 0)
    minimum = read_settings(conn)["min_session_minutes"]
    try:
        started = parse_ts(payload.get("started_at"))
        ended = parse_ts(payload.get("ended_at"))
        check_past_session(started, ended, paused_minutes, datetime.now(timezone.utc), minimum)
    except ValueError as problem:
        raise HTTPException(status_code=422, detail=str(problem))

    started_text, ended_text = format_ts(started), format_ts(ended)
    clash = fetch_one(
        conn,
        "SELECT id FROM sessions WHERE started_at < ? AND COALESCE(ended_at, '9999-12-31T00:00:00Z') > ?",
        ended_text,
        started_text,
    )
    if clash is not None:
        raise HTTPException(status_code=409, detail="That overlaps another session")

    cursor = conn.execute(
        "INSERT INTO sessions (day_number, started_at, ended_at) VALUES (?, ?, ?)",
        (day["day_number"], started_text, ended_text),
    )
    if paused_minutes > 0:
        # We only know HOW LONG she paused, so record it as one pause at the start.
        pause_end = format_ts(started + timedelta(minutes=paused_minutes))
        conn.execute(
            "INSERT INTO pauses (session_id, paused_at, resumed_at) VALUES (?, ?, ?)",
            (cursor.lastrowid, started_text, pause_end),
        )
    conn.commit()
    return {"added": True}


@app.post("/api/days/{day_number}/toggle-complete")
def toggle_complete(day_number: int, conn: sqlite3.Connection = Depends(get_db)):
    """Flip a day between complete and not complete. A toggle, so a misclick is undoable."""
    day = require_day(conn, day_number)
    if day["is_complete"]:
        execute(
            conn,
            "UPDATE course_days SET is_complete = 0, completed_at = NULL WHERE day_number = ?",
            day_number,
        )
    else:
        running = running_session(conn)
        if running is not None and running["day_number"] == day_number:
            raise HTTPException(status_code=409, detail="Stop the running session first")
        execute(
            conn,
            "UPDATE course_days SET is_complete = 1, completed_at = ? WHERE day_number = ?",
            now_utc(),
            day_number,
        )
    return require_day(conn, day_number)


# ---------------------------------------------------------------------------
# ROUTES: stats
# ---------------------------------------------------------------------------

def fetch_finished_sessions(conn):
    """Every finished session as a list of dicts, oldest first: id, day_number,
    started_at, ended_at (UTC text) and active_minutes (pauses already taken out)."""
    return fetch_all(
        conn,
        "SELECT s.id, s.day_number, s.started_at, s.ended_at,"
        "       ROUND(" + ACTIVE_MINUTES_SQL + ", 1) AS active_minutes "
        "FROM sessions s WHERE s.ended_at IS NOT NULL ORDER BY s.started_at",
    )


@app.get("/api/stats")
def get_stats(tz: str = "UTC", conn: sqlite3.Connection = Depends(get_db)):
    """All the summary numbers. The page sends its own timezone (?tz=...) so
    "today" and each streak day follow her calendar. The maths is in stats.py."""
    try:
        zone = ZoneInfo(tz)
    except Exception:
        raise HTTPException(status_code=422, detail=f"Unknown timezone '{tz}'")
    settings = read_settings(conn)
    start_date = date.fromisoformat(settings["course_start_date"])
    today = datetime.now(zone).date()
    return build_stats(
        list_days_rows(conn),
        fetch_finished_sessions(conn),
        start_date,
        today,
        zone,
        settings["min_session_minutes"],
    )


# ---------------------------------------------------------------------------
# ROUTES: her data (export, backup, reset)
# ---------------------------------------------------------------------------

@app.get("/api/export.csv")
def export_csv(conn: sqlite3.Connection = Depends(get_db)):
    """Every finished session as a spreadsheet-friendly CSV download."""
    rows = fetch_all(
        conn,
        "SELECT s.day_number, s.started_at, s.ended_at,"
        "       ROUND(" + PAUSED_MINUTES_SQL + ", 1) AS paused_minutes,"
        "       ROUND(" + ACTIVE_MINUTES_SQL + ", 1) AS active_minutes "
        "FROM sessions s WHERE s.ended_at IS NOT NULL ORDER BY s.started_at",
    )
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["course_day", "started_at_utc", "ended_at_utc", "paused_minutes", "active_minutes"])
    for row in rows:
        writer.writerow([
            row["day_number"], row["started_at"], row["ended_at"],
            row["paused_minutes"], row["active_minutes"],
        ])
    filename = f"100days-sessions-{date.today().isoformat()}.csv"
    return Response(
        out.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/backup")
def backup():
    """A safe copy of the whole database file, as a download."""
    handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    handle.close()
    source = database.connect()
    target = sqlite3.connect(handle.name)
    try:
        source.backup(target)    # copies correctly even while the app is in use
    finally:
        target.close()
        source.close()
    filename = f"100days-backup-{date.today().isoformat()}.db"
    return FileResponse(
        handle.name,
        media_type="application/octet-stream",
        filename=filename,
        background=BackgroundTask(lambda: Path(handle.name).unlink(missing_ok=True)),
    )


@app.post("/api/reset")
async def reset_all(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    """Erase every session and un-complete every day. Needs {"confirm": "RESET"}.
    Settings are kept."""
    payload = await read_json(request)
    if payload.get("confirm") != "RESET":
        raise HTTPException(status_code=422, detail='Send {"confirm": "RESET"} to erase everything')
    conn.execute("DELETE FROM pauses")
    conn.execute("DELETE FROM sessions")
    conn.execute("UPDATE course_days SET is_complete = 0, completed_at = NULL")
    conn.commit()
    return {"reset": True}


# ---------------------------------------------------------------------------
# THE PAGE: must be last, so /api/... routes win
# ---------------------------------------------------------------------------

app.mount("/", StaticFiles(directory=app_dir() / "public", html=True), name="public")
