"""Launcher: `python -m backend` starts the server and opens the app window."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import threading
import time
import urllib.request
import webbrowser

import uvicorn

from .config import get_config

APP_MODE_BROWSERS = ["google-chrome", "chromium", "chromium-browser", "brave-browser", "microsoft-edge"]


def server_alive(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/api/status", timeout=1) as r:
            return r.status == 200
    except OSError:
        return False


def open_app(url: str) -> None:
    """Prefer a chromeless 'app' window; fall back to the default browser."""
    for browser in APP_MODE_BROWSERS:
        if path := shutil.which(browser):
            subprocess.Popen([path, f"--app={url}"], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
            return
    webbrowser.open(url)


def main() -> None:
    cfg = get_config()
    parser = argparse.ArgumentParser(prog="ai-stock-radar")
    parser.add_argument("--host", default=cfg.settings.server.host)
    parser.add_argument("--port", type=int, default=cfg.settings.server.port)
    parser.add_argument("--no-browser", action="store_true", help="start the server without opening a window")
    args = parser.parse_args()
    url = f"http://{args.host}:{args.port}"

    if server_alive(url):
        print(f"AI Stock Radar is already running at {url}")
        if not args.no_browser:
            open_app(url)
        return

    if not args.no_browser:
        def wait_and_open():
            for _ in range(100):
                if server_alive(url):
                    open_app(url)
                    return
                time.sleep(0.2)
        threading.Thread(target=wait_and_open, daemon=True).start()

    print(f"AI Stock Radar → {url}  (Ctrl+C to stop)")
    uvicorn.run("backend.main:app", host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
