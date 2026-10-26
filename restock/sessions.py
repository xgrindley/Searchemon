"""Running tally of how long each checking method lasts before a site blocks it.

A "method" is how a page was loaded: plain requests ("direct"), or one of the
browser profiles (for example "edge", "chrome"). For every method and store the
tracker counts checks, blocks, the current clean streak, and how many checks
each past streak lasted before a block. It is saved to data/block-stats.json so
the numbers keep growing across restarts, and shown in the app.
"""
from __future__ import annotations

import os
import threading
import time

from .util import atomic_write_json, read_json

KEEP_STREAKS = 25


class BlockTracker:
    def __init__(self, data_dir: str):
        self.path = os.path.join(data_dir, "block-stats.json")
        self.lock = threading.Lock()
        self.data: dict = read_json(self.path, {})
        self.dirty = 0
        self.on_record = None          # optional callback(method, site, ok, kind), used for the daily history

    def record(self, method: str, site: str, ok: bool, kind: str = "") -> None:
        if self.on_record:
            try:
                self.on_record(method, site, ok, kind)
            except Exception:
                pass
        with self.lock:
            e = self.data.setdefault(method, {}).setdefault(site, {
                "checks": 0, "blocks": 0, "streak": 0, "streaks": [], "last_block": 0, "last_kind": ""})
            e["checks"] += 1
            if ok:
                e["streak"] += 1
            else:
                e["blocks"] += 1
                if e["streak"] or not e["streaks"] or e["streaks"][-1] != 0:
                    e["streaks"] = (e["streaks"] + [e["streak"]])[-KEEP_STREAKS:]
                e["streak"] = 0
                e["last_block"] = time.time()
                e["last_kind"] = kind
            self.dirty += 1
            flush = (not ok) or self.dirty >= 20
        if flush:
            self.save()

    def save(self) -> None:
        with self.lock:
            self.dirty = 0
            atomic_write_json(self.path, self.data)

    def rows(self) -> list[dict]:
        """One row per method and store, best average streak first within each store."""
        out = []
        with self.lock:
            for method, sites in self.data.items():
                for site, e in sites.items():
                    streaks = e["streaks"]
                    avg = sum(streaks) / len(streaks) if streaks else None
                    out.append({"method": method, "site": site, "checks": e["checks"], "blocks": e["blocks"],
                                "streak": e["streak"], "avg_before_block": avg,
                                "best": max(streaks + [e["streak"]]) if (streaks or e["streak"]) else 0,
                                "last_block": e["last_block"], "last_kind": e["last_kind"]})
        out.sort(key=lambda r: (r["site"], -(r["avg_before_block"] if r["avg_before_block"] is not None
                                              else r["streak"] + 1e6)))
        return out

    def report(self) -> str:
        rows = self.rows()
        if not rows:
            return "No checks recorded yet."
        lines = [f"{'store':<26}{'method':<12}{'checks':>7}{'blocks':>7}{'clean now':>10}{'avg to block':>14}{'best':>6}"]
        for r in rows:
            avg = f"{r['avg_before_block']:.0f}" if r["avg_before_block"] is not None else "never blocked"
            lines.append(f"{r['site'][:25]:<26}{r['method'][:11]:<12}{r['checks']:>7}{r['blocks']:>7}"
                         f"{r['streak']:>10}{avg:>14}{r['best']:>6}")
        return "\n".join(lines)
