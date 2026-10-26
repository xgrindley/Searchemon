"""Best Buy via the official developer API (free key at developer.bestbuy.com).

In-store availability comes from the API's per-store lookup, which Best Buy
describes as near real time and returns only stores that have the item.
"""
from __future__ import annotations

from urllib.parse import quote

from ..models import StockResult, StoreStock
from ..util import normalize_upc, upc_variants
from .base import Blocked, Retailer

API = "https://api.bestbuy.com/v1"
SHOW = ("sku,name,upc,salePrice,regularPrice,onlineAvailability,inStoreAvailability,"
        "orderable,marketplace,image")
IN_STOCK_ORDERABLE = {"available", "preorder"}


class BestBuy(Retailer):
    name = "bestbuy"
    display = "Best Buy"
    supports_search = True
    supports_in_store = True
    search_has_stock = True

    @property
    def key(self) -> str:
        return str(self.rcfg.get("api_key") or "").strip()

    def _api(self, path: str, **params) -> dict:
        if not self.key:
            raise Blocked("Best Buy: no api_key configured", 3600)
        params.update({"apiKey": self.key, "format": "json"})
        data = self.get_json(f"{API}/{path}", params=params) or {}
        self.pause(0.25)  # API allows 5 calls per second
        return data

    def resolve_upc(self, upc: str) -> str | None:
        want = normalize_upc(upc)
        for variant in upc_variants(upc):
            data = self._api(f"products(upc={variant})", show="sku,name,upc")
            for p in data.get("products") or []:
                if normalize_upc(p.get("upc")) == want:   # exact barcode match only
                    return str(p["sku"])
        return None

    def stores_near(self, areas) -> list:
        from ..places import Place
        out = []
        for a in areas:
            data = self._api(f"stores(area({a.zip},{int(a.radius)}))", pageSize=50,
                             show="storeId,name,longName,address,city,postalCode,lat,lng,storeType")
            for s in data.get("stores") or []:
                if str(s.get("storeType") or "").lower() not in ("", "big box", "big_box_store", "bigbox"):
                    continue
                out.append(Place("bestbuy", s.get("longName") or f"Best Buy {s.get('name', '')}".strip(),
                                 s.get("lat"), s.get("lng"), s.get("address", ""), s.get("city", ""),
                                 str(s.get("postalCode") or "")[:5], str(s.get("storeId") or ""), "chain"))
        return out

    def _to_result(self, p: dict) -> StockResult:
        sku = str(p.get("sku"))
        orderable = str(p.get("orderable") or "").lower()
        # "Available" alone is not enough: Best Buy also lists items it will only sell in stores.
        online = bool(p.get("onlineAvailability")) and orderable in IN_STOCK_ORDERABLE
        status = "Pre-order" if orderable == "preorder" else ("In stock" if online else (p.get("orderable") or "Sold out"))
        return StockResult(
            retailer=self.name,
            retailer_name=self.display,
            product_id=sku,
            title=p.get("name") or f"SKU {sku}",
            url=f"https://www.bestbuy.com/site/{sku}.p?skuId={sku}",
            price=p.get("salePrice") or p.get("regularPrice"),
            upc=normalize_upc(p.get("upc")) or None,
            online=online,
            online_status=status,
            third_party=bool(p.get("marketplace")),
            image=p.get("image"),
            preorder=orderable == "preorder",
        )

    def _stores(self, sku: str) -> list[StoreStock]:
        found: dict[str, StoreStock] = {}
        for area in self.areas:
            data = self._api(f"products/{sku}/stores.json", postalCode=area.zip)
            ispu = data.get("ispuEligible")
            for s in data.get("stores") or []:
                dist = s.get("distance")
                if dist is not None and float(dist) > area.radius:
                    continue
                stock = StoreStock(
                    store_id=str(s.get("storeID") or s.get("storeId") or ""),
                    name=s.get("name") or "",
                    distance=float(dist) if dist is not None else None,
                    address=s.get("address") or "",
                    pickup=bool(ispu) if ispu is not None else None,
                    zip=str(s.get("postalCode") or "")[:5],
                    via_area=area.name,
                    chain="bestbuy",
                    level="low" if s.get("lowStock") else "",
                )
                prev = found.get(stock.store_id)
                if prev is None or (stock.distance or 999) < (prev.distance or 999):
                    found[stock.store_id] = stock
        return sorted(found.values(), key=lambda s: s.distance if s.distance is not None else 999)

    def check_ids(self, ids: list[str], in_store: bool) -> dict[str, StockResult]:
        out: dict[str, StockResult] = {}
        for i in range(0, len(ids), 100):
            chunk = [x for x in ids[i:i + 100] if x.isdigit()]
            if not chunk:
                continue
            data = self._api(f"products(sku in({','.join(chunk)}))", show=SHOW, pageSize=100)
            for p in data.get("products") or []:
                res = self._to_result(p)
                if in_store and self.in_store_enabled() and p.get("inStoreAvailability"):
                    res.stores = self._stores(res.product_id)
                out[res.product_id] = res
        return out

    def search(self, query: str, limit: int) -> list[StockResult]:
        terms = [quote(t, safe="") for t in query.split() if t.strip()]
        if not terms:
            return []
        expr = "&".join(f"search={t}" for t in terms)
        data = self._api(f"products({expr})", show=SHOW, pageSize=min(limit, 100),
                         sort="releaseDate.dsc")
        return [self._to_result(p) for p in data.get("products") or []]
