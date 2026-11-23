"""Where things live on disk. Works both when run from source and when frozen
into an .exe by PyInstaller."""

import os
import sys
from pathlib import Path

APP_NAME = "100DaysTracker"
VERSION = "0.1.0"

# The course this tracker is built around: 100 course days, one per "day" of the class.
COURSE_TITLE = "100 Days of Code: The Complete Python Pro Bootcamp"
COURSE_URL = "https://www.udemy.com/course/100-days-of-code/"


def app_dir():
    """The folder that holds public/ (HTML, CSS, JS)."""
    if getattr(sys, "frozen", False):          # inside the PyInstaller bundle
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def data_dir():
    """The folder for her data: %APPDATA%\\100DaysTracker. Set TRACKER_DATA_DIR
    to use a different folder (the tests do, so they never touch real data)."""
    override = os.environ.get("TRACKER_DATA_DIR")
    if override:
        folder = Path(override)
    else:
        folder = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def db_path():
    return data_dir() / "tracker.db"
