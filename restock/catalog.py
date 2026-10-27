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
TIP_BOOST_S = 3600               # a product named in a community restock post is checked every cycle for an hour

# How often a found listing is checked adapts to what that store actually does with it. Every check that finds it
# out of stock (or priced far over MSRP) is a "miss". The first few misses cost nothing; after that the wait before
# the next check doubles every few misses, up to a day, so a listing a store never has is still looked at daily but
# no longer takes a turn every round. Anything that suggests movement resets it: stock at this store, a restock of
# the same product at another store, the price changing, or the store's search showing it again with a new price.
FREE_MISSES = 5                  # misses before checks start to space out
STEP_MISSES = 5                  # the wait doubles every this many further misses
FIRST_WAIT_S = 30 * 60
MAX_WAIT_S = 24 * 3600
PRIORITY_HEAD_S = 600            # head start per priority level when choosing what to check next


def wait_after(misses: int) -> float:
    """Seconds to wait before checking a listing again after this many misses in a row."""
    if misses < FREE_MISSES:
        return 0.0
    return min(MAX_WAIT_S, FIRST_WAIT_S * 2 ** ((misses - FREE_MISSES) // STEP_MISSES))


def _moved(old, new) -> bool:
    """A price change worth noticing (more than 3%, or a price appearing or disappearing)."""
    if not old or not new:
        return bool(old) != bool(new)
    return abs(float(new) - float(old)) / float(old) > 0.03


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
                if r.price and _moved(item.get("price"), r.price):
                    self._wake(item)              # the store's search shows a new price: worth a look soon
                item.update({"title": r.title, "last_seen": now, "price": r.price or item.get("price"),
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

    @staticmethod
    def _wake(item: dict) -> None:
        item["misses"] = min(int(item.get("misses") or 0), FREE_MISSES - 1)
        item["next_due"] = 0

    def note_stock(self, res: StockResult, over_cap: bool = False) -> None:
        """Record a check of a found listing and set when it is next due (see wait_after). over_cap: in stock but
        priced past your limit, which for checking purposes is as good as out of stock."""
        item = self.items.get(res.key)
        if item is None:
            return
        now = time.time()
        with self.lock:
            item["checks"] = int(item.get("checks") or 0) + 1
            item["last_checked"] = now
            moved = res.price is not None and _moved(item.get("price"), res.price)
            if res.in_stock and not over_cap:
                item["last_in_stock"] = now
                item["hits"] = int(item.get("hits") or 0) + 1
                item["misses"] = 0
                item["next_due"] = 0
            else:
                item["misses"] = int(item.get("misses") or 0) + 1
                item["over_cap"] = int(item.get("over_cap") or 0) + (1 if over_cap else 0)
                item["next_due"] = now + wait_after(item["misses"])
                if moved:
                    self._wake(item)              # the price changed: something is happening, back to the normal pace
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
                    self._wake(v)                 # restocked elsewhere: this store may be next
                    n += 1
        return n

    def wake_matching(self, stores: list[str], title: str, limit: int = 5) -> list[str]:
        """A community post says this product is in stock at these stores: check the listings that match it at
        those stores every cycle for a while, starting now. A listing matches when it shares two name words with
        the post ("phantasmal flames"), or one name word and the same product type. Returns the keys woken."""
        from .community import name_words
        words = name_words(title)
        kind = classify(title).type_key
        if not stores or not words:
            return []
        now = time.time()
        scored = []
        with self.lock:
            for key, v in self.items.items():
                if v["retailer"] not in stores or v.get("status") == "ignored":
                    continue
                shared = len(words & name_words(v.get("title", "")))
                same = bool(kind and kind != "other" and v.get("type") == kind)
                if shared >= 2 or (shared and same):
                    scored.append((shared * 2 + same, key))
            woke = [k for _, k in sorted(scored, reverse=True)[:limit]]
            for key in woke:
                self.items[key]["boost_until"] = max(self.items[key].get("boost_until", 0), now + TIP_BOOST_S)
                self._wake(self.items[key])
        return woke

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
        # Of the rest, only listings that are due (see wait_after), the longest-waiting first. Wanted types count as
        # having waited PRIORITY_HEAD_S longer per priority level, so they come up more often, but nothing is starved.
        due = [v for v in items if v not in hot and float(v.get("next_due") or 0) <= now]
        due.sort(key=lambda v: float(v.get("last_checked") or 0) - (9 - int(v.get("priority", 9))) * PRIORITY_HEAD_S)
        return hot + due[: max(0, n - len(hot))]

    def schedule_view(self, v: dict) -> dict:
        """How often a listing is being checked, in words, for the control panel."""
        misses, now = int(v.get("misses") or 0), time.time()
        wait = max(0.0, float(v.get("next_due") or 0) - now)
        if misses < FREE_MISSES or wait <= 0:
            return {"pace": "normal", "text": ""}
        over = int(v.get("over_cap") or 0)
        why = f"not available the last {misses} checks" + (f" ({over} of them priced over your limit)" if over else "")
        return {"pace": "slow", "text": f"Checked less often: {why}. Next check in {_span(wait)}."}

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
            entry["listings"].append({"key": key, **v, "schedule": self.schedule_view(v)})
        return sorted(groups.values(), key=lambda e: (e["priority"], e["title"]))


def _span(seconds: float) -> str:
    if seconds < 90 * 60:
        return f"{max(1, round(seconds / 60))} min"
    return f"{seconds / 3600:.0f} h"
