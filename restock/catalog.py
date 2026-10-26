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
BOOST_FOR_S = 2 * 3600           # the same product at other stores is checked every cycle for a while after a restock


class Catalog:
    def __init__(self, data_dir: str):
        self.path = os.path.join(data_dir, "catalog.json")
        self.lock = threading.Lock()
        saved = read_json(self.path, {})
        self.items: dict[str, dict] = saved.get("items", {})
        self.runs: dict[str, float] = saved.get("runs", {})
        # Products you ignored, remembered by the product itself (barcode and name), not by one store's link, so the
        # choice holds at every store, survives restarts, and still applies when a store's link for it changes.
        self.rejected: dict[str, dict] = saved.get("rejected", {})
        self.cursor: dict[str, int] = {}
        changed = self.purge_non_tcg()
        with self.lock:
            # Ignores made before this was remembered per product: carry them over.
            for v in self.items.values():
                if v.get("status") == "ignored" and not self._is_rejected(v):
                    self._reject(v)
                    changed = True
        if changed:
            self.save()

    # ---- products you ignored -------------------------------------------------------------------
    @staticmethod
    def identities(v: dict) -> set[str]:
        """What makes a listing the same product at any store: its barcode, and its name."""
        out = set()
        if v.get("upc"):
            out.add("upc:" + str(v["upc"]))
        name = normalize_text(str(v.get("title") or "")).replace("pokemon trading card game", "pokemon tcg")
        if name:
            out.add("name:" + name)
        return out

    def _is_rejected(self, v: dict) -> bool:
        return any(i in self.rejected for i in self.identities(v))

    def _reject(self, v: dict) -> None:
        for i in self.identities(v):
            self.rejected[i] = {"title": str(v.get("title") or "")[:120], "at": time.time()}

    def is_rejected(self, v: dict) -> bool:
        with self.lock:
            return self._is_rejected(v)

    def purge_non_tcg(self) -> int:
        """Drop saved listings the classifier no longer accepts (for example a sticker book that an
        older version tracked as a collection box). Returns how many were removed."""
        with self.lock:
            drop = [k for k, v in self.items.items()
                    if not classify(str(v.get("title") or ""), allow_non_english=True).is_tcg]
            for k in drop:
                del self.items[k]
        return len(drop)

    def save(self) -> None:
        with self.lock:
            atomic_write_json(self.path, {"items": self.items, "runs": self.runs, "rejected": self.rejected})

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
                    if self._is_rejected(item):
                        item["status"] = "ignored"        # you ignored this product before (here or at another store)
                    elif not first_run:
                        new.append(item)
                item.update({"title": r.title, "last_seen": now, "price": r.price,
                             "type": c.type_key, "type_label": c.type_label, "msrp": c.msrp})
                if r.upc:
                    item["upc"] = normalize_upc(r.upc)
                if item.get("status") != "ignored" and self._is_rejected(item):
                    item["status"] = "ignored"
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

    def boost_siblings(self, res: StockResult) -> int:
        """A product just restocked somewhere: the first store to restock is unpredictable and others often follow
        within hours, so check the same product at the other stores every cycle for a while. Returns how many."""
        me = self.items.get(res.key)
        if me is None or not res.in_stock:
            return 0
        norm = lambda v: v.get("upc") or normalize_text(v["title"]).replace("pokemon trading card game", "pokemon tcg")
        mine, n = norm(me), 0
        until = time.time() + BOOST_FOR_S
        with self.lock:
            for key, v in self.items.items():
                if key != res.key and v["retailer"] != me["retailer"] and norm(v) == mine and v.get("status") != "ignored":
                    v["boost_until"] = until
                    n += 1
        return n

    def set_status(self, key: str, status: str) -> int:
        """Ignore or track a product. The choice covers the same product at every store and is remembered
        (catalog.json), so it holds after restarts and when the product is found again. Returns how many
        listings it changed."""
        changed = 0
        with self.lock:
            item = self.items.get(key)
            if item is None or status not in ("tracking", "ignored"):
                return 0
            mine = self.identities(item)
            if status == "ignored":
                self._reject(item)
            else:
                for i in mine:
                    self.rejected.pop(i, None)
            for v in self.items.values():
                if v is item or (mine & self.identities(v)):
                    if v.get("status") != status:
                        v["status"] = status
                        changed += 1
        self.save()
        return changed

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
        hot = [v for v in items if now - v.get("last_in_stock", 0) < HOT_FOR_S or v.get("boost_until", 0) > now]
        rest = [v for v in items if v not in hot]
        start = self.cursor.get(retailer, 0) % max(len(rest), 1)
        picked = (rest[start:] + rest[:start])[: max(0, n - len(hot))]
        self.cursor[retailer] = start + len(picked)
        return hot + picked

    def cross_queries(self, retailer: str, n: int) -> list[str]:
        """Search words for products found at other stores but not yet at this one: the UPC where known (a
        store's search usually jumps straight to that product), else the first words of the title. A different
        batch is returned each time, so over a few refreshes every product gets looked for."""
        wanted = []
        for g in self.groups():
            if any(l["retailer"] == retailer for l in g["listings"]):
                continue
            if all(l.get("status") == "ignored" for l in g["listings"]):
                continue
            first = next((l for l in g["listings"] if l.get("upc")), g["listings"][0])
            q = first.get("upc") or " ".join(str(g["title"]).split()[:9])
            if q and q not in wanted:
                wanted.append(q)
        if not wanted or n <= 0:
            return []
        start = self.cursor.get("x:" + retailer, 0) % len(wanted)
        picked = (wanted[start:] + wanted[:start])[:n]
        self.cursor["x:" + retailer] = start + len(picked)
        return picked

    def groups(self) -> list[dict]:
        """Listings of the same product across stores, matched by UPC, else by title."""
        groups: dict[str, dict] = {}
        for key, v in self.items.items():
            g = v.get("upc") or normalize_text(v["title"]).replace("pokemon trading card game", "pokemon tcg")
            entry = groups.setdefault(g, {"title": v["title"], "type_label": v.get("type_label", ""),
                                          "msrp": v.get("msrp"), "priority": v.get("priority", 9), "listings": []})
            entry["listings"].append({"key": key, **v})
        return sorted(groups.values(), key=lambda e: (e["priority"], e["title"]))
