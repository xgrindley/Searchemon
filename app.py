"""Pokemon restock monitor.

  python app.py                 open the desktop window (monitoring runs while it is open)
                                plus the control panel at http://127.0.0.1:8765
  python app.py --headless      run in this console instead of a window
  python app.py --once          check everything one time and print a table
  python app.py --resolve       look up retailer item ids for every UPC in the watchlist
  python app.py --test-discord  send a test message to each webhook
  python app.py --abtest        compare checking methods side by side (see which is blocked last)
  python app.py --stats         print the block tracker table
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import time


def base_dir() -> str:
    # When built into an .exe, keep config and data next to the .exe.
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def resource_dir() -> str:
    # Files bundled inside the .exe (VERSION, config.example.yaml) are unpacked here.
    return getattr(sys, "_MEIPASS", "") or base_dir()


def ensure_config(path: str) -> None:
    if os.path.exists(path):
        return
    for folder in (base_dir(), resource_dir()):
        example = os.path.join(folder, "config.example.yaml")
        if os.path.exists(example):
            shutil.copy(example, path)
            print(f"Created {path} from config.example.yaml. Fill it in, then run again.")
            return
    sys.exit(f"Missing {path}")


def log_crash() -> None:
    """A windowed .exe has no console, so an unexpected error is written next to it instead of vanishing."""
    import traceback
    try:
        os.makedirs(os.path.join(base_dir(), "data"), exist_ok=True)
        with open(os.path.join(base_dir(), "data", "crash.log"), "a", encoding="utf-8") as fh:
            fh.write(time.strftime("%Y-%m-%d %H:%M:%S") + "\n" + traceback.format_exc() + "\n")
    except OSError:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Pokemon TCG restock monitor")
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    parser.add_argument("--selftest", action="store_true", help="check that everything the program needs is present, then exit")
    parser.add_argument("--config", default=os.path.join(base_dir(), "config.yaml"))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--headless", action="store_true")
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--resolve", action="store_true")
    mode.add_argument("--test-discord", action="store_true")
    mode.add_argument("--abtest", action="store_true")
    mode.add_argument("--stats", action="store_true")
    parser.add_argument("--rounds", type=int, default=3, help="--abtest: passes over the page list")
    parser.add_argument("--delay", type=float, default=30, help="--abtest: seconds between loads per method")
    parser.add_argument("--url", action="append", default=[], help="--abtest: a page to test (repeatable)")
    args = parser.parse_args()
    if args.version:
        try:
            print(open(os.path.join(base_dir(), "VERSION")).read().strip())
        except OSError:
            print("unknown")
        return
    if args.selftest:
        from restock.selftest import run as selftest
        sys.exit(0 if selftest(resource_dir(), base_dir()) else 1)
    ensure_config(args.config)
    from restock import power
    power.apply(power.read_settings(args.config))

    if not (args.headless or args.once or args.resolve or args.test_discord
            or args.abtest or args.stats):
        from restock.gui import run_gui
        run_gui(args.config)
        return

    from restock.engine import Monitor
    mon = Monitor(args.config, console=True)

    if args.stats:
        print(mon.tracker.report() if mon.tracker else "No data yet.")
        return

    if args.abtest:
        from restock.abtest import Run, default_urls
        urls = args.url or default_urls(mon)
        if not urls:
            sys.exit("No pages to test. Add product links to the watchlist, or pass --url https://...")
        run = Run(mon, urls, args.rounds, args.delay)
        run.run()
        print("\n" + run.table())
        mon.close()
        return

    if args.test_discord:
        if not mon.notifier.enabled:
            sys.exit("No Discord webhook in config.yaml")
        for name, ok in mon.notifier.test().items():
            print(f"{name}: {'sent' if ok else 'FAILED'}")
        return

    if args.resolve:
        for w in mon.cfg.watchlist:
            if not w.upc:
                continue
            print(f"\n{w.name}  (UPC {w.upc})")
            for name in ("bestbuy", "target", "walmart", "kroger"):
                r = mon.retailers.get(name)
                if not r or not w.wants(name):
                    continue
                try:
                    print(f"  {r.display:10} {mon.resolve(r, w.upc) or 'not found'}")
                except Exception as exc:
                    print(f"  {r.display:10} lookup failed: {exc}")
        return

    if args.once:
        for res in mon.run_once():
            price = f"${res.price:.2f}" if res.price else "-"
            print(f"{res.retailer_name:12} {price:>8}  {(res.note or res.status_text())[:40]:40}  {res.title[:60]}")
        return

    from restock.shutdown import install as install_exit
    install_exit(mon.close, mon.log)
    mon.start()
    if (mon.cfg.raw.get("control_panel") or {}).get("enabled", True):
        from restock.panel import PanelServer
        PanelServer(mon).start()
    print("Monitoring. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        mon.close()


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        log_crash()
        raise
