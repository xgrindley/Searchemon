"""Be a good background program on Windows, so the app can run while you use the PC.

low_priority (default on): the app and the browsers it starts run at below-normal priority, so games, video
calls and everything else you are doing get the CPU first. Checks are mostly waiting, so they lose almost nothing.
keep_awake (default off): stop Windows going to sleep while the app runs (the screen can still turn off).
Turn it on if the PC sleeps when idle and you want checks to carry on overnight.
Both do nothing on other systems.
"""
from __future__ import annotations

import os

BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def apply(power: dict | None) -> list[str]:
    """Apply the settings. Returns what was done, for the log and tests. Never raises."""
    power = power or {}
    done: list[str] = []
    if os.name != "nt":
        return done
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        if power.get("low_priority", True):
            if kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), BELOW_NORMAL_PRIORITY_CLASS):
                done.append("low priority")
        if power.get("keep_awake", False):
            kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
            done.append("keep awake")
    except Exception:
        pass
    return done


def read_settings(config_path: str) -> dict:
    try:
        import yaml
        with open(config_path, encoding="utf-8") as fh:
            return (yaml.safe_load(fh) or {}).get("power") or {}
    except Exception:
        return {}
