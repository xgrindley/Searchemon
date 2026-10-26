"""Notification rules: what gets pushed to Discord and Windows, and when.

Checking and notifying are separate. A store can be checked (so its stock shows
on the dashboard and feeds restock times) without pushing alerts. These rules
decide, for each restock the monitor finds, whether to post and whether to ping.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from .history import in_window
from .models import StockResult

DEFAULTS = {
    "online": True,            # online restocks
    "in_store": True,          # shelf stock at nearby stores
    "pickup_only": False,      # in-store alerts only when order pickup works
    "max_miles": None,         # extra cap on store distance (None = your areas decide)
    "retailers": [],           # stores allowed to alert; empty = all
    "new_listings": True,
    "queue": True,
    "ping_on": ["restock", "queue"],   # which alerts mention your role/user: restock, queue, new_listing
    "quiet_hours": [],         # [{days, start, end}]
    "quiet_mode": "no_ping",   # no_ping: post silently; skip: don't post (still logged)
}


def rules(raw_cfg: dict) -> dict:
    out = dict(DEFAULTS)
    out.update({k: v for k, v in (raw_cfg.get("notify") or {}).items() if v is not None or k == "max_miles"})
    return out


@dataclass
class Decision:
    send: bool
    ping: bool
    new_online: bool
    store_ids: tuple[str, ...]
    why_not: str = ""


def quiet_now(r: dict, now: float | None = None) -> bool:
    lt = time.localtime(now or time.time())
    return any(in_window(w, lt) for w in r.get("quiet_hours") or [])


def decide(res: StockResult, new_online: bool, new_store_ids: tuple[str, ...], raw_cfg: dict,
           now: float | None = None) -> Decision:
    r = rules(raw_cfg)
    allowed = r.get("retailers") or []
    if allowed and res.retailer not in allowed:
        return Decision(False, False, False, (), f"{res.retailer_name} alerts are off")
    online = new_online and bool(r.get("online", True))
    by_id = {s.store_id: s for s in res.stores}
    stores = []
    if r.get("in_store", True):
        cap = r.get("max_miles")
        for sid in new_store_ids:
            st = by_id.get(sid)
            if st is None:
                continue
            if r.get("pickup_only") and not st.pickup:
                continue
            try:
                cap_mi = float(cap) if cap not in (None, "", 0) else None
            except (TypeError, ValueError):
                cap_mi = None
            if cap_mi and st.distance is not None and st.distance > cap_mi:
                continue
            stores.append(sid)
    if not online and not stores:
        why = "online alerts are off" if new_online and not new_store_ids else "no store matched your alert rules"
        return Decision(False, False, False, (), why)
    ping = "restock" in (r.get("ping_on") or [])
    if quiet_now(r, now):
        if r.get("quiet_mode") == "skip":
            return Decision(False, False, online, tuple(stores), "quiet hours")
        ping = False
    return Decision(True, ping, online, tuple(stores))


def allow_kind(kind: str, raw_cfg: dict, now: float | None = None) -> tuple[bool, bool]:
    """(send, ping) for new_listing / queue alerts."""
    r = rules(raw_cfg)
    key = {"new_listing": "new_listings", "queue": "queue"}[kind]
    if not r.get(key, True):
        return False, False
    ping = kind in (r.get("ping_on") or [])
    if quiet_now(r, now):
        if r.get("quiet_mode") == "skip":
            return False, False
        ping = False
    return True, ping
