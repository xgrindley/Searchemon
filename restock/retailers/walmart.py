"""Walmart via the product data embedded in walmart.com pages (__NEXT_DATA__).

Walmart has strong bot protection. Plain requests are tried first; when they
get a bot check, checks move to the real browser (fetch_mode "auto").
Store shelves are not exposed, but product pages say whether pickup works at
the shopper's selected store. Set your store once in the checking browser
(Retailers, Show browser, walmart.com, pick your store) and pickup shows up.
"""
from __future__ import annotations

import json
import os
import re
import time
from urllib.parse import quote

from .. import walmart_auth
from ..models import StockResult, StoreStock
from ..util import dig, normalize_upc, parse_price
from .base import Blocked, Retailer

API_ITEMS = "https://developer.api.walmart.com/api-proxy/service/affil/product/v2/items"
API_OUT = ("out of stock", "not available", "unavailable", "sold out")
API_IN = ("available", "limited supply", "last few items", "in stock")

NEXT_DATA = re.compile(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
WALMART_SELLERS = {"walmart.com", "walmart"}
WALMART_SELLER_ID = "F55CDC31AB754BB68FE0B39041159D63"


def _third_party(p: dict) -> bool | None:
    seller = str(p.get("sellerName") or p.get("sellerDisplayName") or "").strip().lower()
    if seller:
        return seller not in WALMART_SELLERS
    sid = str(p.get("sellerId") or "").upper()
    if sid:
        return sid != WALMART_SELLER_ID
    return None   # unknown: not treated as third party, but not confirmed either


def _pickup_stores(p: dict) -> list[StoreStock]:
    out = []
    for opt in p.get("fulfillmentOptions") or []:
        kind = str(opt.get("type") or opt.get("fulfillmentType") or "").upper()
        status = str(opt.get("availabilityStatus") or opt.get("availability") or "").upper()
        if kind == "PICKUP" and status in ("IN_STOCK", "AVAILABLE", "LIMITED_STOCK"):
            sid = str(opt.get("storeId") or opt.get("locationId") or dig(opt, "location", "storeId", default="") or "selected")
            out.append(StoreStock(store_id=sid, name=opt.get("storeName") or opt.get("locationText") or "Your Walmart store",
                                  pickup=True, chain="walmart",
                                  level="low" if status == "LIMITED_STOCK" else ""))
    return out


class Walmart(Retailer):
    name = "walmart"
    display = "Walmart"
    supports_search = True
    search_has_stock = True
    default_fetch_mode = "auto"

    # ---- Walmart.io (official affiliate API) -----------------------------------------------
    _key = None
    _key_mtime = 0.0
    _api_off_until = 0.0
    _api_warned = ""

    @property
    def api_configured(self) -> bool:
        return bool(str(self.rcfg.get("consumer_id") or "").strip() and str(self.rcfg.get("private_key_file") or "").strip())

    def _private_key(self):
        path = os.path.expanduser(str(self.rcfg.get("private_key_file") or "").strip().strip('"'))
        if not os.path.isabs(path):
            path = os.path.join(os.path.dirname(self.cfg.data_dir), path)
        mtime = os.path.getmtime(path)
        if self._key is None or mtime != self._key_mtime:
            with open(path, encoding="utf-8", errors="replace") as fh:
                self._key = walmart_auth.parse_private_key(fh.read())
            self._key_mtime = mtime
        return self._key

    def _api_headers(self) -> dict:
        return walmart_auth.headers(str(self.rcfg.get("consumer_id")).strip(),
                                    str(self.rcfg.get("key_version") or "1").strip(), self._private_key())

    def _warn_api(self, msg: str) -> None:
        if msg != self._api_warned:
            self._api_warned = msg
            self.log.warning("Walmart.io: %s Falling back to the website for now.", msg)

    def _api_get(self, params: dict) -> dict | None:
        """One signed call; None when the API is off, refused, or unreadable (the caller then uses the website)."""
        if not self.api_configured or time.time() < self._api_off_until:
            return None
        pub = str(self.rcfg.get("publisher_id") or "").strip()
        if pub:
            params = {**params, "publisherId": pub}
        try:
            resp = self.session.get(API_ITEMS, params=params, headers=self._api_headers(), timeout=25)
        except (OSError, walmart_auth.KeyError_) as exc:
            self._api_off_until = time.time() + 600
            self._warn_api(f"could not use your private key file ({exc if isinstance(exc, walmart_auth.KeyError_) else exc.__class__.__name__}).")
            return None
        except Exception as exc:
            self._warn_api(f"network error ({exc.__class__.__name__}).")
            return None
        if resp.status_code in (401, 403):
            self._api_off_until = time.time() + 1800
            self._warn_api("refused the signature (check the Consumer ID, key version, and that the matching public "
                           "key is uploaded to your Walmart.io app).")
            return None
        if resp.status_code == 429:
            self._api_off_until = time.time() + 120
            self._warn_api("rate limit reached.")
            return None
        if resp.status_code >= 400:
            self._warn_api(f"HTTP {resp.status_code}.")
            return None
        try:
            data = resp.json()
        except ValueError:
            self.dump("api", resp.text[:100000], force=True)
            self._warn_api("answer was not readable (saved to data\\debug).")
            return None
        self._api_warned = ""
        return data

    @staticmethod
    def api_items(data) -> list[dict]:
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return [i for i in data["items"] if isinstance(i, dict) and i.get("itemId") is not None]
        if isinstance(data, list):
            return [i for i in data if isinstance(i, dict) and i.get("itemId") is not None]
        if isinstance(data, dict) and data.get("itemId") is not None:
            return [data]
        return []

    def api_result(self, it: dict) -> StockResult:
        item_id = str(it.get("itemId"))
        stock = str(it.get("stock") or "").strip()
        low = stock.lower()
        avail = it.get("availableOnline")
        if isinstance(avail, str):
            avail = avail.lower() == "true"
        if avail is None:
            online = bool(low) and not any(o in low for o in API_OUT) and any(i in low for i in API_IN)
        else:
            online = bool(avail) and not any(o in low for o in API_OUT)
        market = it.get("marketplace")
        offer = str(it.get("offerType") or "").upper()
        preorder = "PRE" in offer and "ORDER" in offer
        return StockResult(
            retailer="walmart", retailer_name=self.display, product_id=item_id,
            title=it.get("name") or f"Walmart item {item_id}",
            url=f"https://www.walmart.com/ip/{item_id}",
            price=parse_price(it.get("salePrice")) or parse_price(it.get("msrp")),
            upc=normalize_upc(it.get("upc")) or None,
            online=online,
            online_status=("Pre-order" if preorder and online else stock) or ("In stock" if online else "Out of stock"),
            third_party=bool(market) if isinstance(market, bool) else None,
            image=it.get("mediumImage") or it.get("thumbnailImage") or None,
            preorder=preorder,
        )

    def _api_check(self, ids: list[str]) -> dict[str, StockResult]:
        out: dict[str, StockResult] = {}
        for i in range(0, len(ids), 20):
            chunk = ids[i:i + 20]
            data = self._api_get({"ids": ",".join(chunk)})
            if data is None:
                break
            items = self.api_items(data)
            for it in items:
                out[str(it["itemId"])] = self.api_result(it)
            if not items:
                self.dump("api_items", json.dumps(data)[:100000], force=True)
                self._warn_api("answered, but no items could be read from it (saved to data\\debug).")
            self.dump("api_items", data)
            self.pause(0.4)
        return out

    def _next_data(self, url: str) -> dict:
        resp = self.fetch_html(url)
        if resp.status == 404:
            return {}
        m = NEXT_DATA.search(resp.text)
        if not m:
            self.dump("page", resp.text[:200000])
            raise Blocked("Walmart: page loaded without product data (layout change or bot check)", 900)
        data = json.loads(m.group(1))
        self.dump(url.rsplit("/", 1)[-1], data)
        return data

    @staticmethod
    def _product_result(item_id: str, p: dict, display: str) -> StockResult:
        status = str(p.get("availabilityStatus") or "").upper()
        preorder = bool(p.get("isPreOrder") or dig(p, "preOrder", "isPreOrder"))
        return StockResult(
            retailer="walmart", retailer_name=display, product_id=item_id,
            title=p.get("name") or f"Walmart item {item_id}",
            url=f"https://www.walmart.com/ip/{item_id}",
            price=parse_price(dig(p, "priceInfo", "currentPrice", "price")),
            upc=normalize_upc(p.get("upc")) or None,
            online=status == "IN_STOCK",
            online_status=("Pre-order" if preorder and status == "IN_STOCK" else status.replace("_", " ").title()) or "Unknown",
            third_party=_third_party(p),
            image=dig(p, "imageInfo", "thumbnailUrl"),
            stores=_pickup_stores(p),
            preorder=preorder,
        )

    def check_ids(self, ids: list[str], in_store: bool) -> dict[str, StockResult]:
        out = {}
        ids = [i.strip() for i in ids if i.strip().isdigit()]
        if self.api_configured:
            out.update(self._api_check(ids))             # official feed first; the website only for what it missed
        for item_id in ids:
            if item_id in out:
                continue
            data = self._next_data(f"https://www.walmart.com/ip/{item_id}")
            product = dig(data, "props", "pageProps", "initialData", "data", "product")
            if product:
                out[item_id] = self._product_result(item_id, product, self.display)
            self.pause(max(1.0, self.link_delay()))
        return out

    def _search_items(self, query: str) -> list[dict]:
        data = self._next_data(f"https://www.walmart.com/search?q={quote(query)}")
        stacks = dig(data, "props", "pageProps", "initialData", "searchResult", "itemStacks", default=[])
        items = []
        for stack in stacks:
            for it in stack.get("items") or []:
                if it.get("usItemId") and it.get("__typename", "Product") == "Product":
                    items.append(it)
        return items

    def resolve_upc(self, upc: str) -> str | None:
        if self.api_configured:
            data = self._api_get({"upc": normalize_upc(upc).zfill(12)})
            found = self.api_items(data) if data is not None else []
            if found:
                return str(found[0]["itemId"])
        items = self._search_items(normalize_upc(upc).zfill(12))
        return str(items[0]["usItemId"]) if items else None

    def search(self, query: str, limit: int) -> list[StockResult]:
        out = []
        for it in self._search_items(query)[:limit]:
            item_id = str(it["usItemId"])
            status = str(dig(it, "availabilityStatusV2", "value", default=it.get("availabilityStatus") or "")).upper()
            out.append(StockResult(
                retailer=self.name, retailer_name=self.display, product_id=item_id,
                title=it.get("name") or f"Walmart item {item_id}",
                url=f"https://www.walmart.com/ip/{item_id}",
                price=parse_price(it.get("price")) or parse_price(dig(it, "priceInfo", "linePrice")),
                online=status == "IN_STOCK",
                online_status=status.replace("_", " ").title() or "Unknown",
                third_party=_third_party(it),
                image=it.get("image"),
            ))
        return out
