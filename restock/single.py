"""Only one copy of the app per folder.

Two copies would post every Discord alert twice, fight over the same browser profile (the
second browser refuses to start) and over the control panel's port. The lock is per folder,
so a separate test copy in another folder still runs alongside.
"""
from __future__ import annotations

import hashlib
import os
import sys

_HELD = None    # keeps the lock alive for the life of the process


def _key(folder: str) -> str:
    return hashlib.sha1(os.path.normcase(os.path.abspath(folder)).encode()).hexdigest()[:16]


def acquire(folder: str) -> bool:
    """True if this is the only copy running from `folder` (and keeps it that way), False if another
    copy already holds it. Never raises: if the check itself fails, the app is allowed to run."""
    global _HELD
    if _HELD is not None:
        return True
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateMutexW.restype = wintypes.HANDLE
            kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
            handle = kernel32.CreateMutexW(None, False, f"Local\\Searchemon-{_key(folder)}")
            if not handle:
                return True
            if ctypes.get_last_error() == 183:        # ERROR_ALREADY_EXISTS
                kernel32.CloseHandle(handle)
                return False
            _HELD = handle
            return True
        import fcntl
        os.makedirs(os.path.join(folder, "data"), exist_ok=True)
        fh = open(os.path.join(folder, "data", ".running.lock"), "w")
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False
        _HELD = fh
        return True
    except Exception:
        return True


def release() -> None:
    """Let go of the lock (only needed by tests; it is freed by Windows when the app exits)."""
    global _HELD
    held, _HELD = _HELD, None
    if held is None:
        return
    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.WinDLL("kernel32").CloseHandle(held)
        else:
            held.close()
    except Exception:
        pass
