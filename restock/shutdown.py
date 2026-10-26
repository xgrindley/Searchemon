"""Make sure the browsers close when the app does, however it is closed.

Closing the window runs the normal shutdown. This also covers the other ways an app ends: Ctrl+C in the
console, closing the console window (Windows gives a few seconds), logging off, a stop request from
another program, or Python exiting. Each of them runs the same close once; a second call does nothing.
"""
from __future__ import annotations

import atexit
import signal
import sys
import threading


def install(close, log=None) -> None:
    """Run close() once when the process is ending. close must be safe to call twice."""
    done = threading.Event()

    def run(*_):
        if done.is_set():
            return
        done.set()
        try:
            close()
        except Exception as exc:                       # never block the exit
            if log:
                log.debug("shutdown: %s", exc)

    atexit.register(run)

    def on_signal(signum, _frame):
        run()
        raise SystemExit(0)

    if threading.current_thread() is threading.main_thread():
        for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
            sig = getattr(signal, name, None)
            if sig is not None:
                try:
                    signal.signal(sig, on_signal)
                except (ValueError, OSError):
                    pass
    if sys.platform == "win32":
        try:
            import ctypes
            handler_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)

            def console(event):
                if event in (2, 5, 6):                 # close button, log off, shutdown
                    run()
                    return 1
                return 0
            keep = handler_type(console)
            ctypes.windll.kernel32.SetConsoleCtrlHandler(keep, True)
            install._keep = keep                       # keep the callback alive
        except Exception:
            pass
