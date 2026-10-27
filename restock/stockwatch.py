"""Stock timeline: how much each store gets, how often, and how fast it sells out.

Every check that shows a product in stock somewhere (a store's shelf, or online) opens or updates a "stock run" for that
product at that place: when it appeared, how many units were there at first and at most, and the count at each check
(stores that report counts: Target, CVS, Kroger levels). When a later check no longer shows it there, the run closes as
sold out, and its length is how long that place held stock. Runs are kept in data/stock-runs.jsonl for 180 days.

From those runs the Store rankings page works out, per store:
- allocation: units on the shelf when a restock lands (the first count seen), and the most seen at once
- how often it restocks (restocks a week) and on which days and hours
- how fast it sells out (the middle of its sell-out times), and units sold per hour where counts are known
- a priority score: expected units a week, weighted toward stores that sell out fast (go there first) and away from
  far ones

Timing honesty: a run's start and end are only as precise as the checks around them, so each run keeps its precision.
Runs whose start was not seen (already in stock the first time the product was checked) or whose start or end is
known only to within more than 90 minutes (a rarely checked product, or the app was off) are kept for allocation but
left out of sell-out times.
"""
from __future__ import annotations

import json
import os
import statistics
import threading
import time
from collections import Counter, defaultdict

from .history import DAY_NAMES, _hour_label
from .models import StockResult
from .util import atomic_write_json, read_json, replace_file

RUNS_FILE = "stock-runs.jsonl"
OPEN_FILE = "stock-open.json"
KEEP_DAYS = 180
MAX_PRECISION_S = 90 * 60   # a start or end known only to within more than this is not used for sell-out times
MAX_SAMPLES = 24
MIN_RUNS = 2                # a store needs this many timed runs before its sell-out time is shown in alerts


def _place_id(retailer: str, channel: str) -> str:
    return f"{retailer}|{channel}"


def fmt_minutes(m: float | None) -> str:
    if m is None:
        return "not known yet"
    if m < 1:
        return "under a minute"
    if m < 90:
        return f"{round(m)} min"
    if m < 48 * 60:
        return f"{m / 60:.1f} h".replace(".0 h", " h")
    return f"{m / 1440:.1f} days".replace(".0 days", " days")


class StockWatch:
    def __init__(self, data_dir: str):
        self.dir = data_dir
        self.path = os.path.join(data_dir, RUNS_FILE)
        self.open_path = os.path.join(data_dir, OPEN_FILE)
        self.lock = threading.Lock()
        self.runs: list[dict] = []
        self.open: dict[str, dict] = {}          # "retailer:product|channel" -> open run
        self.seen: dict[str, float] = {}         # product key -> last check (any result)
        self._load()

    # ---- storage --------------------------------------------------------------------------
    def _load(self) -> None:
        cutoff = time.time() - KEEP_DAYS * 86400
        lines = 0
        try:
            with open(self.path, encoding="utf-8") as fh:
                for line in fh:
                    lines += 1
                    try:
                        run = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(run, dict) and run.get("start", 0) >= cutoff:
                        self.runs.append(run)
        except OSError:
            pass
        if len(self.runs) < lines:
            try:
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    fh.write("".join(json.dumps(r) + "\n" for r in self.runs))
                replace_file(tmp, self.path)
            except OSError:
                pass
        saved = read_json(self.open_path, {}) or {}
        self.open = {k: v for k, v in (saved.get("open") or {}).items() if isinstance(v, dict)}
        self.seen = {k: float(v) for k, v in (saved.get("seen") or {}).items()}
        # Runs left open when the app closed stay open: the next check either finds the stock still there (the run goes
        # on) or gone (it closes, untimed if the app was off for long, since the end could be anywhere in that gap).

    def save(self) -> None:
        with self.lock:
            data = {"open": self.open, "seen": {k: v for k, v in self.seen.items() if time.time() - v < 30 * 86400}}
        try:
            atomic_write_json(self.open_path, data)
        except OSError:
            pass

    def _append(self, run: dict) -> None:
        self.runs.append(run)
        try:
            os.makedirs(self.dir, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(run) + "\n")
        except OSError:
            pass

    # ---- watching ---------------------------------------------------------------------------
    def observe(self, res: StockResult, now: float | None = None, first_look: bool = False) -> None:
        """One check of one product. Opens, updates and closes stock runs for it. first_look: the first check of
        this product since the app started, so stock already there did not just arrive."""
        now = now or time.time()
        key = res.key
        with self.lock:
            prev_check = self.seen.get(key)
            self.seen[key] = now
            here: dict[str, dict] = {}
            if res.online:
                here["online"] = {"place": f"{res.retailer_name} online", "qty": None, "level": "", "area": "",
                                  "dist": None, "addr": ""}
            for st in res.stores:
                here[f"store:{st.store_id}"] = {"place": st.name or f"Store {st.store_id}", "qty": st.qty,
                                                "level": st.level, "area": st.area, "dist": st.distance,
                                                "addr": st.address}
            # Places that had it and no longer do: sold out there. Store shelves only count as gone when this check
            # looked at them (some checks are online only).
            for okey in [k for k in self.open if k.startswith(key + "|") and k[len(key) + 1:] not in here
                         and (k.endswith("|online") or res.stores_checked)]:
                run = self.open[okey]
                self._close(okey, (run["last"] + now) / 2, timed=True, precision=now - run["last"])
            for ch, info in here.items():
                okey = f"{key}|{ch}"
                run = self.open.get(okey)
                q = info["qty"]
                if run is None:
                    seen_start = not first_look and prev_check is not None
                    self.open[okey] = {
                        "r": res.retailer, "rn": res.retailer_name, "k": key, "title": res.title[:100],
                        "type": res.type_label or "", "ch": ch, "place": info["place"], "area": info["area"],
                        "dist": info["dist"], "addr": info["addr"][:120],
                        "start": (prev_check + now) / 2 if seen_start else now,
                        "start_known": seen_start, "start_precision": (now - prev_check) if seen_start else None,
                        "last": now, "q0": q, "qmax": q, "qlast": q, "level0": info["level"],
                        "samples": [[round(now), q]] if q is not None else [], "price": res.price,
                    }
                else:
                    run["last"] = now
                    if q is not None:
                        run["q0"] = run["q0"] if run.get("q0") is not None else q
                        run["qmax"] = max(run.get("qmax") or 0, q)
                        if q != run.get("qlast"):
                            run["samples"] = (run.get("samples") or [])[-(MAX_SAMPLES - 1):] + [[round(now), q]]
                        run["qlast"] = q
                    if info["dist"] is not None:
                        run["dist"] = info["dist"]

    def _close(self, okey: str, end: float, timed: bool, precision: float | None = None) -> None:
        run = self.open.pop(okey, None)
        if run is None:
            return
        run["end"] = end
        run["end_known"] = timed
        run["end_precision"] = precision
        exact = (timed and run.get("start_known") and (precision or 0) <= MAX_PRECISION_S
                 and (run.get("start_precision") or 0) <= MAX_PRECISION_S)
        run["minutes"] = round((end - run["start"]) / 60, 1) if exact else None
        samples = run.get("samples") or []
        rate = None
        if len(samples) >= 2 and samples[-1][0] > samples[0][0] and samples[0][1] is not None:
            sold = (samples[0][1] or 0) - (samples[-1][1] or 0)
            if sold > 0:
                rate = round(sold / ((samples[-1][0] - samples[0][0]) / 3600), 1)
        run["per_hour"] = rate
        self._append(run)

    # ---- reading ------------------------------------------------------------------------------
    def _all_runs(self, since: float) -> list[dict]:
        with self.lock:
            done = [r for r in self.runs if r.get("start", 0) >= since]
            live = [dict(r, live=True) for r in self.open.values() if r.get("start", 0) >= since]
        return done + live

    def sellout_minutes(self, retailer: str, channel: str) -> tuple[float | None, int]:
        """(typical minutes this place stays in stock, timed runs it is based on)."""
        with self.lock:
            mins = [r["minutes"] for r in self.runs if r.get("r") == retailer and r.get("ch") == channel
                    and r.get("minutes") is not None]
        return (statistics.median(mins) if mins else None), len(mins)

    def hint(self, retailer: str, channel: str) -> str:
        m, n = self.sellout_minutes(retailer, channel)
        if m is None or n < MIN_RUNS:
            return ""
        return f"usually sold out in {fmt_minutes(m)}"

    def report(self, days: int = 60, area: str = "") -> dict:
        now = time.time()
        since = now - days * 86400
        runs = [r for r in self._all_runs(since) if not area or r.get("area") == area]
        places: dict[str, dict] = defaultdict(lambda: {"runs": [], "products": Counter(), "types": Counter()})
        for r in runs:
            p = places[_place_id(r["r"], r["ch"])]
            p["runs"].append(r)
            p["products"][r.get("title", "")] += 1
            if r.get("type"):
                p["types"][r["type"]] += 1
        span_weeks = max(1.0, (now - min((r["start"] for r in runs), default=now)) / (7 * 86400))
        rows = []
        for pid, p in places.items():
            rs = sorted(p["runs"], key=lambda r: r["start"])
            last = rs[-1]
            restocks = _restock_visits(rs)
            starts = [r["q0"] for r in rs if r.get("start_known") and r.get("q0") is not None]
            peaks = [r["qmax"] for r in rs if r.get("qmax") is not None]
            mins = [r["minutes"] for r in rs if r.get("minutes") is not None]
            rates = [r["per_hour"] for r in rs if r.get("per_hour")]
            per_restock_units = _units_per_visit(rs)
            hours = Counter(time.localtime(v)[3] for v in restocks)
            days_c = Counter(time.localtime(v)[6] for v in restocks)
            row = {
                "id": pid, "retailer": last["r"], "retailer_name": last["rn"], "place": last["place"],
                "online": last["ch"] == "online", "area": last.get("area", ""), "distance": last.get("dist"),
                "address": last.get("addr", ""),
                "restocks": len(restocks), "per_week": round(len(restocks) / span_weeks, 2),
                "runs": len(rs), "products": len(p["products"]),
                "top_products": [t for t, _ in p["products"].most_common(4)],
                "types": [t for t, _ in p["types"].most_common(4)],
                "units_first": round(statistics.median(starts), 1) if starts else None,
                "units_peak": max(peaks) if peaks else None,
                "units_per_restock": per_restock_units,
                "sellout_min": round(statistics.median(mins), 1) if mins else None,
                "sellout_fast": round(min(mins), 1) if mins else None,
                "timed": len(mins),
                "per_hour": round(statistics.median(rates), 1) if rates else None,
                "last_restock": max(restocks) if restocks else None,
                "in_stock_now": any(r.get("live") for r in rs),
                "usual_day": DAY_NAMES[days_c.most_common(1)[0][0]] if days_c else "",
                "usual_hour": _hour_label(hours.most_common(1)[0][0]) if hours else "",
            }
            rows.append(row)
        _score(rows)
        rows.sort(key=lambda x: -x["score"])
        live = sorted((dict(r, minutes_so_far=round((now - r["start"]) / 60)) for r in self.open_runs()
                       if not area or r.get("area") == area), key=lambda r: r["start"], reverse=True)
        return {"days": days, "rows": rows, "live": live[:40], "total_runs": len(runs),
                "areas": sorted({r.get("area") for r in self._all_runs(since) if r.get("area")}),
                "products": _by_product(runs)}

    def open_runs(self) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.open.values()]


def _restock_visits(rs: list[dict]) -> list[float]:
    """Start times of restocks at one place: runs starting within 2 hours of each other are one delivery."""
    out: list[float] = []
    for r in rs:
        if not r.get("start_known"):
            continue
        if out and r["start"] - out[-1] < 2 * 3600:
            continue
        out.append(r["start"])
    return out


def _units_per_visit(rs: list[dict]) -> float | None:
    """Typical units across all products in one delivery (first counts added up per delivery)."""
    visits: list[list[dict]] = []
    for r in rs:
        if not r.get("start_known") or r.get("q0") is None:
            continue
        if visits and r["start"] - visits[-1][0]["start"] < 2 * 3600:
            visits[-1].append(r)
        else:
            visits.append([r])
    totals = [sum(x["q0"] or 0 for x in v) for v in visits]
    return round(statistics.median(totals), 1) if totals else None


def _score(rows: list[dict]) -> None:
    """Priority 0 to 100: expected units a week (restocks a week times units each; one unit when the store gives
    no counts), worth more where stock goes fast (be there first), less the farther the store is."""
    raw = []
    for r in rows:
        units = r["units_per_restock"] or r["units_first"] or 1
        value = r["per_week"] * units
        speed = r["sellout_min"]
        urgency = 1.5 if speed is not None and speed <= 60 else 1.2 if speed is not None and speed <= 240 else 1.0
        far = r["distance"] if (r["distance"] is not None and not r["online"]) else 0
        value = value * urgency / (1 + far / 15)
        raw.append(value)
    top = max(raw, default=0) or 1
    for r, v in zip(rows, raw):
        r["score"] = round(100 * v / top)
        speed = r["sellout_min"]
        r["advice"] = ("Go first: sells out fast" if speed is not None and speed <= 60 and r["restocks"] >= 1 else
                       "Worth the trip: big deliveries" if (r["units_per_restock"] or 0) >= 6 else
                       "Stock lasts: no rush" if speed is not None and speed >= 24 * 60 else
                       "Not enough seen yet" if r["restocks"] < 2 else "")


def _by_product(runs: list[dict]) -> list[dict]:
    """Which places get each product, and how much."""
    out: dict[str, dict] = {}
    for r in runs:
        p = out.setdefault(r.get("title", ""), {"title": r.get("title", ""), "type": r.get("type", ""),
                                                "places": Counter(), "units": 0, "mins": []})
        p["places"][r.get("place", "")] += 1
        p["units"] += r.get("q0") or 0 if r.get("start_known") else 0
        if r.get("minutes") is not None:
            p["mins"].append(r["minutes"])
    rows = []
    for p in out.values():
        rows.append({"title": p["title"], "type": p["type"], "places": len(p["places"]),
                     "top_places": [n for n, _ in p["places"].most_common(5)], "units": p["units"],
                     "runs": sum(p["places"].values()),
                     "sellout_min": round(statistics.median(p["mins"]), 1) if p["mins"] else None})
    return sorted(rows, key=lambda x: -x["runs"])[:60]
