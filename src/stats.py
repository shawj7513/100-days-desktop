"""
Stats for the 100 Days desktop tracker.

This is the desktop app's OWN copy of stats.py. It started as a copy of the web
version's file and is free to change on its own.

Rules: plain functions, no classes, no database, no web code. Every function
takes plain Python data (lists, dicts, dates) and returns a number, a date, or
a dict. That is what makes them easy to test: tests/test_stats.py runs them
with no app running at all:

    uv run python tests/test_stats.py

The docstring on each function is its spec; the test file shows examples of
what it must return. To add a stat: write a test first, write the function,
then add its key to build_stats (and a label in public/app.js).

What the data looks like
------------------------
A "day" is a dict (this is one row of /api/days):

    {"day_number": 10, "is_complete": 0, "completed_at": None,
     "session_count": 2, "total_minutes": 75.2}

    - is_complete is 1 or 0 (not True/False)
    - total_minutes is 0 for a day with no finished sessions
      (the web version also adds estimated minutes for days it never timed;
      the desktop app has none, so total_minutes is just the timed sessions)

A "session" is a dict (from fetch_finished_sessions in main.py):

    {"id": 1, "day_number": 10,
     "started_at": "2026-11-22T22:17:40Z", "ended_at": "2026-11-22T22:52:52Z",
     "active_minutes": 35.2}

    - the timestamps are UTC TEXT ending in Z, not datetime objects
    - active_minutes already has the pauses taken out

Dates are datetime.date objects. `tz` is a datetime tzinfo (the user's timezone).
"""

from datetime import date, datetime, timedelta, timezone  # noqa: F401

MIN_DAY_MINUTES = 20   # default; the app passes the value from Settings
TOTAL_DAYS = 100


# ---------------------------------------------------------------------------
# Counting and totals
# ---------------------------------------------------------------------------

def count_complete(days):
    """How many days have is_complete == 1."""
    count = 0
    for day in days:
        if day["is_complete"] == 1:
            count = count + 1
    return count

def percent_complete(days):
    """Percent of days complete, rounded to 1 decimal: 9 of 100 days -> 9.0.
    An empty list gives 0.0 (careful: dividing by zero crashes)."""
    if len(days) == 0:
        return 0.0
    done = count_complete(days)
    fraction = done / len(days)
    return round(fraction * 100, 1)

def total_hours(days):
    """Total of every day's total_minutes, in hours, rounded to 1 decimal.
    A day's total already includes its timed sessions AND the estimated
    minutes for days 1-9, so adding up the days counts everything once.
    No minutes anywhere -> 0.0."""
    minutes = 0
    for day in days:
        minutes = minutes + day["total_minutes"]
    return round(minutes / 60, 1)

def average_minutes_per_completed_day(days):
    """Average total_minutes over the days that are complete AND have time
    logged (days 1-9 have none, and would drag the average to nonsense).
    Rounded to 1 decimal. If there are no such days, return None."""
    minutes = []
    for day in days:
        if day["is_complete"] == 1 and day["total_minutes"] > 0:
            minutes.append(day["total_minutes"])
    if len(minutes) == 0:
        return None
    return round(sum(minutes) / len(minutes), 1)


def hardest_day(days):
    """The day (the whole dict) with the most total_minutes. If no day has any
    minutes logged, return None."""
    hardest = None
    for day in days:
        if day["total_minutes"] > 0:
            if hardest is None or day["total_minutes"] > hardest["total_minutes"]:
                hardest = day
    return hardest


# ---------------------------------------------------------------------------
# Dates and timezones
# ---------------------------------------------------------------------------

def days_elapsed(start_date, today):
    """Whole calendar days from start_date to today (both dates).
    2026-10-25 to 2026-11-22 is 28."""
    # Subtracting two dates gives a timedelta; .days is its whole-day count.
    return (today - start_date).days


def to_local_date(timestamp, tz):
    """Turn UTC text like "2026-11-23T03:30:00Z" into the calendar date (a
    datetime.date) it falls on in timezone tz."""
    moment = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return moment.astimezone(tz).date()


def minutes_by_date(sessions, tz):
    """Add up active_minutes per LOCAL calendar date. Returns a dict like
    {date(2026, 11, 22): 55.0}. Use each session's started_at. Sessions for
    different course days on the same date are added together: the streak is
    about the daily habit, not about which course day it was."""
    totals = {}
    for session in sessions:
        local_date = to_local_date(session["started_at"], tz)
        totals[local_date] = totals.get(local_date, 0) + session["active_minutes"]
    return totals


# ---------------------------------------------------------------------------
# Streaks
# ---------------------------------------------------------------------------

def qualifying_dates(minutes_per_date, min_minutes=MIN_DAY_MINUTES):
    """Take the dict from minutes_by_date and return a SORTED list of the dates
    with at least min_minutes minutes (exactly the minimum counts)."""
    dates = []
    for local_date, minutes in minutes_per_date.items():
        if minutes >= min_minutes:
            dates.append(local_date)
    return sorted(dates)


def current_streak(qualifying, today):
    """How many calendar days in a row, ending today, are in `qualifying`
    (a sorted list of dates). If today isn't in it yet, count back from
    yesterday instead, so the streak doesn't read 0 every morning before you
    have started. If neither today nor yesterday is in it, the streak is 0."""
    # A set makes "is this date in it?" quick.
    dates = set(qualifying)
    one_day = timedelta(days=1)
    day = today if today in dates else today - one_day
    streak = 0
    while day in dates:
        streak = streak + 1
        day = day - one_day
    return streak


def longest_streak(qualifying):
    """The longest run of consecutive calendar days anywhere in `qualifying`.
    An empty list gives 0."""
    one_day = timedelta(days=1)
    longest = 0
    run = 0
    previous = None
    for day in sorted(qualifying):
        if previous is not None and day - previous == one_day:
            run = run + 1    # the run continues
        else:
            run = 1          # a gap (or the very first date): a new run starts
        if run > longest:
            longest = run
        previous = day
    return longest


# ---------------------------------------------------------------------------
# Pace and projection
# ---------------------------------------------------------------------------

def average_real_days_per_course_day(days, start_date, today):
    """Real calendar days spent per completed course day, rounded to 1
    decimal: days_elapsed(start_date, today) divided by the number of complete
    days. If nothing is complete yet, return None."""
    done = count_complete(days)
    if done == 0:
        return None
    return round(days_elapsed(start_date, today) / done, 1)


def projected_finish_date(days, average_days, today):
    """The projected finish date if the pace holds: today plus (days remaining x
    average_days), rounded to whole days. Remaining = TOTAL_DAYS minus the
    complete days. If average_days is None, return None."""
    if average_days is None:
        return None
    remaining = TOTAL_DAYS - count_complete(days)
    return today + timedelta(days=round(remaining * average_days))


# ---------------------------------------------------------------------------
# Everything together
# ---------------------------------------------------------------------------

def build_stats(days, sessions, start_date, today, tz, min_minutes=MIN_DAY_MINUTES):
    """Collect every stat into ONE dict, calling the functions above. Each
    function does one job; this one just gathers them. Use exactly
    these keys (the page shows them as a list):

        start_date, days_elapsed, days_complete, percent_complete,
        total_hours, avg_minutes_per_completed_day,
        avg_real_days_per_course_day, projected_finish_date,
        current_streak, longest_streak, hardest_day

    Dates go in as text (date.isoformat()) so they turn into JSON, and
    hardest_day is just the day NUMBER (or None). Use the standard
    (current, longest) streak on `today` in the timezone tz. A calendar day
    counts toward a streak at min_minutes or more (a setting in the app)."""
    average_days = average_real_days_per_course_day(days, start_date, today)
    finish = projected_finish_date(days, average_days, today)
    qualifying = qualifying_dates(minutes_by_date(sessions, tz), min_minutes)
    hardest = hardest_day(days)

    return {
        "start_date": start_date.isoformat(),
        "days_elapsed": days_elapsed(start_date, today),
        "days_complete": count_complete(days),
        "percent_complete": percent_complete(days),
        "total_hours": total_hours(days),
        "avg_minutes_per_completed_day": average_minutes_per_completed_day(days),
        "avg_real_days_per_course_day": average_days,
        "projected_finish_date": finish.isoformat() if finish is not None else None,
        "current_streak": current_streak(qualifying, today),
        "longest_streak": longest_streak(qualifying),
        "hardest_day": hardest["day_number"] if hardest is not None else None,
    }
