"""Target via the JSON endpoints target.com itself uses (redsky).

These are not an official public API, so field names can change. Parsing is
defensive, and settings.debug_dump saves raw responses if something breaks.

In-store stock comes from the per-store availability Target shows on product
pages: a promised quantity per store plus whether order pickup works there.
Each of your areas is asked separately and the answers are merged.
"""
from __future__ import annotations

import re
import time
import uuid

from ..models import StockResult, StoreStock
from ..util import dig, normalize_upc, parse_price
from .base import Blocked, Retailer

REDSKY = "https://redsky.target.com/redsky_aggregations/v1/web"
GOOD = {"IN_STOCK", "LIMITED_STOCK", "PRE_ORDER_SELLABLE"}
DETAIL_TTL = 15 * 60
ZIP_RX = re.compile(r"\b(\d{5})(?:-\d{4})?\b")


def _zip_of(text) -> str:
    m = ZIP_RX.findall(str(text or ""))
    return m[-1] if m else ""


class Target(Retailer):
    name = "target"
    display = "Target"
    supports_search = True
    supports_in_store = True
    page_home = "https://www.target.com/"

    def __init__(self, cfg, log, browser=None):
        super().__init__(cfg, log, browser)
        self.visitor_id = uuid.uuid4().hex.upper()
        self.session.headers.update({"Accept": "application/json", "Origin": "https://www.target.com",
                                     "Referer": "https://www.target.com/"})
        self._details: dict[str, tuple[float, dict]] = {}
        self._store: str | None = None

    @property
    def key(self) -> str:
        return str(self.rcfg.get("api_key") or "")

    @property
    def home_zip(self) -> str:
        return self.areas[0].zip if self.areas else self.zip

    # ---- store context ----------------------------------------------------
    def pricing_store(self) -> str:
        ids = [str(s) for s in self.rcfg.get("store_ids") or [] if str(s).strip()]
        if ids:
            return ids[0]
        if self._store is None:
            self._store = ""
            if self.home_zip:
                try:
                    stores = self._nearby(self.home_zip, 25, 1)
                    if stores:
                        self._store = stores[0]["store_id"]
                except Exception:
                    pass
        return self._store or "3991"  # any valid store works for online status

    def _nearby(self, zip_code: str, radius: float, limit: int) -> list[dict]:
        data = self.get_json(f"{REDSKY}/nearby_stores_v1", params={
            "key": self.key, "limit": limit, "within": int(radius), "place": zip_code,
        })
        out = []
        for s in dig(data, "data", "nearby_stores", "stores", default=[]):
            addr = s.get("mailing_address") or {}
            geo = s.get("geographic_specifications") or {}
            out.append({
                "store_id": str(s.get("store_id") or s.get("location_id") or ""),
                "name": s.get("location_name") or "",
                "distance": s.get("distance"),
                "address": addr.get("address_line1", ""),
                "city": addr.get("city", ""),
                "zip": _zip_of(addr.get("postal_code")),
                "lat": geo.get("latitude"),
                "lon": geo.get("longitude"),
            })
        return out

    def stores_near(self, areas) -> list:
        from ..places import Place
        out = []
        for a in areas:
            for s in self._nearby(a.zip, a.radius, 20):
                out.append(Place("target", f"Target {s['name']}".strip(), s["lat"], s["lon"], s["address"],
                                 s["city"], s["zip"], s["store_id"], "chain"))
        return out

    # ---- product detail (title, price, upc) -------------------------------
    def details(self, tcin: str) -> dict:
        cached = self._details.get(tcin)
        if cached and time.time() - cached[0] < DETAIL_TTL:
            return cached[1]
        store = self.pricing_store()
        data = self.get_json(f"{REDSKY}/pdp_client_v1", params={
            "key": self.key, "tcin": tcin, "pricing_store_id": store, "store_id": store,
            "visitor_id": self.visitor_id, "channel": "WEB", "page": f"/p/A-{tcin}",
        })
        product = dig(data, "data", "product", default={})
        info = {
            "title": dig(product, "item", "product_description", "title", default=f"Target item {tcin}"),
            "price": parse_price(dig(product, "price", "current_retail"))
            or parse_price(dig(product, "price", "formatted_current_price")),
            "upc": normalize_upc(dig(product, "item", "primary_barcode")),
            "image": dig(product, "item", "enrichment", "images", "primary_image_url"),
            "third_party": _is_marketplace(product),
        }
        self._details[tcin] = (time.time(), info)
        return info

    # ---- stock --------------------------------------------------------------
    def online_status(self, tcin: str) -> str:
        store = self.pricing_store()
        data = self.get_json(f"{REDSKY}/product_fulfillment_and_variation_hierarchy_v1", params={
            "key": self.key, "tcin": tcin, "store_id": store, "required_store_id": store,
            "zip": self.home_zip or "", "visitor_id": self.visitor_id, "channel": "WEB",
            "paid_membership": "false", "base_membership": "false", "card_membership": "false",
        })
        ful = dig(data, "data", "product", "fulfillment", default={})
        return str(dig(ful, "shipping_options", "availability_status", default="UNKNOWN"))

    def _store_rows(self, tcin: str, zip_code: str, radius: float) -> list[dict]:
        data = self.get_json(f"{REDSKY}/fiats_v1", params={
            "key": self.key, "tcin": tcin, "nearby": zip_code, "radius": int(radius),
            "limit": 20, "requested_quantity": 1, "include_only_available_stores": "false",
        })
        rows = dig(data, "data", "fulfillment_fiats", "locations", default=None)
        if rows is None:  # older/alternate shape: product fulfillment with store_options
            rows = dig(data, "data", "product", "fulfillment", "store_options", default=[])
        return rows or []

    def store_stock(self, tcin: str) -> list[StoreStock]:
        allowed = {str(s) for s in self.rcfg.get("store_ids") or [] if str(s).strip()}
        found: dict[str, StoreStock] = {}
        for area in self.areas:
            for loc in self._store_rows(tcin, area.zip, area.radius):
                store_id = str(loc.get("location_id") or loc.get("store_id") or "")
                if not store_id or (allowed and store_id not in allowed):
                    continue
                qty = loc.get("location_available_to_promise_quantity")
                statuses = {
                    str(dig(loc, k, "availability_status", default="")).upper()
                    for k in ("order_pickup", "in_store_only", "curbside", "ship_to_store")
                }
                try:
                    qty_n = int(float(qty)) if qty not in (None, "") else None
                except (TypeError, ValueError):
                    qty_n = None
                in_stock = (qty_n is not None and qty_n > 0) or (qty_n is None and bool(statuses & GOOD))
                if not in_stock:
                    continue
                pickup = any(str(dig(loc, k, "availability_status", default="")).upper() in GOOD
                             for k in ("order_pickup", "curbside", "drive_up"))
                dist = loc.get("distance")
                address = loc.get("store_address") or loc.get("location_address") or ""
                stock = StoreStock(
                    store_id=store_id,
                    name=loc.get("location_name") or loc.get("store_name") or "",
                    distance=float(dist) if dist not in (None, "") else None,
                    qty=qty_n,
                    address=str(address).split(",")[0] if address else "",
                    pickup=pickup,
                    zip=_zip_of(address) or _zip_of(loc.get("postal_code")),
                    via_area=area.name,
                    chain="target",
                    level="low" if "LIMITED_STOCK" in statuses else "",
                )
                prev = found.get(store_id)
                if prev is None or (stock.distance or 999) < (prev.distance or 999):
                    found[store_id] = stock
            self.pause(0.4)
        return sorted(found.values(), key=lambda s: s.distance if s.distance is not None else 999)

    def check_ids(self, ids: list[str], in_store: bool) -> dict[str, StockResult]:
        out = {}
        for tcin in ids:
            tcin = tcin.strip().removeprefix("A-")
            if not tcin.isdigit():
                continue
            info = self.details(tcin)
            status = self.online_status(tcin).upper()
            res = StockResult(
                retailer=self.name, retailer_name=self.display, product_id=tcin,
                title=info["title"], url=f"https://www.target.com/p/-/A-{tcin}",
                price=info["price"], upc=info["upc"] or None, image=info["image"],
                online=status in GOOD,
                online_status="Pre-order" if status == "PRE_ORDER_SELLABLE" else status.replace("_", " ").title(),
                third_party=info["third_party"],
                preorder=status.startswith("PRE_ORDER"),
            )
            if in_store and self.in_store_enabled():
                res.stores = self.store_stock(tcin)
            out[tcin] = res
            self.pause(0.6)
        return out

    def resolve_upc(self, upc: str) -> str | None:
        """Only accept a result whose barcode matches, so a similar product is never watched by mistake."""
        target_upc = normalize_upc(upc)
        for p in self._search_raw(target_upc or upc, 10):
            tcin = str(p.get("tcin") or "")
            barcode = normalize_upc(dig(p, "item", "primary_barcode"))
            if tcin and barcode and barcode == target_upc:
                return tcin
        for p in self._search_raw(target_upc or upc, 3):  # search results without barcodes: check the product page
            tcin = str(p.get("tcin") or "")
            if tcin and self.details(tcin).get("upc") == target_upc:
                return tcin
        return None

    def _search_variants(self, query: str, count: int, offset: int) -> list[dict]:
        """Parameter sets for plp_search_v2, most like target.com's own request first.
        Target returns a valid but empty answer when it dislikes a parameter mix,
        so an empty first answer is retried with simpler ones."""
        store = self.pricing_store()
        base = {"key": self.key, "keyword": query, "channel": "WEB", "count": count,
                "offset": offset, "page": "/s/" + query.replace(" ", "+"),
                "visitor_id": self.visitor_id, "platform": "desktop", "spellcheck": "true",
                "new_search": "true" if offset == 0 else "false"}
        site = dict(base, default_purchasability_filter="true", include_sponsored="true",
                    pricing_store_id=store, store_ids=store, zip=self.home_zip or "",
                    useragent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        no_store = dict(base, default_purchasability_filter="true", include_sponsored="false")
        bare = {k: v for k, v in base.items() if k not in ("new_search", "spellcheck", "platform")}
        return [site, no_store, bare]

    def _search_raw(self, query: str, limit: int, offset: int = 0) -> list[dict]:
        data, products = {}, None
        for i, params in enumerate(self._search_variants(query, min(limit, 24), offset)):
            data = self.get_json(f"{REDSKY}/plp_search_v2", params=params)
            products = dig(data, "data", "search", "products", default=None)
            if not products and isinstance(data, dict):
                products = _find_products(data)  # layout moved
            if products:
                if i:
                    self.log.info("Target search worked with simpler settings (#%d).", i + 1)
                break
            self.pause(0.5)
        if not products and offset == 0:
            errors = data.get("errors") if isinstance(data, dict) else None
            msg = "; ".join(str(e.get("message", e))[:120] for e in errors[:2]) if isinstance(errors, list) else ""
            self.log.warning("Target search for %r came back empty%s. Saved the response to data\\debug.",
                             query, f" ({msg})" if msg else "")
            self.dump(f"search_empty_{query}", data, force=True)
        return products or []

    # Known Pokemon product numbers, used only when Target's search comes back empty,
    # so shelf checks still run. Titles and prices are read from each product page.
    SEED_TCINS = ("1010892076", "1011407490", "1012850570", "1012793604", "1013166578",
                  "1013166573", "95230445")

    def seed_products(self) -> list[StockResult]:
        out = []
        for tcin in self.SEED_TCINS:
            try:
                info = self.details(tcin)
            except Blocked:
                raise
            except Exception as exc:
                self.log.info("Target seed %s skipped: %s", tcin, exc)
                continue
            out.append(StockResult(
                retailer=self.name, retailer_name=self.display, product_id=tcin, title=info["title"],
                url=f"https://www.target.com/p/-/A-{tcin}", price=info["price"],
                upc=info["upc"] or None, online_status="UNCHECKED", third_party=info["third_party"]))
            self.pause(0.5)
        return out

    def search(self, query: str, limit: int) -> list[StockResult]:
        """Candidates with title and price only. The engine fetches real stock
        for the ones that pass the filters, which saves requests."""
        out, seen, offset = [], set(), 0
        while len(out) < limit:
            page = self._search_raw(query, 24, offset)
            if not page:
                break
            for p in page:
                tcin = str(p.get("tcin") or "")
                if not tcin or tcin in seen:
                    continue
                seen.add(tcin)
                out.append(StockResult(
                    retailer=self.name, retailer_name=self.display, product_id=tcin,
                    title=dig(p, "item", "product_description", "title", default=f"Target item {tcin}"),
                    url=f"https://www.target.com/p/-/A-{tcin}",
                    price=parse_price(dig(p, "price", "current_retail"))
                    or parse_price(dig(p, "price", "formatted_current_price")),
                    upc=normalize_upc(dig(p, "item", "primary_barcode")) or None,
                    online_status="UNCHECKED",
                    third_party=_is_marketplace(p),
                ))
            if len(page) < 24:
                break
            offset += 24
            self.pause(0.5)
        return out[:limit]


def _is_marketplace(product: dict) -> bool | None:
    """Target Plus (third-party) listings name a vendor and are flagged as marketplace."""
    flag = dig(product, "item", "fulfillment", "is_marketplace")
    if flag is not None:
        return bool(flag)
    rel = str(dig(product, "item", "relationship_type_code", default="")).upper()
    if rel:
        return rel in {"TP", "TARGET_PLUS"}
    return None


def _find_products(data, depth: int = 0) -> list[dict] | None:
    """Look for the first list of dicts that carry a tcin anywhere in a response."""
    if depth > 6:
        return None
    if isinstance(data, list):
        if data and all(isinstance(x, dict) for x in data) and any("tcin" in x for x in data):
            return data
        for x in data:
            found = _find_products(x, depth + 1)
            if found:
                return found
    elif isinstance(data, dict):
        for v in data.values():
            found = _find_products(v, depth + 1)
            if found:
                return found
    return None
