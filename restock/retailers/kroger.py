"""Kroger and its store brands via Kroger's official public API.

Covers Kroger, Fred Meyer, Ralphs, Smith's, King Soopers, Fry's, QFC, Dillons,
Harris Teeter, Food 4 Less and the other Kroger banners. A free developer
account (developer.kroger.com) gives a client ID and secret. With a store's
location ID, product lookups include that store's stock level (HIGH, LOW,
TEMPORARILY_OUT_OF_STOCK) and whether curbside pickup works.

Daily limits on a free account: 10,000 product calls and 1,600 location calls.
Each cycle makes one product call per store per 50 items, so the defaults
(5 stores, every 5 minutes) use about 1,500 product calls a day.
"""
from __future__ import annotations

import threading
import time

import requests

from ..models import StockResult, StoreStock
from ..util import dig, normalize_upc, parse_price
from .base import Blocked, Retailer

API = "https://api.kroger.com/v1"
GOOD_LEVELS = {"HIGH", "LOW"}
LOCATIONS_TTL = 24 * 3600


def kroger_product_ids(upc: str) -> list[str]:
    """Kroger product IDs are 13 digits. Try the barcode without its check digit
    (Kroger's usual form) and with it."""
    core = normalize_upc(upc)
    if not core:
        return []
    out = []
    if len(core) >= 11:
        out.append(core[:-1].zfill(13))
    out.append(core.zfill(13))
    return list(dict.fromkeys(x for x in out if len(x) == 13))


class Kroger(Retailer):
    name = "kroger"
    display = "Kroger family"
    supports_search = True
    supports_in_store = True

    def __init__(self, cfg, log, browser=None):
        super().__init__(cfg, log, browser)
        self.session.headers.update({"Accept": "application/json"})
        self._token = ""
        self._token_until = 0.0
        self._token_lock = threading.Lock()
        self._locations: list[dict] = []
        self._locations_at = 0.0

    # ---- auth -----------------------------------------------------------------
    def setup_needed(self) -> str:
        if not (str(self.rcfg.get("client_id") or "").strip() and str(self.rcfg.get("client_secret") or "").strip()):
            return "Needs a free Kroger key (developer.kroger.com). Add it in Stores, or switch Kroger off."
        return ""

    def token(self) -> str:
        cid, secret = str(self.rcfg.get("client_id") or ""), str(self.rcfg.get("client_secret") or "")
        if not (cid and secret):
            raise Blocked("Kroger: add a client ID and secret (free at developer.kroger.com)", 3600)
        with self._token_lock:
            if self._token and time.time() < self._token_until - 60:
                return self._token
            try:
                resp = self.session.post(f"{API}/connect/oauth2/token", auth=(cid, secret), timeout=20,
                                         data={"grant_type": "client_credentials", "scope": "product.compact"})
            except requests.RequestException as exc:
                raise ConnectionError(f"Kroger: network error {exc.__class__.__name__}") from exc
            if resp.status_code in (400, 401):
                raise Blocked("Kroger: client ID or secret was rejected", 3600)
            if resp.status_code != 200:
                raise ConnectionError(f"Kroger: sign-in failed ({resp.status_code})")
            try:
                data = resp.json()
            except ValueError as exc:
                raise ConnectionError("Kroger: sign-in answer was not readable; trying again later") from exc
            if not isinstance(data, dict) or not data.get("access_token"):
                raise ConnectionError("Kroger: sign-in gave no access token; trying again later")
            self._token = data.get("access_token", "")
            self._token_until = time.time() + float(data.get("expires_in") or 1800)
            return self._token

    def _api(self, path: str, **params) -> dict:
        data = self.get_json(f"{API}/{path}", params=params,
                             headers={"Authorization": f"Bearer {self.token()}"}) or {}
        self.pause(0.15)
        return data

    # ---- stores ------------------------------------------------------------------
    def locations(self) -> list[dict]:
        if self._locations and time.time() - self._locations_at < LOCATIONS_TTL:
            return self._locations
        wanted = {str(s) for s in self.rcfg.get("store_ids") or [] if str(s).strip()}
        found: dict[str, dict] = {}
        for area in self.areas:
            data = self._api("locations", **{"filter.zipCode.near": area.zip,
                                             "filter.radiusInMiles": int(min(area.radius, 100)),
                                             "filter.limit": 50})
            for loc in data.get("data") or []:
                lid = str(loc.get("locationId") or "")
                if not lid or (wanted and lid not in wanted):
                    continue
                addr = loc.get("address") or {}
                geo = loc.get("geolocation") or {}
                found.setdefault(lid, {
                    "id": lid, "name": loc.get("name") or loc.get("chain") or "Kroger",
                    "chain": loc.get("chain") or "", "address": addr.get("addressLine1", ""),
                    "city": addr.get("city", ""), "zip": str(addr.get("zipCode") or "")[:5],
                    "lat": geo.get("latitude"), "lon": geo.get("longitude"), "area": area.name,
                })
        locs = list(found.values())
        if not wanted:
            from ..geo import miles, place_point
            def dist(l):
                pt = place_point(l["lat"], l["lon"], l["zip"])
                ds = [miles(pt, (a.lat, a.lon)) for a in self.areas if a.located]
                ds = [d for d in ds if d is not None]
                return min(ds) if ds else 0
            locs.sort(key=dist)
            locs = locs[: int(self.rcfg.get("max_stores") or 5)]
        self._locations, self._locations_at = locs, time.time()
        return locs

    def stores_near(self, areas) -> list:
        from ..places import Place
        self._locations_at = 0
        return [Place("kroger", l["name"], l["lat"], l["lon"], l["address"], l["city"], l["zip"], l["id"], "chain")
                for l in self.locations()]

    # ---- products -------------------------------------------------------------------
    @staticmethod
    def _parse(p: dict) -> tuple[dict, dict]:
        item = (p.get("items") or [{}])[0]
        desc, brand = str(p.get("description") or ""), str(p.get("brand") or "")
        title = desc if (not brand or brand.lower() in desc.lower()) else f"{brand} {desc}"
        return item, {
            "title": title,
            "upc": normalize_upc(p.get("upc")),
            "price": parse_price(dig(item, "price", "promo")) or parse_price(dig(item, "price", "regular")),
            "image": _image(p),
        }

    def _result(self, pid: str, info: dict) -> StockResult:
        return StockResult(
            retailer=self.name, retailer_name=self.display, product_id=pid, title=info["title"] or f"Kroger {pid}",
            url=f"https://www.kroger.com/p/-/{pid}", price=info["price"], upc=info["upc"] or None,
            image=info["image"], online=False, online_status="In-store item", third_party=False,
        )

    def check_ids(self, ids: list[str], in_store: bool) -> dict[str, StockResult]:
        ids = [i for i in dict.fromkeys(x.strip() for x in ids) if i.isdigit()]
        out: dict[str, StockResult] = {}
        if not ids:
            return out
        locs = self.locations() if self.in_store_enabled() else []   # Kroger stock is per store
        if not locs:
            for i in range(0, len(ids), 50):
                data = self._api("products", **{"filter.productId": ",".join(ids[i:i + 50]), "filter.limit": 50})
                for p in data.get("data") or []:
                    _, info = self._parse(p)
                    out[str(p.get("productId"))] = self._result(str(p.get("productId")), info)
            return out
        for loc in locs:
            for i in range(0, len(ids), 50):
                data = self._api("products", **{"filter.productId": ",".join(ids[i:i + 50]),
                                                "filter.locationId": loc["id"], "filter.limit": 50})
                for p in data.get("data") or []:
                    pid = str(p.get("productId"))
                    item, info = self._parse(p)
                    res = out.get(pid) or self._result(pid, info)
                    out[pid] = res
                    level = str(dig(item, "inventory", "stockLevel", default="")).upper()
                    ful = item.get("fulfillment") or {}
                    if level in GOOD_LEVELS and ful.get("inStore", True) is not False:
                        res.stores.append(StoreStock(
                            store_id=loc["id"], name=loc["name"], address=loc["address"], zip=loc["zip"],
                            lat=_f(loc["lat"]), lon=_f(loc["lon"]), level=level.lower(),
                            pickup=bool(ful.get("curbside")), via_area=loc["area"], chain="kroger",
                        ))
        return out

    def resolve_upc(self, upc: str) -> str | None:
        want = normalize_upc(upc)
        for pid in kroger_product_ids(upc):
            data = self._api("products", **{"filter.productId": pid, "filter.limit": 1})
            for p in data.get("data") or []:
                got = normalize_upc(p.get("upc"))
                if got and (got == want or got == want[:-1] or want == got[:-1]):
                    return str(p.get("productId"))
        return None

    def search(self, query: str, limit: int) -> list[StockResult]:
        locs = self.locations() if self.in_store_enabled() else []
        params = {"filter.term": query[:60], "filter.limit": min(limit, 50)}
        if locs:
            params["filter.locationId"] = locs[0]["id"]
        data = self._api("products", **params)
        out = []
        for p in data.get("data") or []:
            pid = str(p.get("productId"))
            _, info = self._parse(p)
            res = self._result(pid, info)
            res.online_status = "UNCHECKED"   # stock is checked across all your stores afterwards
            out.append(res)
        return out


def _image(p: dict) -> str | None:
    for img in p.get("images") or []:
        if img.get("perspective") == "front" or img.get("featured"):
            sizes = img.get("sizes") or []
            for want in ("large", "medium", "xlarge", "small"):
                for s in sizes:
                    if s.get("size") == want and s.get("url"):
                        return s["url"]
    return None


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
