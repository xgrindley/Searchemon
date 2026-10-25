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


class GameStop(WebPage):
    name = "gamestop"
    display = "GameStop"
    domains = ("gamestop.com",)
    own_seller_names = ("gamestop",)


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


class CVS(WebPage):
    """CVS online listing. Accepts a full product URL or the numeric prodid."""
    name = "cvs"
    display = "CVS"
    domains = ("cvs.com",)

    def url_for(self, ident: str) -> str:
        if ident.startswith("http"):
            return ident
        return f"https://www.cvs.com/shop/-prodid-{ident.removeprefix('prodid-')}"


SITE_CLASSES = (PokemonCenter, GameStop, Costco, SamsClub, BarnesAndNoble, BooksAMillion, Amazon, DicksSportingGoods,
                Safeway, Raleys, Walgreens, CVS)
