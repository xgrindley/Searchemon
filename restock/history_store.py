"""A small rolling history of how each store's checks went, kept on disk.

The trust table used to start from nothing every time the app opened, because it only knew about
checks made since launch. This keeps, per store, the outcomes of the last 40 checks plus hourly
totals for the last 7 days, in data/store-history.json (a few KB). It holds only counts and the
last problem text: no pages, no URLs, nothing about you.
"""
from __future__ import annotations

import os
import threading
import time

from .util import atomic_write_json, read_json

FILE = "store-history.json"
RECENT = 40
KEEP_HOURS = 24 * 7


class StoreHistory:
    def __init__(self, data_dir: str):
        self.path = os.path.join(data_dir, FILE)
        self.lock = threading.Lock()
        data = read_json(self.path, {}) or {}
        self.stores: dict[str, dict] = data.get("stores", {}) if isinstance(data, dict) else {}
        self._prune()

    @staticmethod
    def _hour(t: float) -> int:
        return int(t // 3600)

    def _row(self, store: str) -> dict:
        return self.stores.setdefault(store, {"recent": "", "hours": {}, "blocks": 0, "last_block": "", "last_block_t": 0,
                                              "last_ok": 0})

    def _prune(self) -> None:
        cutoff = self._hour(time.time()) - KEEP_HOURS
        for row in self.stores.values():
            row["hours"] = {h: v for h, v in (row.get("hours") or {}).items() if str(h).isdigit() and int(h) >= cutoff}

    def record(self, store: str, ok: bool, why: str = "", t: float | None = None) -> None:
        t = t or time.time()
        with self.lock:
            row = self._row(store)
            row["recent"] = (row["recent"] + ("1" if ok else "0"))[-RECENT:]
            b = row["hours"].setdefault(str(self._hour(t)), [0, 0])
            b[0 if ok else 1] += 1
            if ok:
                row["last_ok"] = round(t)
            elif why:
                row["blocks"] = int(row.get("blocks", 0)) + 1
                row["last_block"] = why[:160]
                row["last_block_t"] = round(t)

    def recent(self, store: str) -> list[int]:
        with self.lock:
            return [int(c) for c in self._row(store)["recent"]]

    def last_problem(self, store: str) -> tuple[str, float]:
        with self.lock:
            row = self._row(store)
            return row.get("last_block", ""), float(row.get("last_block_t") or 0)

    def last_ok(self, store: str) -> float:
        with self.lock:
            return float(self._row(store).get("last_ok") or 0)

    def window(self, store: str, hours: int) -> tuple[int, int]:
        """(good checks, failed checks) in the last `hours` hours."""
        floor = self._hour(time.time()) - hours + 1
        good = bad = 0
        with self.lock:
            for h, (g, b) in (self._row(store).get("hours") or {}).items():
                if int(h) >= floor:
                    good += g
                    bad += b
        return good, bad

    def save(self) -> None:
        with self.lock:
            self._prune()
            data = {"stores": {s: dict(r) for s, r in self.stores.items()}}
        try:
            atomic_write_json(self.path, data)
        except OSError:
            pass
