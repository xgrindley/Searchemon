"""Walmart via the product data embedded in walmart.com pages (__NEXT_DATA__).

Walmart has strong bot protection. Plain requests are tried first; when they
get a bot check, checks move to the real browser (fetch_mode "auto").
Store shelves are not exposed, but product pages say whether pickup works at
the shopper's selected store. Set your store once in the checking browser
(Retailers, Show browser, walmart.com, pick your store) and pickup shows up.
"""
from __future__ import annotations

import json
import re
from urllib.parse import quote

from ..models import StockResult, StoreStock
from ..util import dig, normalize_upc, parse_price
from .base import Blocked, Retailer

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
        for item_id in ids:
            item_id = item_id.strip()
            if not item_id.isdigit():
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
