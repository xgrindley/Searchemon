"""Page-based checkers for stores without a stock API.

Pokemon Center, GameStop, Costco, Sam's Club, Barnes & Noble, Books-A-Million,
Amazon, Walgreens, CVS, plus any other product link. Each reads the product
data stores publish for search engines (schema.org JSON-LD: name, price,
availability, seller). Amazon has its own reader because it does not publish
that data. Paste product links under a product's links; links are routed to
the right store automatically.

Sites with heavy bot protection may refuse plain requests. In "auto" mode the
checker then switches to the real browser (see browser.py), and asks you to
finish a check yourself if the site wants a person.
"""
from __future__ import annotations

import html as htmllib
import json
import random
import re
from urllib.parse import urlsplit

from ..models import StockResult
from ..util import clean_url, normalize_text, normalize_upc, parse_price
from .base import Retailer

LD_JSON = re.compile(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)
OG_TITLE = re.compile(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', re.I)
TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
TAGS = re.compile(r"<[^>]+>")

IN_STOCK = ("instock", "limitedavailability", "preorder", "presale", "onlineonly", "instoreonly")
OUT_STOCK = ("outofstock", "soldout", "discontinued", "backorder")

KNOWN_SITES = {
    "pokemoncenter.com": "Pokemon Center",
    "gamestop.com": "GameStop",
    "costco.com": "Costco",
    "samsclub.com": "Sam's Club",
    "barnesandnoble.com": "Barnes & Noble",
    "booksamillion.com": "Books-A-Million",
    "amazon.com": "Amazon",
    "walgreens.com": "Walgreens",
    "cvs.com": "CVS",
    "meijer.com": "Meijer",
    "kohls.com": "Kohl's",
    "fivebelow.com": "Five Below",
    "dickssportinggoods.com": "Dick's Sporting Goods",
    "safeway.com": "Safeway",
    "raleys.com": "Raley's",
    "scheels.com": "Scheels",
}


def site_name(url: str) -> str:
    host = urlsplit(url).netloc.lower().removeprefix("www.")
    for domain, name in KNOWN_SITES.items():
        if host == domain or host.endswith("." + domain):
            return name
    return host or "Web"


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def page_text(fragment: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(TAGS.sub(" ", fragment))).strip()


def parse_product_page(html: str, patterns: dict | None = None) -> dict:
    """Pull title, price, upc, seller and availability out of a product page."""
    info = {"title": None, "price": None, "upc": None, "status": None, "image": None,
            "preorder": False, "seller": None}
    for block in LD_JSON.findall(html):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        for node in _walk(data):
            types = node.get("@type")
            types = types if isinstance(types, list) else [types]
            if "Product" in types:
                info["title"] = info["title"] or node.get("name")
                info["upc"] = info["upc"] or node.get("gtin12") or node.get("gtin13") or node.get("gtin")
                img = node.get("image")
                info["image"] = info["image"] or (img[0] if isinstance(img, list) and img else img if isinstance(img, str) else None)
            if "Offer" in types or "AggregateOffer" in types or "availability" in node:
                avail = normalize_text(str(node.get("availability") or "")).replace(" ", "")
                if avail:
                    if any(k in avail for k in IN_STOCK):
                        info["status"] = "in"
                        info["preorder"] = info["preorder"] or "preorder" in avail or "presale" in avail
                    elif any(k in avail for k in OUT_STOCK) and info["status"] != "in":
                        info["status"] = "out"
                price = parse_price(node.get("price") or node.get("lowPrice"))
                if price and not info["price"]:
                    info["price"] = price
                seller = node.get("seller")
                if isinstance(seller, dict) and seller.get("name") and not info["seller"]:
                    info["seller"] = str(seller["name"])

    if not info["title"]:
        m = OG_TITLE.search(html) or TITLE.search(html)
        info["title"] = htmllib.unescape(re.sub(r"\s+", " ", m.group(1))).strip() if m else None

    patterns = patterns or {}
    if info["status"] is None and (patterns.get("in_stock_text") or patterns.get("out_of_stock_text")):
        text = normalize_text(page_text(html))
        outs = [normalize_text(p) for p in patterns.get("out_of_stock_text") or []]
        ins = [normalize_text(p) for p in patterns.get("in_stock_text") or []]
        if any(p and p in text for p in outs):
            info["status"] = "out"
        elif any(p and p in text for p in ins):
            info["status"] = "in"
    return info


def _slice(html: str, marker: str, size: int = 2500) -> str:
    i = html.find(marker)
    return html[i:i + size] if i >= 0 else ""


def parse_amazon(html: str) -> dict:
    """Amazon pages carry no JSON-LD, so read the buy box directly."""
    info = {"title": None, "price": None, "upc": None, "status": None, "image": None,
            "preorder": False, "seller": None}
    m = re.search(r'id="productTitle"[^>]*>(.*?)</span>', html, re.S)
    info["title"] = page_text(m.group(1)) if m else None
    avail = normalize_text(page_text(_slice(html, 'id="availability"', 1500)))
    buybox = page_text(_slice(html, 'id="tabular-buybox"', 3000) or _slice(html, 'id="merchant-info"', 1500)
                       or _slice(html, 'id="offer-display-feature', 3000))
    if any(w in avail for w in ("currently unavailable", "temporarily out of stock", "out of stock")):
        info["status"] = "out"
    elif any(w in avail for w in ("in stock", "left in stock", "available to ship", "usually ships")):
        info["status"] = "in"
    if 'id="buy-now-button"' not in html and 'id="add-to-cart-button"' not in html and info["status"] == "in":
        info["status"] = "out"     # an "in stock" line with no buy button = only other sellers
    if "pre order" in normalize_text(page_text(_slice(html, 'id="buy-now-button"', 600))) or "this item will be released" in avail:
        info["preorder"] = True
    m = re.search(r'class="a-offscreen">\s*\$?([\d,]+\.\d\d)', _slice(html, 'id="corePrice', 4000) or html)
    info["price"] = parse_price(m.group(1)) if m else None
    sold = re.search(r"sold by\s+([A-Za-z0-9 .&'\-]{2,40})", buybox, re.I)
    if sold:
        info["seller"] = sold.group(1).strip()
    elif "ships from and sold by amazon" in normalize_text(buybox):
        info["seller"] = "Amazon.com"
    return info


class WebPage(Retailer):
    """Any product URL. Put URLs under a product's links."""
    name = "web"
    display = "Other sites"
    default_fetch_mode = "auto"
    domains: tuple[str, ...] = ()
    own_seller_names: tuple[str, ...] = ()      # seller names that mean "sold by the store itself"

    def url_for(self, ident: str) -> str:
        return ident

    def parse(self, html: str, url: str) -> dict:
        return parse_product_page(html, self.rcfg)

    def third_party(self, seller: str | None) -> bool | None:
        if not seller or not self.own_seller_names:
            return None
        s = normalize_text(seller)
        return not any(normalize_text(o) in s for o in self.own_seller_names)

    def check_ids(self, ids: list[str], in_store: bool) -> dict[str, StockResult]:
        out = {}
        for ident in ids:
            url = clean_url(self.url_for(ident.strip()))
            if not url.startswith("http"):
                continue
            resp = self.fetch_html(url)
            if resp.status == 404:
                continue
            self.dump(urlsplit(url).path.strip("/").replace("/", "_") or "page", resp.text[:300000])
            if resp.block is not None and resp.block.kind == "queue":
                out[ident] = StockResult(self.name, self.display if self.name != "web" else site_name(url), ident,
                                         ident, url, online=False, online_status="Queue active (drop starting)")
                continue
            info = self.parse(resp.text, url)
            status = info["status"]
            out[ident] = StockResult(
                retailer=self.name,
                retailer_name=site_name(url) if self.name == "web" else self.display,
                product_id=ident,
                title=info["title"] or url,
                url=url,
                price=info["price"],
                upc=normalize_upc(info["upc"]) or None,
                online=status == "in",
                online_status=("Pre-order" if info.get("preorder") and status == "in" else
                               {"in": "In stock", "out": "Out of stock"}.get(status, "Unknown (no stock data on page)")),
                image=info["image"],
                third_party=self.third_party(info.get("seller")),
                preorder=bool(info.get("preorder")),
            )
            self.pause(self.link_delay())
        return out


class PokemonCenter(WebPage):
    name = "pokemoncenter"
    display = "Pokemon Center"
    default_fetch_mode = "browser"
    domains = ("pokemoncenter.com",)
    own_seller_names = ("pokemon center",)
    HOME = "https://www.pokemoncenter.com/"

    def signals(self) -> list[dict]:
        """The waiting-room queue usually opens minutes before product goes live."""
        if not self.rcfg.get("watch_queue", True):
            return []
        resp = self.fetch_html(self.HOME)
        active = resp.block is not None and resp.block.kind == "queue"
        return [{"kind": "queue", "site": self.name, "display": self.display, "active": active, "url": self.HOME}]


_GS_BASE = "https://www.gamestop.com/on/demandware.store/Sites-gamestop-us-Site/default/"
# GameStop does not publish its store-stock call, so a few likely shapes are tried in turn and the
# first one that returns store rows is remembered. If none is readable, the response is saved
# to data\\debug so the reader can be adjusted.
_GS_ENDPOINTS = (
    _GS_BASE + "Stores-FindStores?showMap=false&radius={radius}&postalCode={zip}&products={pid}:1",
    _GS_BASE + "Stores-InventorySearch?pid={pid}&radius={radius}&postalCode={zip}&showMap=false",
)
_GS_ID = ("storeId", "storeID", "storeNumber", "ID", "id")
_GS_QTY = ("storeQuantity", "quantity", "availableQuantity", "ats", "inventory", "qty")
_GS_FLAG = ("inStockAtStore", "inStock", "available", "isAvailable")
_GS_OUT = ("out_of_stock", "outofstock", "not_available", "unavailable", "none", "sold_out")


def gamestop_product_id(ident: str) -> str:
    m = re.search(r"/(\d{4,})(?:\.html)?(?:[/?#]|$)", ident)
    return m.group(1) if m else (ident if ident.isdigit() else "")


def _pick(node: dict, keys) -> object:
    for k in keys:
        if node.get(k) not in (None, ""):
            return node[k]
    return None


def json_from_page(text: str):
    """A JSON answer loaded in a browser arrives wrapped in a page; pull the JSON back out."""
    body = htmllib.unescape(TAGS.sub("", text or "")).strip()
    for a, b in (("{", "}"), ("[", "]")):
        i, j = body.find(a), body.rfind(b)
        if 0 <= i < j:
            try:
                return json.loads(body[i:j + 1])
            except ValueError:
                continue
    return None


def parse_gamestop_stores(data, area_name: str = "") -> list:
    """Store rows with stock out of whatever shape GameStop answers with. A row counts when it has
    a store number and says there is stock (a count above zero, a yes flag, or a level word)."""
    from ..models import StoreStock
    found: dict[str, StoreStock] = {}
    for node in _walk(data):
        sid = _pick(node, _GS_ID)
        if sid is None or isinstance(sid, (dict, list)):
            continue
        qty_raw = _pick(node, _GS_QTY)
        flag = _pick(node, _GS_FLAG)
        level_raw = _pick(node, ("stockLevel", "availabilityStatus", "availability", "status"))
        if qty_raw is None and flag is None and level_raw is None:
            continue
        try:
            qty = int(float(qty_raw)) if qty_raw is not None else None
        except (TypeError, ValueError):
            qty = None
        level = normalize_text(str(level_raw or "")).replace(" ", "_")
        if qty is not None and qty > 0:
            ok = True
        elif flag is not None:
            ok = str(flag).lower() in ("true", "1", "yes", "y")
        else:
            ok = bool(level) and not any(o in level for o in _GS_OUT) and any(
                w in level for w in ("in_stock", "instock", "low", "limited", "available", "orderable"))
        if not ok:
            continue
        addr = node.get("storeAddress") or node.get("address") or node.get("address1") or ""
        if isinstance(addr, dict):
            addr = addr.get("address1") or addr.get("street") or ""
        dist = _pick(node, ("storeDistanceMiles", "distance", "distanceMiles"))
        try:
            dist = float(dist) if dist is not None else None
        except (TypeError, ValueError):
            dist = None
        zip_ = str(_pick(node, ("storeZip", "postalCode", "zip", "zipCode")) or "")[:5]
        lat, lon = _pick(node, ("latitude", "lat")), _pick(node, ("longitude", "lng", "lon"))
        found[str(sid)] = StoreStock(
            store_id=str(sid),
            name=str(_pick(node, ("storeName", "name")) or f"GameStop {sid}"),
            distance=dist, qty=qty if qty and qty > 0 else None,
            address=str(addr).split(",")[0],
            pickup=True if _pick(node, ("pickupEligible", "inStorePickup")) in (True, "true", 1) else None,
            zip=zip_, lat=float(lat) if lat not in (None, "") else None,
            lon=float(lon) if lon not in (None, "") else None,
            level="low" if "low" in level else "", via_area=area_name, chain="gamestop")
    return list(found.values())


class GameStop(WebPage):
    name = "gamestop"
    display = "GameStop"
    domains = ("gamestop.com",)
    own_seller_names = ("gamestop",)
    supports_in_store = True
    _store_ep = -1             # which entry of _GS_ENDPOINTS worked
    _warned_stores = False

    def store_stock(self, pid: str) -> list:
        allowed = {str(s) for s in self.rcfg.get("store_ids") or [] if str(s).strip()}
        found: dict[str, object] = {}
        tried_any = False
        for area in self.areas:
            order = ([self._store_ep] if self._store_ep >= 0 else []) + [
                i for i in range(len(_GS_ENDPOINTS)) if i != self._store_ep]
            for i in order:
                url = _GS_ENDPOINTS[i].format(zip=area.zip, radius=int(area.radius), pid=pid)
                resp = self.fetch_html(url)
                tried_any = True
                data = json_from_page(resp.text)
                rows = parse_gamestop_stores(data, area.name) if data is not None else []
                has_rows = any(isinstance(n, dict) and _pick(n, _GS_ID) is not None for n in _walk(data)) if data is not None else False
                if rows or has_rows:
                    self._store_ep = i
                    for r in rows:
                        if allowed and r.store_id not in allowed:
                            continue
                        prev = found.get(r.store_id)
                        if prev is None or (r.distance or 999) < (prev.distance or 999):
                            found[r.store_id] = r
                    break
                self.pause(1.0)
            self.pause(self.link_delay())
        if tried_any and self._store_ep < 0 and not self._warned_stores:
            self._warned_stores = True
            self.log.warning("GameStop store stock: no readable answer from GameStop's store lookup. "
                             "Saved the last response to data\\debug so the reader can be adjusted.")
            self.dump(f"stores_{pid}", resp.text[:200000], force=True)
        return sorted(found.values(), key=lambda s: s.distance if s.distance is not None else 999)

    def check_ids(self, ids: list[str], in_store: bool) -> dict[str, StockResult]:
        out = super().check_ids(ids, in_store)
        if in_store and self.in_store_enabled():
            for ident, res in out.items():
                pid = gamestop_product_id(ident)
                if pid:
                    res.stores = self.store_stock(pid)
        return out


class Costco(WebPage):
    name = "costco"
    display = "Costco"
    domains = ("costco.com",)


class SamsClub(WebPage):
    name = "samsclub"
    display = "Sam's Club"
    domains = ("samsclub.com",)
    own_seller_names = ("sam s club", "sams club")


class BarnesAndNoble(WebPage):
    name = "barnesandnoble"
    display = "Barnes & Noble"
    domains = ("barnesandnoble.com",)


class BooksAMillion(WebPage):
    name = "booksamillion"
    display = "Books-A-Million"
    domains = ("booksamillion.com",)


class Amazon(WebPage):
    name = "amazon"
    display = "Amazon"
    default_fetch_mode = "browser"
    domains = ("amazon.com",)
    own_seller_names = ("amazon.com", "amazon")

    def url_for(self, ident: str) -> str:
        if ident.startswith("http"):
            return ident
        return f"https://www.amazon.com/dp/{ident}"

    def parse(self, html: str, url: str) -> dict:
        return parse_amazon(html)

    def third_party(self, seller: str | None) -> bool | None:
        if not seller:
            return True    # no seller shown = no Amazon offer in the buy box
        return normalize_text(seller) not in ("amazon com", "amazon")


DICKS_LINK = re.compile(r'href="(/p/([a-z0-9-]+)/([a-z0-9]+))"[^>]*>(.*?)</a>', re.S | re.I)


def parse_dicks_listing(html: str) -> list[tuple[str, str]]:
    """(product url, title) pairs from a Dick's category or search page."""
    out: dict[str, str] = {}
    for path, slug, _pid, inner in DICKS_LINK.findall(html):
        text = page_text(inner)
        if len(text) < 8:   # image-only links: build a title from the URL slug
            words = slug.split("-")
            if words and re.fullmatch(r"[a-z0-9]{12,}", words[-1]):
                words = words[:-1]
            text = " ".join(words).title().replace("Pokmon", "Pokemon").replace("Tcg", "TCG").replace("Etb", "ETB")
        url = "https://www.dickssportinggoods.com" + path
        if url not in out or len(text) > len(out[url]):
            out[url] = text
    return list(out.items())


class DicksSportingGoods(WebPage):
    """Dick's sells Pokemon TCG in its trading card section. The site only renders
    with JavaScript, so it is checked through the browser."""
    name = "dicks"
    display = "Dick's Sporting Goods"
    default_fetch_mode = "browser"
    domains = ("dickssportinggoods.com",)
    own_seller_names = ("dick s", "dicks")
    supports_search = True
    CATEGORY = "https://www.dickssportinggoods.com/f/pokemon-trading-cards"

    _listing: tuple[float, list] = (0.0, [])

    def search(self, query: str, limit: int) -> list[StockResult]:
        # One category page lists their Pokemon products, so the query is not needed
        # and the page is reused for 10 minutes.
        import time as _t
        if _t.time() - self._listing[0] > 600:
            resp = self.fetch_html(self.CATEGORY)
            items = parse_dicks_listing(resp.text)
            self.dump("category", resp.text[:300000], force=not items)
            if not items:
                self.log.warning("Dick's Pokemon page listed no products (%d characters). Saved it to data\\debug.",
                                 len(resp.text or ""))
            self._listing = (_t.time(), items)
        return [StockResult(self.name, self.display, url, title, url, online_status="UNCHECKED")
                for url, title in self._listing[1][:limit]]


class Safeway(WebPage):
    """Safeway and the other Albertsons stores. Product pages reflect the store chosen
    in the checking browser, so pick your nearest Safeway there once."""
    name = "safeway"
    display = "Safeway"
    default_fetch_mode = "browser"
    domains = ("safeway.com", "albertsons.com", "vons.com", "pavilions.com", "randalls.com", "tomthumb.com",
               "jewelosco.com", "acmemarkets.com", "shaws.com", "starmarket.com")


class Raleys(WebPage):
    """Raley's online listings (Reno, Sparks and Northern California). Untested: if its
    pages carry no stock data, add in/out-of-stock words under Other sites."""
    name = "raleys"
    display = "Raley's"
    domains = ("raleys.com",)


class Walgreens(WebPage):
    """Walgreens online listing. Accepts a full product URL or a 'prod1234567' id."""
    name = "walgreens"
    display = "Walgreens"
    domains = ("walgreens.com",)

    def url_for(self, ident: str) -> str:
        if ident.startswith("http"):
            return ident
        pid = ident if ident.startswith("prod") else f"prod{ident}"
        return f"https://www.walgreens.com/store/c/-/ID={pid}-product"


_CVS_STOCK_URL = "https://www.cvs.com/RETAGPV3/Inventory/V1/getStoreDetailsAndInventory"
# The key CVS's own web page sends with every store lookup. It is the same for every visitor;
# retailers.cvs.api_key overrides it if CVS ever changes it.
_CVS_PUBLIC_KEY = "a2ff75c6-2da7-4299-929d-d670d827ab4a"


def cvs_product_id(ident: str) -> str:
    m = re.search(r"prodid-(\d+)", ident)
    return m.group(1) if m else (ident if ident.isdigit() else "")


def cvs_stock_request(pid: str, zip_code: str, api_key: str = _CVS_PUBLIC_KEY) -> dict:
    return {"getStoreDetailsAndInventoryRequest": {
        "header": {"apiKey": api_key, "channelName": "WEB", "deviceToken": "%016x" % random.getrandbits(64),
                   "deviceType": "DESKTOP", "responseFormat": "JSON", "securityType": "apiKey",
                   "source": "CVS_WEB", "appName": "CVS_WEB", "lineOfBusiness": "RETAIL", "type": "rdp"},
        "productId": pid, "geolatitude": "", "geolongitude": "", "addressLine": zip_code}}


def parse_cvs_stores(data, area_name: str = "", radius: float | None = None) -> list:
    """Stores with stock out of CVS's nearby-store answer: shelf count, pickup and distance per store."""
    from ..models import StoreStock
    rows = data.get("atgResponse") if isinstance(data, dict) else None
    out = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        try:
            qty = int(r.get("Qty") or 0)
        except (TypeError, ValueError):
            qty = 0
        in_stock = qty > 0 or str(r.get("bohStatus", "")).lower() == "in stock"
        try:
            dist = float(r.get("dt")) if r.get("dt") not in (None, "") else None
        except (TypeError, ValueError):
            dist = None
        if not in_stock or (radius and dist is not None and dist > radius):
            continue
        try:
            pick_qty = int((r.get("bopus") or {}).get("Qty") or 0)
        except (TypeError, ValueError):
            pick_qty = 0
        city = str(r.get("City") or "").title()
        out.append(StoreStock(
            store_id=str(r.get("storeId") or ""), name=f"CVS {city}".strip(), distance=dist,
            qty=qty if qty > 0 else None, address=str(r.get("storeAddress") or "").title(),
            pickup=pick_qty > 0, zip=str(r.get("Zipcode") or "")[:5], via_area=area_name, chain="cvs",
            level="low" if 0 < qty <= 2 else ""))
    return [x for x in out if x.store_id]


class CVS(WebPage):
    """CVS online listing, plus shelf counts at stores around your area ZIPs. Accepts a full
    product URL or the numeric prodid."""
    name = "cvs"
    display = "CVS"
    domains = ("cvs.com",)

    def url_for(self, ident: str) -> str:
        if ident.startswith("http"):
            return ident
        return f"https://www.cvs.com/shop/-prodid-{ident.removeprefix('prodid-')}"

    supports_in_store = True
    _warned_stores = False

    def store_stock(self, pid: str, referer: str) -> list:
        allowed = {str(x) for x in self.rcfg.get("store_ids") or [] if str(x).strip()}
        key = str(self.rcfg.get("api_key") or _CVS_PUBLIC_KEY)
        found: dict[str, object] = {}
        for area in self.areas:
            resp = self.post_via_browser(_CVS_STOCK_URL, cvs_stock_request(pid, area.zip, key), referer)
            data = None
            try:
                data = json.loads(resp.text)
            except ValueError:
                pass
            if not isinstance(data, dict) or "atgResponse" not in data:
                if not self._warned_stores:
                    self._warned_stores = True
                    self.log.warning("CVS store stock: unreadable answer for ZIP %s (status %s). Saved it to data\\debug.",
                                     area.zip, resp.status)
                    self.dump(f"stores_{pid}", resp.text[:100000], force=True)
                continue
            for r in parse_cvs_stores(data, area.name, area.radius):
                if allowed and r.store_id not in allowed:
                    continue
                prev = found.get(r.store_id)
                if prev is None or (r.distance or 999) < (prev.distance or 999):
                    found[r.store_id] = r
            self.pause(self.link_delay())
        return sorted(found.values(), key=lambda x: x.distance if x.distance is not None else 999)

    def check_ids(self, ids: list[str], in_store: bool) -> dict[str, StockResult]:
        out = super().check_ids(ids, in_store)
        if in_store and self.in_store_enabled():
            for ident, res in out.items():
                pid = cvs_product_id(ident)
                if pid:
                    res.stores = self.store_stock(pid, res.url)
        return out


SITE_CLASSES = (PokemonCenter, GameStop, Costco, SamsClub, BarnesAndNoble, BooksAMillion, Amazon, DicksSportingGoods,
                Safeway, Raleys, Walgreens, CVS)
