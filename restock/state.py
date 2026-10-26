"""Remembers the last seen stock per product so alerts fire on changes, not every poll."""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass

from .models import StockResult
from .util import atomic_write_json, read_json


@dataclass
class Change:
    alert: bool
    reason: str = ""
    new_online: bool = False
    new_store_ids: tuple[str, ...] = ()
    sold_out: bool = False
    first_look: bool = False                 # first time this item was seen since the app started
    raw_new_online: bool = False             # real transitions before the quiet period is applied
    raw_new_store_ids: tuple[str, ...] = ()


class StateStore:
    def __init__(self, data_dir: str):
        self.path = os.path.join(data_dir, "state.json")
        self.lock = threading.Lock()
        self.data: dict = read_json(self.path, {})
        self.session_seen: set[str] = set()

    def evaluate(self, res: StockResult, cooldown_s: float, alert_on_startup: bool) -> Change:
        now = time.time()
        with self.lock:
            prev = self.data.get(res.key)
            first_this_run = res.key not in self.session_seen
            self.session_seen.add(res.key)

            if prev is None or first_this_run:
                # On the first look each run, treat everything as "previously out of stock"
                # when alert_on_startup is on, so you hear about what is already available.
                prev_online = False if alert_on_startup else res.online
                prev_stores = set() if alert_on_startup else {s.store_id for s in res.stores}
                last_alerts = (prev or {}).get("alerts", {})
            else:
                prev_online = bool(prev.get("online"))
                prev_stores = set(prev.get("stores", []))
                last_alerts = prev.get("alerts", {})

            cur_stores = {s.store_id for s in res.stores}
            new_online = res.online and not prev_online
            new_stores = cur_stores - prev_stores
            raw_online, raw_stores = new_online, tuple(sorted(new_stores))
            sold_out = bool(prev) and not first_this_run and prev_online and not res.online

            def cooled(channel: str) -> bool:
                return now - float(last_alerts.get(channel, 0)) >= cooldown_s

            new_online = new_online and cooled("online")
            new_stores = {s for s in new_stores if cooled(f"store:{s}")}

            self.data[res.key] = {
                "online": res.online,
                "stores": sorted(cur_stores),
                "alerts": last_alerts,
                "title": res.title[:120],
                "checked": now,
            }
            reason = []
            if new_online:
                reason.append("online restock")
            if new_stores:
                reason.append(f"in stock at {len(new_stores)} new store(s)")
            return Change(bool(new_online or new_stores), ", ".join(reason),
                          new_online, tuple(sorted(new_stores)), sold_out,
                          first_this_run, raw_online, raw_stores)

    def would_alert(self, res: StockResult) -> bool:
        """True if this result shows stock that was not there last time (no state change)."""
        with self.lock:
            prev = self.data.get(res.key)
            if prev is None or res.key not in self.session_seen:
                return res.in_stock
            new_online = res.online and not prev.get("online")
            new_stores = {s.store_id for s in res.stores} - set(prev.get("stores", []))
            return bool(new_online or new_stores)

    def mark_alerted(self, res: StockResult, change: Change) -> None:
        now = time.time()
        with self.lock:
            entry = self.data.setdefault(res.key, {"alerts": {}})
            alerts = entry.setdefault("alerts", {})
            if change.new_online:
                alerts["online"] = now
            for s in change.new_store_ids:
                alerts[f"store:{s}"] = now

    def undo_alert(self, res: StockResult, change: Change, max_retries: int = 6) -> bool:
        """The alert could not be delivered: forget that this stock was seen so the next
        check tries again. Gives up after max_retries so a dead webhook cannot loop forever."""
        with self.lock:
            entry = self.data.get(res.key)
            if entry is None:
                return False
            tries = int(entry.get("send_failures", 0)) + 1
            if tries > max_retries:
                entry["send_failures"] = 0
                return False
            entry["send_failures"] = tries
            if change.new_online:
                entry["online"] = False
            entry["stores"] = sorted(set(entry.get("stores", [])) - set(change.new_store_ids))
            return True

    def clear_failures(self, res: StockResult) -> None:
        with self.lock:
            entry = self.data.get(res.key)
            if entry and entry.get("send_failures"):
                entry["send_failures"] = 0

    def save(self) -> None:
        with self.lock:
            # Forget products not seen for 30 days so the file stays small.
            cutoff = time.time() - 30 * 86400
            self.data = {k: v for k, v in self.data.items() if v.get("checked", 0) > cutoff}
            atomic_write_json(self.path, self.data)
