"""Quick health check of the program and everything it was built with. Run: PokeRestock.exe --selftest
(or python app.py --selftest). Prints a short report, saves it as selftest.txt next to the program and
returns True when nothing required is missing. Used by build-exe.ps1 to check a fresh build before it is zipped."""
from __future__ import annotations

import importlib
import os
import sys
import tempfile

REQUIRED = ["requests", "yaml", "zipcodes", "tkinter", "restock.engine", "restock.panel", "restock.panel_page", "restock.gui",
            "restock.theme", "restock.retailers", "restock.retailers.pages", "restock.retailers.browser", "restock.trials", "restock.accounts",
            "restock.history_store", "restock.scan", "restock.tcg", "restock.catalog"]
OPTIONAL = {
    "playwright.sync_api": "checking through a browser",
    "patchright.sync_api": "the stealth browser method",
    "curl_cffi.requests": "the direct-impersonate method",
    "h2": "the direct-h2 method",
    "winotify": "Windows pop-up alerts",
}


def run(resource_dir: str, out_dir: str | None = None) -> bool:
    lines, ok = [], True

    def add(good: bool, what: str, note: str = "") -> None:
        lines.append(f"{'ok     ' if good else 'MISSING'}  {what}" + (f"  ({note})" if note else ""))

    from .util import app_version
    lines.append(f"Version {app_version() or 'unknown'}, Python {sys.version.split()[0]}, "
                 f"{'built exe' if getattr(sys, 'frozen', False) else 'from source'}")
    for name in REQUIRED:
        try:
            importlib.import_module(name)
            add(True, name)
        except Exception as exc:
            ok = False
            add(False, name, f"{exc.__class__.__name__}: {str(exc)[:80]}")
    for name, why in OPTIONAL.items():
        if name == "winotify" and sys.platform != "win32":
            continue
        try:
            importlib.import_module(name)
            add(True, name, why)
        except Exception:
            add(False, name, f"optional, needed for {why}")
    for name in ("VERSION", "config.example.yaml"):
        found = any(os.path.exists(os.path.join(d, name)) for d in {resource_dir, out_dir or resource_dir})
        ok = ok and found
        add(found, name)
    try:
        import zipcodes
        add(bool(zipcodes.matching("89434")), "ZIP code data (89434)")
    except Exception as exc:
        ok = False
        add(False, "ZIP code data", str(exc)[:60])
    try:
        from .panel_page import PAGE
        add(len(PAGE) > 50000 and "</html>" in PAGE.lower(), "control panel page")
    except Exception as exc:
        ok = False
        add(False, "control panel page", str(exc)[:60])
    try:
        with tempfile.TemporaryDirectory() as tmp:
            from .util import atomic_write_json
            atomic_write_json(os.path.join(tmp, "x.json"), {"a": 1})
        add(True, "can write files")
    except Exception as exc:
        ok = False
        add(False, "can write files", str(exc)[:60])
    lines.append("RESULT: " + ("all good" if ok else "something required is missing"))
    text = "\n".join(lines)
    print(text)
    try:
        with open(os.path.join(out_dir or resource_dir, "selftest.txt"), "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    except OSError:
        pass
    return ok
