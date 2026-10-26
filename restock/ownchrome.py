"""Start your own Chrome for the stores that refuse the app's automated browsers (CVS, Dick's, GameStop, Sam's Club).

This is what start-my-chrome.ps1 does, done by the app itself the first time such a store needs it, so a store does not
sit on "Blocked" until you remember to start Chrome by hand. It opens a normal Chrome window, minimized, with its own
profile in data\\my-chrome (your everyday Chrome, passwords and history are never touched), with DevTools open on this
PC only. Switch off with browser.auto_start_own_chrome: false.
"""
from __future__ import annotations

import os
import subprocess
import sys

CANDIDATES = (
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
)


def find_chrome() -> str:
    for c in CANDIDATES:
        path = os.path.expandvars(c)
        if "%" not in path and os.path.isfile(path):
            return path
    return ""


def command(chrome: str, port: int, profile: str) -> list[str]:
    return [chrome, f"--remote-debugging-port={port}", "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check", "--start-minimized"]


def start(port: int, data_dir: str, log=None) -> bool:
    """Launch Chrome minimized with DevTools on `port`. Returns True when it was started. Never raises."""
    if sys.platform != "win32":
        return False
    chrome = find_chrome()
    if not chrome:
        if log:
            log.info("Your own Chrome could not be started: Chrome is not installed in a standard folder")
        return False
    profile = os.path.join(data_dir, "my-chrome")
    try:
        os.makedirs(profile, exist_ok=True)
        subprocess.Popen(command(chrome, port, profile), close_fds=True,
                         creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        return True
    except Exception as exc:
        if log:
            log.info("Your own Chrome could not be started: %s", str(exc)[:100])
        return False
