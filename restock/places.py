"""Finds the stores around your areas that sell Pokemon cards.

Two sources, merged:
  * The chains' own store finders, for chains the monitor can check live
    (Target, Best Buy, Kroger family). These carry the store numbers that stock
    checks use.
  * OpenStreetMap, through the public Overpass API, for every chain on the
    list below. This finds GameStop, Walgreens, CVS, Costco, Five Below and the
    rest so they show on your store list even when their shelves can't be
    checked online.

What leaves your PC: for OpenStreetMap, a rough circle (the ZIP's center point
and radius); for chain finders, the ZIP code. Results are cached in
data/places.json and refreshed weekly or when your areas change.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import asdict, dataclass

import requests

from .geo import Area, miles, nearest_area, zip_point
from .util import atomic_write_json, normalize_text, read_json

OVERPASS_URLS = ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter")
REFRESH_S = 7 * 86400
UA = "PokeRestockMonitor/1.0 (personal restock monitor; store list refresh about weekly)"


@dataclass(frozen=True)
class Chain:
    key: str
    name: str
    match: tuple[str, ...]        # normalized brand/name values that identify the chain in OpenStreetMap
    coverage: str                 # "live" (shelf stock checked), "online" (website checked), "listed" (shown only)
    retailer: str | None = None   # checker that covers it
    note: str = ""


CHAINS: tuple[Chain, ...] = (
    Chain("target", "Target", ("target",), "live", "target", "Shelf quantity per store, order pickup"),
    Chain("bestbuy", "Best Buy", ("best buy",), "live", "bestbuy", "In-store availability and pickup (API key)"),
    Chain("kroger", "Kroger family", ("kroger", "fred meyer", "ralphs", "smith s", "smiths", "king soopers", "fry s",
                                      "frys food and drug", "qfc", "dillons", "harris teeter", "food 4 less", "foods co",
                                      "pick n save", "mariano s", "metro market", "baker s", "city market", "gerbes",
                                      "jay c", "pay less", "owen s"),
          "live", "kroger", "Stock level per store (free API key)"),
    Chain("walmart", "Walmart", ("walmart", "walmart supercenter", "walmart neighborhood market"), "online", "walmart",
          "Online stock; pickup at the store set in the checking browser"),
    Chain("gamestop", "GameStop", ("gamestop",), "online", "gamestop", "Online stock from product links; store pickup stock for your areas (experimental)"),
    Chain("walgreens", "Walgreens", ("walgreens",), "online", "walgreens", "Online listings from product links; exact store locations with a developer key"),
    Chain("cvs", "CVS", ("cvs", "cvs pharmacy"), "live", "cvs", "Shelf count per store around your areas (needs your own Chrome)"),
    Chain("costco", "Costco", ("costco", "costco wholesale"), "online", "costco", "Bundles go live online first"),
    Chain("samsclub", "Sam's Club", ("sam s club", "sams club"), "online", "samsclub", "Online listings from product links"),
    Chain("barnesandnoble", "Barnes & Noble", ("barnes and noble", "barnes noble"), "online", "barnesandnoble", "Online listings from product links"),
    Chain("booksamillion", "Books-A-Million", ("books a million",), "online", "booksamillion", "Online listings from product links"),
    Chain("dicks", "Dick's Sporting Goods", ("dick s sporting goods", "dicks sporting goods"), "online", "dicks",
          "Pokemon section online, found automatically; pickup at stores"),
    Chain("safeway", "Safeway / Albertsons", ("safeway", "albertsons", "vons", "pavilions", "randalls", "tom thumb",
                                             "jewel osco", "acme markets", "shaw s", "star market"), "online", "safeway",
          "Packs and blisters online; set your store in the checking browser"),
    Chain("raleys", "Raley's", ("raley s", "raleys", "nob hill foods"), "online", "raleys",
          "Online listings from product links (untested)"),
    Chain("fivebelow", "Five Below", ("five below",), "listed", None, "In store only; small items and tins"),
    Chain("dollargeneral", "Dollar General", ("dollar general",), "listed", None, "In store only; packs, often stocked Mondays"),
    Chain("meijer", "Meijer", ("meijer",), "listed", None, "Midwest only"),
    Chain("michaels", "Michaels", ("michaels",), "listed", None, "Some locations"),
    Chain("hobbylobby", "Hobby Lobby", ("hobby lobby",), "listed", None, "Some locations"),
    Chain("scheels", "Scheels", ("scheels",), "listed", None, "Trading card section, mixed with sports cards"),
)
CHAIN_BY_KEY = {c.key: c for c in CHAINS}
_PHARMACY_CHAINS = {"walgreens", "cvs"}
_SKIP_WORDS = ("pharmacy", "optical", "fuel", "gas", "tire", "auto care", "vision", "photo", "liquor", "money center",
               "mobile", "starbucks", "pickup point", "distribution", "warehouse store #")


def chain_for(brand: str, name: str = "") -> Chain | None:
    b, n = normalize_text(brand), normalize_text(name)
    for c in CHAINS:
        for m in c.match:
            if b == m or n == m or (b and b.startswith(m + " ")) or (n and n.startswith(m + " ")):
                return c
    return None


@dataclass
class Place:
    chain: str
    name: str
    lat: float | None
    lon: float | None
    address: str = ""
    city: str = ""
    zip: str = ""
    store_id: str = ""            # the chain's own store number, when known
    source: str = "osm"           # osm | chain
    area: str = ""
    distance: float | None = None

    @property
    def key(self) -> str:
        return f"{self.chain}:{self.store_id}" if self.store_id else f"{self.chain}:{self.lat:.4f},{self.lon:.4f}"


def overpass_query(areas: list[Area]) -> str:
    names = sorted({m for c in CHAINS for m in c.match})

    def loose(n: str) -> str:
        # OpenStreetMap keeps the real punctuation ("Smith's", "Barnes & Noble"); match it loosely,
        # then chain_for() checks each result exactly.
        out = ""
        for i, w in enumerate(n.split(" ")):
            if w == "and":
                out += "[^A-Za-z0-9]*(&|and)?"
            else:
                out += ("[^A-Za-z0-9]*" if i else "") + re.escape(w)
        return out

    words = sorted({loose(n) for n in names}, key=len, reverse=True)
    rx = "^(" + "|".join(words) + ")"
    parts = []
    for a in areas:
        if not a.located:
            continue
        r = int(a.radius * 1609.34)
        parts.append(f'nwr["shop"]["brand"~"{rx}",i](around:{r},{a.lat:.4f},{a.lon:.4f});')
        parts.append(f'nwr["shop"]["name"~"{rx}",i](around:{r},{a.lat:.4f},{a.lon:.4f});')
        parts.append(f'nwr["amenity"="pharmacy"]["brand"~"^(Walgreens|CVS)",i](around:{r},{a.lat:.4f},{a.lon:.4f});')
    return "[out:json][timeout:40];(" + "".join(parts) + ");out center tags;"


def parse_overpass(data: dict) -> list[Place]:
    out = []
    for el in data.get("elements") or []:
        tags = el.get("tags") or {}
        lat = el.get("lat", (el.get("center") or {}).get("lat"))
        lon = el.get("lon", (el.get("center") or {}).get("lon"))
        if lat is None or lon is None:
            continue
        chain = chain_for(tags.get("brand", ""), tags.get("name", ""))
        if chain is None:
            continue
        name = tags.get("name") or chain.name
        low = normalize_text(name)
        if any(w in low for w in _SKIP_WORDS) and not (chain.key in _PHARMACY_CHAINS and "pharmacy" in low):
            continue
        if tags.get("amenity") == "pharmacy" and chain.key not in _PHARMACY_CHAINS:
            continue
        street = " ".join(x for x in (tags.get("addr:housenumber"), tags.get("addr:street")) if x)
        out.append(Place(chain.key, name, float(lat), float(lon), street, tags.get("addr:city", ""),
                         tags.get("addr:postcode", "")[:5], tags.get("ref", "") if chain.key == "target" else "", "osm"))
    return _dedupe(out, 0.15)


def _dedupe(places: list[Place], within_miles: float) -> list[Place]:
    """Drop near-duplicates: the same store mapped as a point and a building, or a
    pharmacy counter inside another chain's store."""
    kept: list[Place] = []
    for p in sorted(places, key=lambda x: (x.source != "chain", x.chain in _PHARMACY_CHAINS)):
        dup = False
        for k in kept:
            d = miles((p.lat, p.lon), (k.lat, k.lon)) if p.lat is not None and k.lat is not None else None
            if d is None:
                continue
            if k.chain == p.chain and d < within_miles:
                dup = True
                break
            if p.chain in _PHARMACY_CHAINS and k.chain not in _PHARMACY_CHAINS and d < 0.05:
                dup = True   # a CVS counter inside a Target is not a CVS store
                break
        if not dup:
            kept.append(p)
    return kept


class PlaceFinder:
    def __init__(self, data_dir: str, log: logging.Logger):
        self.path = os.path.join(data_dir, "places.json")
        self.log = log
        self.lock = threading.Lock()
        saved = read_json(self.path, {})
        self.places: list[Place] = [Place(**p) for p in saved.get("places", []) if isinstance(p, dict)]
        self.signature = saved.get("signature", "")
        self.updated = float(saved.get("updated", 0))
        self.last_error = ""

    @staticmethod
    def area_signature(areas: list[Area]) -> str:
        return json.dumps([[a.zip, a.radius] for a in areas])

    def stale(self, areas: list[Area]) -> bool:
        return self.signature != self.area_signature(areas) or time.time() - self.updated > REFRESH_S

    def assign(self, areas: list[Area]) -> None:
        for p in self.places:
            pt = (p.lat, p.lon) if p.lat is not None else zip_point(p.zip)
            area, d = nearest_area(pt, areas)
            p.area, p.distance = (area.name, round(d, 1)) if area else ("", None)

    def refresh(self, areas: list[Area], chain_sources: list | None = None) -> int:
        """Rebuild the store list. chain_sources: callables(areas) -> list[Place]."""
        found: list[Place] = []
        errors = []
        for source in chain_sources or []:
            try:
                found.extend(source(areas))
            except Exception as exc:
                errors.append(f"{getattr(source, '__self__', source).__class__.__name__}: {exc}")
        if any(a.located for a in areas):
            try:
                found.extend(self._overpass(areas))
            except Exception as exc:
                errors.append(f"OpenStreetMap: {exc.__class__.__name__}")
        else:
            errors.append("ZIP lookup unavailable (install the zipcodes package), so OpenStreetMap search was skipped")
        if not found and errors:
            self.last_error = "; ".join(errors)
            raise RuntimeError(self.last_error)
        merged = _dedupe(found, 0.15)
        with self.lock:
            self.places = merged
            self.assign(areas)
            self.places = [p for p in self.places if p.area]
            self.places.sort(key=lambda p: (p.distance if p.distance is not None else 999, p.chain))
            self.signature = self.area_signature(areas)
            self.updated = time.time()
            self.last_error = "; ".join(errors)
            atomic_write_json(self.path, {"signature": self.signature, "updated": self.updated,
                                          "places": [asdict(p) for p in self.places]})
        return len(self.places)

    def _overpass(self, areas: list[Area]) -> list[Place]:
        q = overpass_query(areas)
        last = None
        for url in OVERPASS_URLS:
            try:
                resp = requests.post(url, data={"data": q}, timeout=60, headers={"User-Agent": UA})
                if resp.status_code == 200:
                    return parse_overpass(resp.json())
                last = f"HTTP {resp.status_code}"
            except (requests.RequestException, ValueError) as exc:
                last = exc.__class__.__name__
        raise ConnectionError(last or "no response")

    def summary(self) -> dict:
        with self.lock:
            places = [asdict(p) | {"key": p.key} for p in self.places]
        return {"places": places, "updated": self.updated, "error": self.last_error,
                "chains": [asdict(c) for c in CHAINS]}
