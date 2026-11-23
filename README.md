# 100 Days Tracker

A small, offline Windows app for tracking a 100-day course. It shows a poster
of 100 days to check off, times your study sessions (Start, Pause, Resume,
Stop), and works out stats like your streak and projected finish date.

Everything stays on your PC. There is no account, no sign-in, no internet
connection, and no tracking.

**Made for one specific course:** the Udemy class
[100 Days of Code: The Complete Python Pro Bootcamp](https://www.udemy.com/course/100-days-of-code/).
Each of the 100 "days" in the app is one numbered day of that class, so it
matches that course's plan exactly. It isn't a generic tracker for any 100-day challenge.

> **No affiliation.** "100 Days of Code" is a trademark of its owner. This is
> an independent, unofficial project. It is not affiliated with, endorsed by,
> or sponsored by Udemy, the course's instructor, or the owner of the
> "100 Days of Code" trademark. The course name is used only to say which class
> the tracker is made for. It contains no course content.

## Features

- A 100-day poster: click a day to see its sessions, start timing, or mark it complete
- Timed sessions with pause and resume. Paused time isn't counted
- A minimum session length (20 minutes by default) so only real study counts
- Forgot to press Start? Add a past session by hand
- Stats: percent complete, hours logged, current and longest streak, pace, projected finish date, and the most time-consuming day
- Settings: course name, start date, minimum session length, and a theme (Match Windows, Light, Dark, Ocean, Forest, Sunset, High contrast)
- Export your sessions to CSV, back up your data, or erase everything and start over
- A built-in Help page

## Install

1. Go to the [latest release](../../releases/latest) and download `100DaysTracker-0.1.0-win64.zip`.
2. Unzip it anywhere (for example your Documents folder). Keep the folder together: the `.exe` needs the `_internal` folder beside it.
3. Double-click `100DaysTracker.exe`.

Requires Windows 10 or 11 (64-bit). It uses Microsoft Edge WebView2, which is
already part of Windows 11 and most up-to-date Windows 10 PCs.

**"Windows protected your PC":** the app isn't code-signed, because certificates
cost money. Windows shows this screen for any unsigned download. Click
**More info**, then **Run anyway**. Each release lists the file's SHA-256 so you
can check your download:

```powershell
Get-FileHash .\100DaysTracker-0.1.0-win64.zip -Algorithm SHA256
```

To uninstall, delete the folder. Your data is kept separately (see below).

## Your data

Everything is one file: `%APPDATA%\100DaysTracker\tracker.db`. It is never
sent anywhere. The app talks only to itself on `127.0.0.1`, which is your own
PC.

- **Back up:** Settings, then *Back up my data* (or copy that file)
- **Restore or move to another PC:** close the app, then replace `tracker.db` with the backup
- **Start over:** Settings, then *Erase everything* (settings are kept)

## How it's built

| Piece | What |
|---|---|
| Python 3.13 | the language |
| [pywebview](https://pywebview.flowrl.com/) | the native window (WebView2) |
| FastAPI + uvicorn | the local API, bound to `127.0.0.1` only |
| sqlite3 | the database |
| PyInstaller (+ Inno Setup) | packaging |

```
src/app.py       starts the API and opens the window
src/server.py    the routes: days, sessions, settings, stats, export, backup, reset
src/db.py        the database schema
src/paths.py     where files live
src/stats.py     the stats, as plain functions
public/          the page (HTML, CSS, JS)
tests/           stats and API tests
```

### Run from source

Needs [uv](https://docs.astral.sh/uv/).

```powershell
uv sync
uv run python src/app.py
```

### Tests

```powershell
uv run python tests/test_stats.py     # the stats maths
uv run python tests/test_server.py    # the API, against a throwaway database
```

### Build

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
```

This makes `dist\100DaysTracker\100DaysTracker.exe`. If the free
[Inno Setup](https://jrsoftware.org/isinfo.php) is installed, it also builds a
single-file installer from `installer.iss`.

## Contributing and issues

Bug reports and ideas are welcome in [Issues](../../issues). This is a small
personal project, so replies may be slow. Please don't include personal data
in an issue; you never need to share your database.

## License

The code is released under the [MIT license](LICENSE). That license covers
this software only. It grants no rights to the "100 Days of Code" name or to
any Udemy course content.
