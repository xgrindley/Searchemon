"""A rolling history of how each store's checks went, kept on disk.

The trust table used to start from nothing every time the app opened, because it only knew about
checks made since launch. This keeps, per store, the outcomes of the last 40 checks plus hourly
totals for the last 7 days, and one line per day for the last 180 days (checks that loaded, failed, time taken,
products checked, alerts sent), plus the same per-day counts for each checking method. It lives in
data/store-history.json (well under 200 KB). It holds only counts and the last problem text: no pages,
no URLs, nothing about you.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time

from .util import read_json

FILE = "store-history.json"
RECENT = 40
KEEP_HOURS = 24 * 7
KEEP_DAYS = 180


class StoreHistory:
    def __init__(self, data_dir: str):
        self.path = os.path.join(data_dir, FILE)
        self.lock = threading.Lock()
        data = read_json(self.path, {}) or {}
        self.stores: dict[str, dict] = data.get("stores", {}) if isinstance(data, dict) else {}
        self.methods: dict[str, dict] = data.get("methods", {}) if isinstance(data, dict) else {}
        self._prune()

    @staticmethod
    def _hour(t: float) -> int:
        return int(t // 3600)

    @staticmethod
    def _day(t: float) -> str:
        return time.strftime("%Y%m%d", time.localtime(t))

    def _row(self, store: str) -> dict:
        row = self.stores.setdefault(store, {"recent": "", "hours": {}, "blocks": 0, "last_block": "", "last_block_t": 0,
                                             "last_ok": 0})
        row.setdefault("days", {})
        return row

    def _prune(self) -> None:
        cutoff = self._hour(time.time()) - KEEP_HOURS
        day_cut = self._day(time.time() - KEEP_DAYS * 86400)
        for row in self.stores.values():
            row["hours"] = {h: v for h, v in (row.get("hours") or {}).items() if str(h).isdigit() and int(h) >= cutoff}
            row["days"] = {d: v for d, v in (row.get("days") or {}).items() if str(d) >= day_cut}
        for m, days in list(self.methods.items()):
            self.methods[m] = {d: v for d, v in days.items() if str(d) >= day_cut}
            if not self.methods[m]:
                del self.methods[m]

    @staticmethod
    def _dayrow(row: dict, day: str) -> list:
        return row["days"].setdefault(day, [0, 0, 0, 0, 0, 0])      # ok, failed, ms total, timed, products, alerts

    def record(self, store: str, ok: bool, why: str = "", t: float | None = None, ms: float | None = None,
               products: int = 0) -> None:
        t = t or time.time()
        with self.lock:
            row = self._row(store)
            d = self._dayrow(row, self._day(t))
            d[0 if ok else 1] += 1
            if ms is not None:
                d[2] += int(ms)
                d[3] += 1
            d[4] += int(products)
            row["recent"] = (row["recent"] + ("1" if ok else "0"))[-RECENT:]
            b = row["hours"].setdefault(str(self._hour(t)), [0, 0])
            b[0 if ok else 1] += 1
            if ok:
                row["last_ok"] = round(t)
            elif why:
                row["blocks"] = int(row.get("blocks", 0)) + 1
                row["last_block"] = why[:160]
                row["last_block_t"] = round(t)

    def note_alert(self, store: str, t: float | None = None) -> None:
        with self.lock:
            self._dayrow(self._row(store), self._day(t or time.time()))[5] += 1

    def record_method(self, method: str, ok: bool, t: float | None = None) -> None:
        with self.lock:
            d = self.methods.setdefault(method, {}).setdefault(self._day(t or time.time()), [0, 0])
            d[0 if ok else 1] += 1

    def days(self, store: str, n: int = 30) -> list[dict]:
        """The last n days for a store, oldest first, with empty days included so charts line up."""
        out = []
        with self.lock:
            rows = self._row(store)["days"]
            for i in range(n - 1, -1, -1):
                day = self._day(time.time() - i * 86400)
                ok, bad, ms, timed, prod, alerts = rows.get(day, [0, 0, 0, 0, 0, 0])
                out.append({"day": day, "ok": ok, "fail": bad, "ms": round(ms / timed) if timed else None,
                            "products": prod, "alerts": alerts})
        return out

    def totals(self, store: str) -> dict:
        ok = bad = ms = timed = prod = alerts = 0
        first = ""
        with self.lock:
            for day, v in sorted(self._row(store)["days"].items()):
                first = first or day
                ok += v[0]; bad += v[1]; ms += v[2]; timed += v[3]; prod += v[4]; alerts += v[5]
        n = ok + bad
        return {"checks": n, "ok": ok, "fail": bad, "success": round(100 * ok / n) if n else None,
                "avg_ms": round(ms / timed) if timed else None, "products": prod, "alerts": alerts, "since": first}

    def method_days(self, n: int = 14) -> list[dict]:
        out = []
        with self.lock:
            for m, days in sorted(self.methods.items()):
                series = []
                for i in range(n - 1, -1, -1):
                    series.append(days.get(self._day(time.time() - i * 86400), [0, 0]))
                ok = sum(x[0] for x in days.values()); bad = sum(x[1] for x in days.values())
                out.append({"method": m, "days": series, "checks": ok + bad, "fail": bad})
        return out

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
            data = {"stores": {s: dict(r) for s, r in self.stores.items()}, "methods": self.methods}
        try:                                   # compact on purpose: this file grows with the days kept
            folder = os.path.dirname(os.path.abspath(self.path))
            os.makedirs(folder, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, separators=(",", ":"))
            os.replace(tmp, self.path)
        except OSError:
            pass
