"""Marketplace sellers that price-gouge, blocked by what they actually charge.

Stores such as Walmart, Amazon and Books-A-Million also list items from other sellers, and those often ask double
MSRP or more. Each time a check shows a third-party seller's price next to a known MSRP, the offer is recorded.
A seller is blocked automatically when, over its recent offers, nearly all of them are past your price limit and
the typical markup is large. The decision is recomputed with every new offer, so a seller that starts pricing
fairly is let through again without you doing anything. You can also block or allow a seller by hand, which
always wins. Nothing here touches the stores' own listings.
"""
from __future__ import annotations

import os
import statistics
import threading
import time

from .util import atomic_write_json, normalize_text, read_json

KEEP = 20                         # most recent offers kept per seller
WINDOW_S = 30 * 86400             # offers older than this no longer count
MIN_OFFERS = 3                    # never judged on fewer offers than this
OVER_SHARE = 0.8                  # blocked when at least this share of offers is over your limit...
MIN_MARKUP = 0.25                 # ...and the typical (median) price is at least this much over MSRP


class SellerWatch:
    def __init__(self, data_dir: str):
        self.path = os.path.join(data_dir, "sellers.json")
        self.lock = threading.Lock()
        self.data: dict[str, dict] = read_json(self.path, {}).get("sellers", {})
        self.dirty = False

    @staticmethod
    def key(retailer: str, seller: str) -> str:
        return f"{retailer}|{normalize_text(seller)}"

    def record(self, retailer: str, seller: str, price: float | None, msrp: float | None, limit: float | None,
               title: str = "") -> None:
        """One offer by a third-party seller. limit is your highest allowed price for it (MSRP plus your allowance)."""
        if not (seller and price and msrp and limit):
            return
        k = self.key(retailer, seller)
        now = time.time()
        with self.lock:
            row = self.data.setdefault(k, {"name": seller.strip()[:80], "retailer": retailer, "offers": [], "mode": "auto"})
            row["offers"] = [o for o in row["offers"] if now - o["t"] < WINDOW_S][-(KEEP - 1):] + [{
                "t": now, "price": round(float(price), 2), "markup": round(float(price) / float(msrp) - 1, 3),
                "over": float(price) > float(limit) + 0.01, "title": title[:80]}]
            self.dirty = True

    def verdict(self, row: dict) -> tuple[bool, str]:
        """(blocked, why) for one seller."""
        mode = row.get("mode", "auto")
        if mode == "block":
            return True, "blocked by you"
        if mode == "allow":
            return False, "allowed by you"
        now = time.time()
        offers = [o for o in row.get("offers", []) if now - o["t"] < WINDOW_S]
        if len(offers) < MIN_OFFERS:
            return False, f"watching ({len(offers)} of {MIN_OFFERS} offers seen)"
        over = sum(1 for o in offers if o["over"]) / len(offers)
        median = statistics.median(o["markup"] for o in offers)
        if over >= OVER_SHARE and median >= MIN_MARKUP:
            return True, f"{round(over * 100)}% of {len(offers)} offers over your limit, typically {round(median * 100)}% over MSRP"
        return False, f"{round(over * 100)}% of {len(offers)} offers over your limit, typically {median * 100:+.0f}% vs MSRP"

    def blocked(self, retailer: str, seller: str | None) -> tuple[bool, str]:
        if not seller:
            return False, ""
        with self.lock:
            row = self.data.get(self.key(retailer, seller))
            return self.verdict(row) if row else (False, "")

    def set_mode(self, key: str, mode: str) -> bool:
        if mode not in ("auto", "block", "allow"):
            return False
        with self.lock:
            if key not in self.data:
                return False
            self.data[key]["mode"] = mode
            self.dirty = True
        self.save()
        return True

    def rows(self) -> list[dict]:
        with self.lock:
            out = []
            for k, row in self.data.items():
                blocked, why = self.verdict(row)
                offers = row.get("offers", [])
                out.append({"key": k, "name": row.get("name", ""), "retailer": row.get("retailer", ""), "mode": row.get("mode", "auto"),
                            "blocked": blocked, "why": why, "offers": len(offers),
                            "last": offers[-1] if offers else None})
        return sorted(out, key=lambda r: (not r["blocked"], r["retailer"], r["name"].lower()))

    def save(self) -> None:
        with self.lock:
            if not self.dirty:
                return
            try:
                atomic_write_json(self.path, {"sellers": self.data})
                self.dirty = False
            except OSError:
                pass
