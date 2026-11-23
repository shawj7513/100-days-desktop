"""
Starts the app: runs the API on this PC only (127.0.0.1, a free port), then
opens a native window showing it. Close the window and everything stops.

    uv run python src/app.py
"""

import socket
import threading
import time

import uvicorn
import webview

import db
from server import app


def free_port():
    """Ask Windows for any unused port on this PC."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    db.init_db()
    port = free_port()
    # log_config=None: a windowed .exe has no console, and uvicorn's default
    # logging would crash trying to write to one.
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None)
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)

    webview.settings["ALLOW_DOWNLOADS"] = True   # lets Export and Backup save files
    webview.create_window(
        "100 Days Tracker",
        f"http://127.0.0.1:{port}/",
        width=760,
        height=900,
        min_size=(420, 600),
    )
    webview.start()          # returns when the window is closed
    server.should_exit = True


if __name__ == "__main__":
    main()
