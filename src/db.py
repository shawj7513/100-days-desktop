"""The database: one SQLite file in her AppData folder.

Timestamps are ISO 8601 text in UTC ("2026-11-22T14:05:00Z"). A session with no
ended_at is the one running now. Minutes are never stored: they are calculated
from the timestamps, so they can't disagree with them.
"""

import sqlite3
from datetime import date

from paths import db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS course_days (
    day_number    INTEGER PRIMARY KEY CHECK (day_number BETWEEN 1 AND 100),
    is_complete   INTEGER NOT NULL DEFAULT 0 CHECK (is_complete BETWEEN 0 AND 1),
    completed_at  TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY,
    day_number  INTEGER NOT NULL REFERENCES course_days(day_number),
    started_at  TEXT NOT NULL,
    ended_at    TEXT CHECK (ended_at IS NULL OR ended_at >= started_at)
);

CREATE TABLE IF NOT EXISTS pauses (
    id          INTEGER PRIMARY KEY,
    session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    paused_at   TEXT NOT NULL,
    resumed_at  TEXT CHECK (resumed_at IS NULL OR resumed_at >= paused_at)
);

CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);

-- Safety nets: the database itself refuses a second running session, or a
-- second open pause in one session, even if the code has a bug.
CREATE UNIQUE INDEX IF NOT EXISTS one_running_session
    ON sessions ((1)) WHERE ended_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS one_open_pause
    ON pauses (session_id) WHERE resumed_at IS NULL;
"""

# Used when a setting has never been saved. The start date is filled in with
# today's date the first time the app runs.
DEFAULT_SETTINGS = {
    "course_name": "100 Days of Code",
    "min_session_minutes": "20",
    "theme": "system",
}


def connect():
    # check_same_thread=False: FastAPI may open and close a connection on
    # different worker threads. Each request gets its own connection.
    conn = sqlite3.connect(db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create the tables and the 100 course days. Safe to run on every launch."""
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT OR IGNORE INTO course_days (day_number) VALUES (?)",
            [(n,) for n in range(1, 101)],
        )
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('course_start_date', ?)",
            (date.today().isoformat(),),
        )
        conn.executemany(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            list(DEFAULT_SETTINGS.items()),
        )
        conn.commit()
    finally:
        conn.close()
