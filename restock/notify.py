"""Discord webhook alerts plus optional Windows toast notifications."""
from __future__ import annotations

import dataclasses
import datetime as dt
import logging
import threading
import time

import requests

from .models import StockResult
from .util import clean_url

GREEN = 0x2ECC71
GREY = 0x95A5A6
BLUE = 0x5865F2
AMBER = 0xF1A33A
RETAILER_COLORS = {
    "target": 0xCC0000, "bestbuy": 0x0046BE, "walmart": 0x0071CE,
    "walgreens": 0xE31837, "cvs": 0xCC0000,
}


EMBED_BUDGET = 5600   # Discord rejects an embed over 6000 characters in total


def embed_size_so_far(title: str, desc: str, fields: list[dict], footer_len: int = 0) -> int:
    return len(title) + 12 + len(desc) + footer_len + sum(len(f["name"]) + len(f["value"]) for f in fields)


def fit_store_fields(store_fields: list[dict], used: int) -> list[dict]:
    """Keep as many store blocks as fit in the embed's character budget. Without
    this, a restock spread over many stores is refused by Discord and never arrives."""
    out, left = [], EMBED_BUDGET - used
    for f in store_fields:
        cost = len(f["name"]) + len(f["value"])
        if cost <= left and len(out) < 18:
            out.append(f)
            left -= cost
            continue
        room = left - len(f["name"]) - 40
        if room > 120 and len(out) < 18:
            cut = f["value"][:room].rsplit("\n", 1)[0]
            out.append({**f, "value": cut + "\n...more stores not shown"})
        break
    return out


class DiscordNotifier:
    def __init__(self, discord_cfg: dict, log: logging.Logger, areas=()):
        self.area_hooks = {a.name: a.webhook for a in areas if getattr(a, "webhook", "")}
        self.hooks = {k: v for k, v in (discord_cfg.get("webhooks") or {}).items() if v}
        # The "status" channel is for everything that is not stock: sign-in needed, blocks, method changes.
        # It is kept out of the restock routing so a stock alert can never land there.
        self.status_url = self.hooks.pop("status", "")
        self.status_ping = bool(discord_cfg.get("ping_status", False))
        self.role = str(discord_cfg.get("mention_role_id") or "").strip()
        self.user = str(discord_cfg.get("mention_user_id") or "").strip()
        self.username = discord_cfg.get("username") or "Restock Monitor"
        self.log = log
        self.lock = threading.Lock()
        self.last_post = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.hooks or self.area_hooks)

    @property
    def status_enabled(self) -> bool:
        return bool(self.status_url)

    def status(self, title: str, text: str, kind: str = "info", ping: bool = False) -> bool:
        """A message for the status channel. Never pings unless you turned that on, and only for things you must act on."""
        if not self.status_url:
            return False
        color = {"blocked": AMBER, "human": AMBER, "signin": BLUE, "autostop": GREY, "recovered": GREEN,
                 "browser": AMBER}.get(kind, BLUE)
        content, allowed = self._mention(ping and self.status_ping)
        embed = {"title": title[:256], "description": text[:3800], "color": color,
                 "footer": {"text": "Status"}, "timestamp": dt.datetime.now(dt.timezone.utc).isoformat()}
        return self._post(self.status_url, {"username": self.username, "content": content, "embeds": [embed],
                                            "allowed_mentions": allowed})

    def routes(self, res: StockResult, new_online: bool = True, new_stores: bool = True) -> list[tuple[str, StockResult]]:
        """Which channels an alert goes to, and what each one shows.

        - a webhook named after the store (for example "target") wins for that store and shows everything
        - otherwise online stock goes to the "online" channel and shows only the online side, and
          store shelf stock goes to the "in_store" channel and shows only the store side, so neither
          channel repeats what belongs in the other; "default" fills any gap. When both land on the
          same channel one combined alert is posted
        - only the side that actually changed is posted (new_online / new_stores)
        - each of your areas with its own webhook also gets the alert, showing
          only the stores inside that area
        The same channel is never posted to twice for one alert.
        """
        out: list[tuple[str, StockResult]] = []
        used: set[str] = set()

        def add(url, view):
            if url and url not in used:
                used.add(url)
                out.append((url, view))

        own = self.hooks.get(res.retailer)
        if own:
            add(own, res)
        else:
            default = self.hooks.get("default")
            online_url = self.hooks.get("online") or default
            store_url = self.hooks.get("in_store") or default
            send_online = res.online and new_online
            send_stores = bool(res.stores) and new_stores
            if send_online and send_stores and online_url == store_url:
                add(online_url, res)
            else:
                if send_online:
                    add(online_url, dataclasses.replace(res, stores=[]))
                if send_stores:
                    add(store_url, dataclasses.replace(res, online=False, online_status=""))
            if not out and not (res.online or res.stores):
                add(default, res)
        if res.stores and new_stores and self.area_hooks:
            for area, url in self.area_hooks.items():
                mine = [st for st in res.stores if st.area == area]
                if mine:
                    add(url, dataclasses.replace(res, stores=mine, online=False, online_status=""))
        if not out:  # nothing matched: never lose an alert
            add(self.hooks.get("default") or next(iter(self.hooks.values()), None), res)
        return out

    @staticmethod
    def reason_for(view: StockResult, reason: str, new_store_ids: tuple[str, ...]) -> str:
        """Reason text that only talks about what this channel's alert shows."""
        parts = []
        for part in [p.strip() for p in reason.split(",") if p.strip()]:
            if part == "online restock":
                if view.online:
                    parts.append(part)
            elif "new store" in part:
                if view.stores:
                    mine = [st for st in view.stores if st.store_id in set(new_store_ids)] if new_store_ids else []
                    parts.append(f"in stock at {len(mine)} new store(s)" if mine else part)
            else:
                parts.append(part)
        return ", ".join(parts)

    def _hook_for(self, retailer: str) -> str | None:
        return self.hooks.get(retailer) or self.hooks.get("default")

    def _mention(self, ping: bool = True) -> tuple[str, dict]:
        content, allowed = [], {"parse": [], "roles": [], "users": []}
        if not ping:
            return "", allowed
        if self.role:
            content.append(f"<@&{self.role}>")
            allowed["roles"].append(self.role)
        if self.user:
            content.append(f"<@{self.user}>")
            allowed["users"].append(self.user)
        return " ".join(content), allowed

    def _post(self, url: str, payload: dict) -> bool:
        with self.lock:
            for _ in range(4):
                wait = 0.6 - (time.time() - self.last_post)  # stay under 5 posts per 2s
                if wait > 0:
                    time.sleep(wait)
                try:
                    resp = requests.post(url, json=payload, timeout=15)
                except requests.RequestException as exc:
                    self.log.warning("Discord post failed: %s", exc.__class__.__name__)
                    return False
                self.last_post = time.time()
                if resp.status_code == 429:
                    try:
                        retry = float(resp.json().get("retry_after", 1))
                    except ValueError:
                        retry = 2.0
                    time.sleep(min(retry, 30))
                    continue
                if resp.status_code >= 300:
                    self.log.warning("Discord returned %s: %s", resp.status_code, resp.text[:200])
                    return False
                return True
        return False

    def restock(self, res: StockResult, reason: str, new_store_ids: tuple[str, ...] = (), ping: bool = True) -> bool:
        low = (reason or "").lower()
        known = "online restock" in low or "new store" in low
        routes = self.routes(res, new_online=("online restock" in low) if known else True,
                             new_stores=("new store" in low or bool(new_store_ids)) if known else True)
        if not routes:
            return False
        sent = [self._restock_to(url, view, self.reason_for(view, reason, new_store_ids) if known else reason,
                                 new_store_ids, ping) for url, view in routes]
        return any(sent)

    def _restock_to(self, url: str, res: StockResult, reason: str, new_store_ids: tuple[str, ...],
                    ping: bool) -> bool:
        fields = [{"name": "Retailer", "value": res.retailer_name, "inline": True}]
        if res.type_label:
            fields.append({"name": "Product", "value": res.type_label, "inline": True})
        if res.price is not None:
            price = f"${res.price:.2f}"
            if res.msrp:
                price += f" (MSRP ${res.msrp:.2f})"
            fields.append({"name": "Price", "value": price, "inline": True})
        if res.online:
            fields.append({"name": "Online", "value": res.online_status or "In stock", "inline": True})
        store_fields = self._store_fields(res, set(new_store_ids)) if res.stores else []
        if res.upc:
            fields.append({"name": "UPC", "value": res.upc, "inline": True})
        fields.append({"name": "Item ID", "value": str(res.product_id)[:100] or "-", "inline": True})

        desc = [reason.capitalize()] if reason else []
        if res.stores:
            units = sum(st.qty or 0 for st in res.stores)
            desc.append(f"In stock at {len(res.stores)} store{'s' if len(res.stores) != 1 else ''} near you"
                        + (f", {units} unit{'s' if units != 1 else ''} counted" if units else "") + ".")
        pickup = res.pickup_stores
        if pickup:
            nearest = pickup[0]
            desc.append(f"Order pickup available at {len(pickup)} store(s), nearest {nearest.name}"
                        f"{f' ({nearest.distance:.1f} mi)' if nearest.distance is not None else ''}. "
                        "Buy online now and pick up instead of driving around.")
        elif res.stores and not res.online:
            desc.append("On the shelf in store (not orderable for pickup). Call ahead or go soon.")
        if res.stores and all(s.low for s in res.stores):
            desc.append("Low counts can be wrong (items already sold or misplaced), so call the store first.")
        if res.preorder:
            desc.append("This is a pre-order: you pay now and it ships on release.")
        if res.confirmed:
            desc.append("Confirmed on a second check.")
        desc_text = "\n".join(desc)[:3500]
        embed = {
            "title": f"IN STOCK: {res.title}"[:256],
            "url": clean_url(res.url),
            "description": desc_text or None,
            "color": RETAILER_COLORS.get(res.retailer, GREEN),
            "fields": fields + fit_store_fields(store_fields, embed_size_so_far(res.title, desc_text, fields, footer_len=60)),
            "footer": {"text": f"Matched {res.watch_name or res.source}"[:200]},
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        embed = {k: v for k, v in embed.items() if v}
        if res.image and str(res.image).startswith(("http://", "https://")):
            embed["thumbnail"] = {"url": res.image}
        content, allowed = self._mention(ping)
        return self._post(url, {"username": self.username, "content": content,
                                "embeds": [embed], "allowed_mentions": allowed})

    @staticmethod
    def _store_fields(res: StockResult, new: set) -> list[dict]:
        """Every store with stock, grouped by your area, nearest first: name,
        distance, how many it has, pickup, and address."""
        groups: dict[str, list[str]] = {}
        for st in sorted(res.stores, key=lambda x: (x.area, x.distance if x.distance is not None else 9e9)):
            bits = [f"**{st.name or 'Store ' + st.store_id}**"]
            if st.distance is not None:
                bits[0] += f" ({st.distance:.1f} mi)"
            line = bits[0] + f": {st.stock_text()}"
            if st.pickup:
                line += ", pickup today"
            elif st.pickup is False:
                line += ", in store only"
            if st.store_id in new:
                line = "NEW " + line
            if st.address:
                line += f"\n{st.address}"
            groups.setdefault(st.area or "", []).append(line)
        fields, shown = [], 0
        for area, lines in groups.items():
            chunk, title = [], f"In stock near {area}" if area else "In stock at stores"
            for line in lines:
                if len(fields) >= 20:
                    break
                if sum(len(x) + 1 for x in chunk) + len(line) > 1000:
                    fields.append({"name": title[:256], "value": "\n".join(chunk), "inline": False})
                    title, chunk = title + " (more)", []
                chunk.append(line)
                shown += 1
            if chunk and len(fields) < 20:
                fields.append({"name": title[:256], "value": "\n".join(chunk), "inline": False})
        if shown < len(res.stores):
            fields.append({"name": "More stores", "value": f"...and {len(res.stores) - shown} more", "inline": False})
        return fields

    def new_listing(self, item: dict, ping: bool = False) -> bool:
        url = self._hook_for(item["retailer"])
        if not url:
            return False
        fields = [{"name": "Retailer", "value": item["retailer_name"], "inline": True},
                  {"name": "Product", "value": item.get("type_label") or "Pokemon product", "inline": True}]
        if item.get("price"):
            fields.append({"name": "Price", "value": f"${item['price']:.2f}", "inline": True})
        embed = {"title": f"New listing: {item['title']}"[:256], "url": clean_url(item["url"]), "color": BLUE,
                 "description": "Just appeared in the store's catalog. It may not be buyable yet; "
                                "the monitor now tracks it and alerts when it is in stock.",
                 "fields": fields, "timestamp": dt.datetime.now(dt.timezone.utc).isoformat()}
        content, allowed = self._mention(ping)
        return self._post(url, {"username": self.username, "content": content, "embeds": [embed], "allowed_mentions": allowed})

    def queue_open(self, sig: dict, ping: bool = True) -> bool:
        url = self._hook_for(sig["site"])
        if not url:
            return False
        embed = {"title": f"{sig['display']} queue is open", "url": sig["url"], "color": AMBER,
                 "description": "The waiting room is up, which usually means a drop is starting within minutes. "
                                "Open the site and join the line; don't refresh once you're in.",
                 "timestamp": dt.datetime.now(dt.timezone.utc).isoformat()}
        content, allowed = self._mention(ping)
        return self._post(url, {"username": self.username, "content": content, "embeds": [embed],
                                "allowed_mentions": allowed})

    def note(self, text: str) -> bool:
        url = self.hooks.get("default") or next(iter(self.hooks.values()), None)
        if not url:
            return False
        return self._post(url, {"username": self.username, "content": text[:1900],
                                "allowed_mentions": {"parse": []}})

    def sold_out(self, res: StockResult) -> bool:
        url = self._hook_for(res.retailer)
        if not url:
            return False
        embed = {"title": f"Sold out: {res.title}"[:256], "url": clean_url(res.url), "color": GREY,
                 "footer": {"text": res.retailer_name}}
        return self._post(url, {"username": self.username, "embeds": [embed],
                                "allowed_mentions": {"parse": []}})

    def test(self) -> dict[str, bool]:
        results = {}
        everything = dict(self.hooks)
        everything.update({f"area: {n}": u for n, u in self.area_hooks.items()})
        for name, url in everything.items():
            results[name] = self._post(url, {
                "username": self.username,
                "embeds": [{"title": "Restock monitor connected",
                            "description": f"Alerts for '{name}' will post here.",
                            "color": GREEN}],
                "allowed_mentions": {"parse": []},
            })
        if self.status_url:
            results["status"] = self._post(self.status_url, {
                "username": self.username,
                "embeds": [{"title": "Status channel connected",
                            "description": "Sign-in requests, blocks and method changes will post here. Stock alerts never do.",
                            "color": GREEN}],
                "allowed_mentions": {"parse": []},
            })
        return results


class Toaster:
    """Windows 10/11 toast via winotify when installed. Silently does nothing elsewhere."""

    def __init__(self, enabled: bool):
        self.notification = None
        if enabled:
            try:
                from winotify import Notification  # type: ignore
                self.notification = Notification
            except Exception:
                self.notification = None

    def message(self, title: str, msg: str) -> None:
        if not self.notification:
            return
        try:
            self.notification(app_id="Restock Monitor", title=title[:60], msg=msg[:200]).show()
        except Exception:
            pass

    def show(self, res: StockResult, reason: str) -> None:
        if not self.notification:
            return
        try:
            toast = self.notification(
                app_id="Restock Monitor",
                title=f"{res.retailer_name}: in stock"[:60],
                msg=f"{res.title[:90]}\n{reason}",
                launch=clean_url(res.url),
            )
            toast.show()
        except Exception:
            pass
