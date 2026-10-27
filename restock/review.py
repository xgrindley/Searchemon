"""Products to review: Pokemon things the monitor found but did not treat as card product (t-shirts, model kits,
plush, books...), so you can see what it skipped and decide.

- Each one is listed once on the control panel (Products > To review) and, if you add a "review" webhook, posted to that
  Discord channel with two links: Accept and Mute.
- Accept: the monitor tracks it like a card product from then on (Found for you, stock checks, alerts).
- Mute: it is never listed or posted again.
- Your choices are saved on this PC in data/review.json. The links in Discord point at this PC's control panel. Each
  link carries a code that only works for that one product and that one choice, so a link cannot be changed into
  anything else; a link from Discord works from any device that can reach the panel (this PC, or your phone on home
  Wi-Fi with phone access on).
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time

from .util import atomic_write_json, normalize_text, read_json

FILE = "review.json"
KEEP = 600
ACTIONS = ("accept", "mute", "undo")


def review_id(title: str) -> str:
    """The same product found at several stores (or found again) gets the same id."""
    t = normalize_text(title).replace("pokemon trading card game", "pokemon tcg")
    return hashlib.sha1(t.encode()).hexdigest()[:12]


class ReviewQueue:
    def __init__(self, data_dir: str):
        self.path = os.path.join(data_dir, FILE)
        self.lock = threading.Lock()
        d = read_json(self.path, {}) or {}
        self.items: dict[str, dict] = {k: v for k, v in (d.get("items") or {}).items() if isinstance(v, dict)}
        self.secret: str = str(d.get("secret") or "") or secrets.token_hex(16)
        if not d.get("secret"):
            self.save()

    # ---- recording ------------------------------------------------------------------------------
    def add(self, retailer: str, store: str, title: str, url: str, reason: str, price: float | None = None) -> dict | None:
        """Note a skipped product. Returns the entry when it is new (worth posting), else None."""
        rid = review_id(title)
        now = time.time()
        with self.lock:
            item = self.items.get(rid)
            if item is not None:
                item["last_seen"] = now
                stores = item.setdefault("stores", {})
                if retailer not in stores:
                    stores[retailer] = {"name": store, "url": url, "price": price}
                return None
            item = {"id": rid, "title": title[:200], "reason": reason, "status": "pending", "first_seen": now,
                    "last_seen": now, "stores": {retailer: {"name": store, "url": url, "price": price}}}
            self.items[rid] = item
            if len(self.items) > KEEP:
                for k, _ in sorted(((k, v.get("last_seen", 0)) for k, v in self.items.items()
                                    if v.get("status") == "pending"), key=lambda x: x[1])[: len(self.items) - KEEP]:
                    self.items.pop(k, None)
        return dict(item)

    def decide(self, rid: str, action: str) -> tuple[bool, str]:
        if action not in ACTIONS:
            return False, "Unknown choice."
        with self.lock:
            item = self.items.get(rid)
            if item is None:
                return False, "That product is no longer in the list."
            item["status"] = {"accept": "accepted", "mute": "muted", "undo": "pending"}[action]
            item["decided"] = time.time()
            title = item["title"]
        self.save()
        return True, {"accept": f"Accepted: {title}. It is tracked like a card product from now on.",
                      "mute": f"Muted: {title}. It will not be listed again.",
                      "undo": f"Back to review: {title}."}[action]

    def status_of(self, title: str) -> str:
        item = self.items.get(review_id(title))
        return item.get("status", "") if item else ""

    def accepted(self, title: str) -> bool:
        return self.status_of(title) == "accepted"

    # ---- signed links ---------------------------------------------------------------------------
    def sign(self, rid: str, action: str) -> str:
        return hmac.new(self.secret.encode(), f"{rid}:{action}".encode(), hashlib.sha256).hexdigest()[:20]

    def check(self, rid: str, action: str, sig: str) -> bool:
        return action in ACTIONS and hmac.compare_digest(self.sign(rid, action), str(sig or ""))

    def link(self, base: str, rid: str, action: str) -> str:
        return f"{base.rstrip('/')}/r/{action}/{rid}/{self.sign(rid, action)}"

    # ---- view and storage ---------------------------------------------------------------------
    def rows(self) -> list[dict]:
        with self.lock:
            return sorted((dict(v) for v in self.items.values()), key=lambda v: -v.get("last_seen", 0))

    def counts(self) -> dict:
        with self.lock:
            out = {"pending": 0, "accepted": 0, "muted": 0}
            for v in self.items.values():
                out[v.get("status", "pending")] = out.get(v.get("status", "pending"), 0) + 1
            return out

    def save(self) -> None:
        with self.lock:
            data = {"secret": self.secret, "items": self.items}
        try:
            atomic_write_json(self.path, data)
        except OSError:
            pass
