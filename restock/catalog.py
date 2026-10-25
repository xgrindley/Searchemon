"""Products the monitor found on its own.

Every few hours it searches each discovery store for Pokemon cards, keeps the
listings the classifier recognizes as sealed product, and tracks them like
products you added yourself. A listing it has never seen before can trigger a
"new listing" alert, often the first sign of a coming release or restock.
"""
from __future__ import annotations

import os
import threading
import time

from .models import StockResult
from .tcg import classify, type_settings
from .util import atomic_write_json, normalize_text, normalize_upc, read_json

FORGET_AFTER_S = 21 * 86400      # a listing not seen in searches for 3 weeks is dropped
HOT_FOR_S = 6 * 3600             # an item seen in stock recently is checked every cycle


class Catalog:
    def __init__(self, data_dir: str):
        self.path = os.path.join(data_dir, "catalog.json")
        self.lock = threading.Lock()
        saved = read_json(self.path, {})
        self.items: dict[str, dict] = saved.get("items", {})
        self.runs: dict[str, float] = saved.get("runs", {})
        self.cursor: dict[str, int] = {}

    def save(self) -> None:
        with self.lock:
            atomic_write_json(self.path, {"items": self.items, "runs": self.runs})

    def due(self, retailer: str, hours: float) -> bool:
        return time.time() - self.runs.get(retailer, 0) >= hours * 3600

    def seeded(self, retailer: str) -> bool:
        return retailer in self.runs

    def merge(self, retailer: str, results: list[StockResult], raw_cfg: dict, mark_run: bool) -> list[dict]:
        """Add classified listings. Returns the ones never seen before (empty on the very first run)."""
        allow_other_lang = bool((raw_cfg.get("settings") or {}).get("allow_non_english"))
        types = type_settings(raw_cfg)
        overrides = {k: v["msrp"] for k, v in types.items()}
        now = time.time()
        first_run = not self.seeded(retailer)
        new = []
        with self.lock:
            for r in results:
                c = classify(r.title, allow_non_english=allow_other_lang, msrp_overrides=overrides)
                if not c.is_tcg or r.third_party:
                    continue
                key = f"{retailer}:{r.product_id}"
                item = self.items.get(key)
                if item is None:
                    item = {"retailer": retailer, "retailer_name": r.retailer_name, "id": r.product_id,
                            "title": r.title, "url": r.url, "type": c.type_key, "type_label": c.type_label,
                            "msrp": c.msrp, "priority": c.priority, "upc": normalize_upc(r.upc) or "",
                            "first_seen": now, "status": "tracking", "last_in_stock": 0}
                    self.items[key] = item
                    if not first_run:
                        new.append(item)
                item.update({"title": r.title, "last_seen": now, "price": r.price,
                             "type": c.type_key, "type_label": c.type_label, "msrp": c.msrp})
                if r.upc:
                    item["upc"] = normalize_upc(r.upc)
            for key in [k for k, v in self.items.items() if v["retailer"] == retailer
                        and v.get("status") != "ignored" and now - v.get("last_seen", now) > FORGET_AFTER_S]:
                del self.items[key]
            if mark_run:
                self.runs[retailer] = now
        self.save()
        return new

    def note_stock(self, res: StockResult) -> None:
        item = self.items.get(res.key)
        if item is not None:
            if res.in_stock:
                item["last_in_stock"] = time.time()
            item["price"] = res.price if res.price is not None else item.get("price")
            item["status_text"] = res.status_text()

    def set_status(self, key: str, status: str) -> None:
        with self.lock:
            if key in self.items and status in ("tracking", "ignored"):
                self.items[key]["status"] = status
        self.save()

    def tracked(self, retailer: str, types: dict) -> list[dict]:
        out = []
        for v in self.items.values():
            if v["retailer"] != retailer or v.get("status") == "ignored":
                continue
            if not types.get(v.get("type") or "other", {}).get("alert", True):
                continue
            out.append(v)
        return out

    def rotation(self, retailer: str, n: int, types: dict) -> list[dict]:
        """Recently in-stock items every cycle, plus the next n others round-robin, most wanted types first."""
        items = sorted(self.tracked(retailer, types), key=lambda v: (v.get("priority", 9), v["title"]))
        if n <= 0 or not items:
            return []
        now = time.time()
        hot = [v for v in items if now - v.get("last_in_stock", 0) < HOT_FOR_S]
        rest = [v for v in items if v not in hot]
        start = self.cursor.get(retailer, 0) % max(len(rest), 1)
        picked = (rest[start:] + rest[:start])[: max(0, n - len(hot))]
        self.cursor[retailer] = start + len(picked)
        return hot + picked

    def groups(self) -> list[dict]:
        """Listings of the same product across stores, matched by UPC, else by title."""
        groups: dict[str, dict] = {}
        for key, v in self.items.items():
            g = v.get("upc") or normalize_text(v["title"]).replace("pokemon trading card game", "pokemon tcg")
            entry = groups.setdefault(g, {"title": v["title"], "type_label": v.get("type_label", ""),
                                          "msrp": v.get("msrp"), "priority": v.get("priority", 9), "listings": []})
            entry["listings"].append({"key": key, **v})
        return sorted(groups.values(), key=lambda e: (e["priority"], e["title"]))
