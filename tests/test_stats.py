"""
Tests for src/stats.py. Run them with:

    uv run python tests/test_stats.py

Each test_ function checks one thing with `assert`. An assert that is false
stops that test and shows which line failed. The runner at the bottom runs
every test_ function and prints PASS or FAIL for each.

When you find a bug, write a test that catches it first, then fix the code.
"""

import sys
from datetime import date, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import stats  # noqa: E402

# A fixed timezone six hours behind UTC, so tests don't depend on this PC.
CENTRAL = timezone(timedelta(hours=-6))


def day(number, complete=0, minutes=0):
    return {"day_number": number, "is_complete": complete, "total_minutes": minutes}


def session(day_number, started_at, minutes):
    return {"day_number": day_number, "started_at": started_at, "active_minutes": minutes}


# ----- 6a ------------------------------------------------------------------

def test_count_complete():
    assert stats.count_complete([day(1, 1), day(2, 0), day(3, 1)]) == 2
    assert stats.count_complete([]) == 0


def test_percent_complete():
    nine_of_hundred = [day(n, 1 if n <= 9 else 0) for n in range(1, 101)]
    assert stats.percent_complete(nine_of_hundred) == 9.0
    assert stats.percent_complete([day(1, 1), day(2, 0), day(3, 0)]) == 33.3
    assert stats.percent_complete([]) == 0.0


def test_total_hours():
    # each day's total_minutes already includes its timed sessions and any estimate
    assert stats.total_hours([day(1, 1, 30), day(2, 1, 60), day(3, 0, 90)]) == 3.0
    assert stats.total_hours([day(1, 1, 100)]) == 1.7
    assert stats.total_hours([day(1), day(2)]) == 0.0
    assert stats.total_hours([]) == 0.0


def test_average_minutes_per_completed_day():
    days = [day(1, 1, 60), day(2, 1, 120), day(3, 1, 0), day(4, 0, 500)]
    # only days 1 and 2 count: complete AND time logged
    assert stats.average_minutes_per_completed_day(days) == 90.0
    assert stats.average_minutes_per_completed_day([day(1, 1, 0), day(2, 0, 50)]) is None


def test_hardest_day():
    days = [day(10, 0, 75), day(11, 0, 200), day(12, 0, 0)]
    assert stats.hardest_day(days)["day_number"] == 11
    assert stats.hardest_day([day(1), day(2)]) is None
    assert stats.hardest_day([]) is None


# ----- 6b ------------------------------------------------------------------

def test_days_elapsed():
    assert stats.days_elapsed(date(2026, 10, 25), date(2026, 11, 22)) == 28
    assert stats.days_elapsed(date(2026, 11, 22), date(2026, 11, 22)) == 0


def test_to_local_date():
    # 03:30 UTC on the 23rd is 9:30 PM on the 22nd at UTC-6
    assert stats.to_local_date("2026-11-23T03:30:00Z", CENTRAL) == date(2026, 11, 22)
    assert stats.to_local_date("2026-11-22T15:00:00Z", CENTRAL) == date(2026, 11, 22)
    assert stats.to_local_date("2026-11-22T15:00:00Z", timezone.utc) == date(2026, 11, 22)


def test_minutes_by_date():
    sessions = [
        session(10, "2026-11-22T15:00:00Z", 30),   # Nov 22, day 10
        session(11, "2026-11-22T19:00:00Z", 25),   # Nov 22, day 11: same date, added together
        session(11, "2026-11-23T03:30:00Z", 40),   # 9:30 PM on Nov 22 locally!
        session(11, "2026-11-24T15:00:00Z", 22.5),
    ]
    assert stats.minutes_by_date(sessions, CENTRAL) == {
        date(2026, 11, 22): 95,
        date(2026, 11, 24): 22.5,
    }
    assert stats.minutes_by_date([], CENTRAL) == {}


# ----- 6c ------------------------------------------------------------------

def test_qualifying_dates():
    minutes = {date(2026, 11, 24): 20, date(2026, 11, 20): 55, date(2026, 11, 22): 19.9}
    assert stats.qualifying_dates(minutes) == [date(2026, 11, 20), date(2026, 11, 24)]
    assert stats.qualifying_dates({}) == []
    # the minimum is a setting: with a 10-minute minimum the 19.9 day counts too
    assert stats.qualifying_dates(minutes, 10) == [
        date(2026, 11, 20), date(2026, 11, 22), date(2026, 11, 24)]


def test_current_streak():
    run = [date(2026, 11, 20), date(2026, 11, 21), date(2026, 11, 22)]
    assert stats.current_streak(run, date(2026, 11, 22)) == 3     # today counts
    assert stats.current_streak(run, date(2026, 11, 23)) == 3     # not yet today: count from yesterday
    assert stats.current_streak(run, date(2026, 11, 24)) == 0     # missed a whole day: broken
    gap = [date(2026, 11, 18), date(2026, 11, 20), date(2026, 11, 21), date(2026, 11, 22)]
    assert stats.current_streak(gap, date(2026, 11, 22)) == 3     # the 19th is missing
    assert stats.current_streak([], date(2026, 11, 22)) == 0


def test_longest_streak():
    dates = [date(2026, 11, 18), date(2026, 11, 19), date(2026, 11, 20),
             date(2026, 11, 25), date(2026, 11, 26)]
    assert stats.longest_streak(dates) == 3
    assert stats.longest_streak([date(2026, 11, 25)]) == 1
    assert stats.longest_streak([]) == 0


# ----- 6d ------------------------------------------------------------------

def nine_complete():
    return [day(n, 1 if n <= 9 else 0) for n in range(1, 101)]


def test_average_real_days_per_course_day():
    assert stats.average_real_days_per_course_day(nine_complete(), date(2026, 10, 25), date(2026, 11, 22)) == 3.1
    assert stats.average_real_days_per_course_day([day(1, 0)], date(2026, 10, 25), date(2026, 11, 22)) is None


def test_projected_finish_date():
    today = date(2026, 11, 22)
    # 91 days left at 3 real days each = 273 days from today
    assert stats.projected_finish_date(nine_complete(), 3.0, today) == today + timedelta(days=273)
    assert stats.projected_finish_date(nine_complete(), None, today) is None
    assert stats.projected_finish_date([day(n, 1) for n in range(1, 101)], 3.0, today) == today


# ----- 6e ------------------------------------------------------------------

def test_build_stats():
    sessions = [session(10, "2026-11-21T15:00:00Z", 30), session(10, "2026-11-22T15:00:00Z", 60)]
    days = nine_complete()
    days[9] = day(10, 0, 90)
    result = stats.build_stats(days, sessions, date(2026, 10, 25), date(2026, 11, 22), CENTRAL)
    assert set(result) == {
        "start_date", "days_elapsed", "days_complete", "percent_complete",
        "total_hours", "avg_minutes_per_completed_day",
        "avg_real_days_per_course_day", "projected_finish_date",
        "current_streak", "longest_streak", "hardest_day",
    }
    assert result["start_date"] == "2026-10-25"
    assert result["days_elapsed"] == 28
    assert result["days_complete"] == 9
    assert result["total_hours"] == 1.5
    assert result["current_streak"] == 2
    assert result["longest_streak"] == 2
    assert result["hardest_day"] == 10
    # with a 45-minute minimum, the 30-minute day no longer counts toward streaks
    strict = stats.build_stats(days, sessions, date(2026, 10, 25), date(2026, 11, 22), CENTRAL, 45)
    assert strict["current_streak"] == 1
    assert strict["longest_streak"] == 1


def test_build_stats_fresh_start():
    # a brand-new install: 100 days, nothing done, nothing logged
    fresh = [day(n) for n in range(1, 101)]
    today = date(2026, 11, 22)
    result = stats.build_stats(fresh, [], today, today, CENTRAL)
    assert result["days_complete"] == 0
    assert result["total_hours"] == 0.0
    assert result["current_streak"] == 0
    assert result["longest_streak"] == 0
    assert result["avg_real_days_per_course_day"] is None
    assert result["projected_finish_date"] is None
    assert result["hardest_day"] is None


# ---------------------------------------------------------------------------
# The runner
# ---------------------------------------------------------------------------

def run_all():
    tests = [(name, fn) for name, fn in globals().items() if name.startswith("test_")]
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
        except AssertionError:
            failed += 1
            print(f"FAIL  {name}")
            import traceback
            print("      " + traceback.format_exc().strip().splitlines()[-2].strip())
        except Exception as error:
            failed += 1
            print(f"ERROR {name}: {type(error).__name__}: {error}")
        else:
            passed += 1
            print(f"PASS  {name}")
    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
