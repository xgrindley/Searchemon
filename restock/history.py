"""Restock history and timing.

Every real restock the monitor sees (an item going from unavailable to
available, online or at a specific store) is written to data/history.jsonl.
From that it works out when each store tends to restock, which drives two
things: the "Restock times" view in the control panel, and checking more often
during the hours restocks have happened before.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import Counter, defaultdict

from .models import StockResult, StoreStock
from .util import replace_file

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_DAY_KEYS = {d.lower(): i for i, d in enumerate(DAY_NAMES)}
KEEP_DAYS = 180
SAME_VISIT_S = 2 * 3600   # several items appearing at one store within 2h = one restock


def _hour_label(h: int) -> str:
    h %= 24
    return f"{(h % 12) or 12} {'AM' if h < 12 else 'PM'}"


class History:
    def __init__(self, data_dir: str):
        self.path = os.path.join(data_dir, "history.jsonl")
        self.lock = threading.Lock()
        self.events: list[dict] = []
        self._load()

    def _load(self) -> None:
        cutoff = time.time() - KEEP_DAYS * 86400
        lines = 0
        try:
            with open(self.path, encoding="utf-8") as fh:
                for line in fh:
                    lines += 1
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    if ev.get("t", 0) >= cutoff:
                        self.events.append(ev)
        except OSError:
            return
        # Rewrite without expired lines once in a while so the file stays small.
        if len(self.events) < lines:
            try:
                text = "".join(json.dumps(ev) + "\n" for ev in self.events)
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    fh.write(text)
                replace_file(tmp, self.path)
            except OSError:
                pass        # tidying is optional; the app must start regardless

    def record(self, res: StockResult, store: StoreStock | None, when: float | None = None) -> None:
        ev = {
            "t": when or time.time(),
            "r": res.retailer,
            "rn": res.retailer_name,
            "k": res.key,
            "title": res.title[:100],
            "ch": f"store:{store.store_id}" if store else "online",
            "place": (store.name or f"Store {store.store_id}") if store else f"{res.retailer_name} online",
            "q": store.qty if store else None,
            "pickup": store.pickup if store else None,
            "p": res.price,
        }
        with self.lock:
            self.events.append(ev)
            try:                 # the restock-time record is nice to have; it must never stop an alert
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(ev) + "\n")
            except OSError:
                pass

    # ---- analysis -------------------------------------------------------------
    def visits(self, retailer: str | None = None, place: str | None = None) -> list[dict]:
        """Restock events grouped so one truck/vendor visit counts once per place."""
        with self.lock:
            evs = sorted(self.events, key=lambda e: e["t"])
        out: list[dict] = []
        last: dict[str, dict] = {}
        for ev in evs:
            if retailer and ev["r"] != retailer:
                continue
            pid = f'{ev["r"]}|{ev["ch"]}'
            if place and pid != place:
                continue
            prev = last.get(pid)
            if prev and ev["t"] - prev["t"] < SAME_VISIT_S:
                prev["items"].add(ev["title"])
                continue
            visit = {"t": ev["t"], "r": ev["r"], "rn": ev["rn"], "place": ev["place"], "pid": pid,
                     "items": {ev["title"]}, "pickup": ev.get("pickup")}
            last[pid] = visit
            out.append(visit)
        return out

    def patterns(self, retailer: str | None = None, place: str | None = None) -> dict:
        visits = self.visits(retailer, place)
        grid = [[0] * 24 for _ in range(7)]
        for v in visits:
            lt = time.localtime(v["t"])
            grid[lt.tm_wday][lt.tm_hour] += 1

        # Best 2-hour windows across the week.
        windows = []
        for d in range(7):
            for hr in range(24):
                n = grid[d][hr] + grid[d][(hr + 1) % 24]
                if n:
                    windows.append((n, d, hr))
        windows.sort(reverse=True)
        best, used = [], set()
        for n, d, hr in windows:
            if (d, hr) in used or (d, (hr + 1) % 24) in used or (d, (hr - 1) % 24) in used:
                continue
            used.update({(d, hr), (d, (hr + 1) % 24)})
            best.append({"day": DAY_NAMES[d], "label": f"{DAY_NAMES[d]} {_hour_label(hr)} to {_hour_label(hr + 2)}",
                         "count": n})
            if len(best) == 5:
                break

        days = Counter(time.localtime(v["t"]).tm_wday for v in visits)
        places = defaultdict(lambda: {"count": 0, "last": 0, "name": "", "retailer": ""})
        for v in self.visits(retailer):
            p = places[v["pid"]]
            p["count"] += 1
            p["last"] = max(p["last"], v["t"])
            p["name"], p["retailer"] = v["place"], v["rn"]
        return {
            "total": len(visits),
            "grid": grid,
            "best": best,
            "by_day": [days.get(i, 0) for i in range(7)],
            "places": sorted(({"id": k, **v} for k, v in places.items()), key=lambda x: -x["count"]),
            "recent": [{"t": v["t"], "retailer": v["rn"], "place": v["place"], "items": sorted(v["items"])[:6],
                        "pickup": v["pickup"]} for v in reversed(visits[-40:])],
        }

    def likely_now(self, retailer: str, now: float | None = None, spread_h: int = 1, min_visits: int = 2) -> bool:
        """True if this retailer has restocked at least min_visits times near this weekday and hour."""
        lt = time.localtime(now or time.time())
        here = lt.tm_wday * 24 + lt.tm_hour
        n = 0
        for v in self.visits(retailer):
            t = time.localtime(v["t"])
            slot = t.tm_wday * 24 + t.tm_hour
            diff = min((slot - here) % 168, (here - slot) % 168)
            if diff <= spread_h:
                n += 1
        return n >= min_visits


def _parse_days(value) -> set[int]:
    """Weekday numbers (Monday 0) from "all", "weekdays", "weekend", "mon-fri", "sat,sun" or a list of those.
    Text that names no day at all counts as every day, so a typo never silently turns a window off."""
    if value in (None, "", "all", ["all"]):
        return set(range(7))
    if isinstance(value, str):
        items = [p for p in value.replace(";", ",").replace(" ", ",").split(",") if p]
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        items = [value]
    out: set[int] = set()
    for item in items:
        text = str(item).strip().lower()
        if "-" in text:                                    # a range such as mon-fri or fri-mon
            a, _, b = text.partition("-")
            if a[:3] in _DAY_KEYS and b[:3] in _DAY_KEYS:
                d, last = _DAY_KEYS[a[:3]], _DAY_KEYS[b[:3]]
                out.add(d)
                while d != last:
                    d = (d + 1) % 7
                    out.add(d)
                continue
        key = text[:3]
        if text.startswith("weekday"):
            out.update(range(5))
        elif text.startswith("weekend"):
            out.update({5, 6})
        elif key in ("all", "dai", "eve"):
            out.update(range(7))
        elif key in _DAY_KEYS:
            out.add(_DAY_KEYS[key])
    return out or set(range(7))


def _minutes(hhmm) -> int:
    """Minutes after midnight from "22:00", "7:30", "10pm", "10:30 PM" or 22. A bare 22:00 typed into
    config.yaml without quotes arrives as the number 1320 (YAML reads it as minutes), which is handled too.
    Anything unreadable counts as midnight rather than stopping alerts."""
    if isinstance(hhmm, bool):
        return 0
    if isinstance(hhmm, (int, float)):
        v = int(hhmm)
        return (v % 24) * 60 if 0 <= v < 24 else v % 1440
    text = str(hhmm or "0").strip().lower().replace(".", "")
    pm, am = text.endswith(("pm", "p")), text.endswith(("am", "a"))
    text = text.rstrip("apm ").strip()
    h, _, m = text.partition(":")
    try:
        hour, minute = int(h or 0), int(m or 0)
    except ValueError:
        return 0
    if pm and hour < 12:
        hour += 12
    if am and hour == 12:
        hour = 0
    return (hour % 24) * 60 + max(0, min(minute, 59))


def in_window(window: dict, lt: time.struct_time) -> bool:
    if not isinstance(window, dict):
        return False
    start, end = _minutes(window.get("start", "0:00")), _minutes(window.get("end", "0:00"))
    now_m = lt.tm_hour * 60 + lt.tm_min
    days = _parse_days(window.get("days"))
    if start <= end:
        return lt.tm_wday in days and start <= now_m < end
    # Crosses midnight: the early-morning half belongs to the previous day's window.
    if now_m >= start:
        return lt.tm_wday in days
    return now_m < end and (lt.tm_wday - 1) % 7 in days


class Schedule:
    """How much faster or slower to check right now."""

    def __init__(self, raw_cfg: dict, history: History):
        self.cfg = raw_cfg.get("schedule") or {}
        self.history = history

    def factor(self, retailer: str, now: float | None = None) -> tuple[float, str]:
        lt = time.localtime(now or time.time())
        fast = float(self.cfg.get("fast_factor") or 0.5)
        slow = float(self.cfg.get("slow_factor") or 3)
        if any(in_window(w, lt) for w in self.cfg.get("fast_windows") or []):
            return fast, "busy window"
        if self.cfg.get("learn_from_history", True) and self.history.likely_now(retailer, now):
            return fast, "usual restock time"
        if any(in_window(w, lt) for w in self.cfg.get("slow_windows") or []):
            return slow, "quiet hours"
        return 1.0, ""

    @property
    def min_interval(self) -> float:
        return float(self.cfg.get("min_interval_seconds") or 30)
