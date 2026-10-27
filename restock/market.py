"""Fair market value and eBay deals.

Fair market value for a product comes from two places:
- TCGplayer's market price, read once a day from tcgcsv.com (sealed products of the newest sets only, about two dozen
  small requests a day, within its rules).
- What eBay sellers ask right now: each listing's price plus shipping, for new, sealed, Buy It Now listings in the US.
  Outliers are left out before taking the middle: prices far above or below the rest (outside 1.5 times the spread of
  the middle half), and listings whose shipping is egregious (more than the larger of $15 and half the price), since a
  low price with a huge shipping charge is not really low.

eBay deals: the same listings are scored for risk, so a cheap listing from a risky seller is not mistaken for a deal.
Red flags (each adds to the risk score, shown with the listing):
- few feedback ratings (under 10, 50, 200) and a low positive share (under 95%, 98%, 99.5%)
- a price far under fair value (a classic scam sign when the seller is also new)
- listed in the last 3 days by a seller with little feedback
- shipped from outside the US, no returns, a large quantity of a hot product from a small seller
- words that mean it is not the sealed product: "box only", "empty", "no cards", "read description", "photo of", "proxy",
  "repack", "resealed", "custom", "opened" and the like (those are dropped outright)
Feedback that looks fake cannot be read from eBay's public data directly (eBay does not share who left it or for what).
What can be seen is used instead: a positive share under 98% on a small count is a real warning, a large count
earned by a brand-new listing account is not taken at face value (new listing plus low price plus small seller), and
the listing's own red flags count whatever the feedback says.

eBay access: with an eBay developer key (free, developer.ebay.com, "Production" keyset: App ID and Cert ID) the official
Browse API is used. Without one, eBay's public search page is read instead, which works but is less exact.
"""
from __future__ import annotations

import base64
import os
import re
import statistics
import threading
import time
from urllib.parse import quote_plus

import requests

from .tcg import classify
from .util import atomic_write_json, clean_url, normalize_text, read_json

TCG_GROUPS = "https://tcgcsv.com/tcgplayer/3/groups"
TCG_PRODUCTS = "https://tcgcsv.com/tcgplayer/3/{gid}/products"
TCG_PRICES = "https://tcgcsv.com/tcgplayer/3/{gid}/prices"
TCG_EVERY_S = 24 * 3600
TCG_MAX_GROUPS = 12
TCG_RECENT_DAYS = 400
EBAY_TOKEN = "https://api.ebay.com/identity/v1/oauth2/token"
EBAY_SEARCH = "https://api.ebay.com/buy/browse/v1/item_summary/search"
EBAY_HTML = "https://www.ebay.com/sch/i.html?_nkw={q}&LH_BIN=1&LH_ItemCondition=1000&LH_PrefLoc=1&_ipg=60&_sop=15"
NOT_SEALED = re.compile(r"(?i)\b(box only|empty|no cards|no packs|read desc|read the desc|see desc|photo of|picture of|"
                        r"pic of|image of|proxy|repack|re-?sealed|custom|opened|open box|damaged|dented|crushed|"
                        r"code cards?|digital|online code|wrapper|art card|display only|mystery|lot of|bundle of|"
                        r"\d+ ?x |case of|japanese|korean|chinese)\b")
SHIP_CAP = 15.0                 # shipping over max(this, half the price) is egregious
DEFAULTS = {"enabled": False, "app_id": "", "cert_id": "", "interval_minutes": 30, "products_per_check": 4,
            "queries": [], "deal_pct": 90, "alert_max_risk": "low", "us_only": True}


def ebay_cfg(raw: dict) -> dict:
    c = dict(DEFAULTS)
    own = raw.get("ebay") if isinstance(raw, dict) else None
    if isinstance(own, dict):
        c.update({k: v for k, v in own.items() if v is not None})
    return c


# ---- matching names --------------------------------------------------------------------------------
TYPE_WORDS = {"elite", "trainer", "booster", "bundle", "box", "display", "collection", "premium", "ultra", "super",
              "tin", "mini", "blister", "pack", "packs", "build", "battle", "binder", "poster", "illustration", "case",
              "sleeved", "checklane", "deck", "figure", "surprise", "etb", "upc", "spc"}
FILLER = {"pokemon", "tcg", "trading", "card", "game", "the", "and", "of", "new", "sealed", "factory", "english",
          "with", "for", "in", "a", "an", "brand", "authentic", "official", "free", "shipping", "fast"}
ABBR = {"etb": "elite trainer box", "bb": "booster bundle", "upc": "ultra premium collection",
        "spc": "super premium collection"}


def words(title: str) -> set[str]:
    t = re.sub(r"\$?\d+(\.\d+)?", lambda m: m.group(0) if re.fullmatch(r"\d{2,3}(st|th)?", m.group(0)) else " ",
               normalize_text(title))
    out = " ".join(ABBR.get(w, w) for w in t.split()).split()
    return {w for w in out if len(w) > 1 and w not in FILLER}


def match_score(a: str, b: str) -> float:
    """How alike two product names are: 0 to 1. Names of the set and the product type both have to agree."""
    wa, wb = words(a), words(b)
    if not wa or not wb:
        return 0.0
    na, nb = wa - TYPE_WORDS, wb - TYPE_WORDS
    ta, tb = classify("Pokemon TCG " + a).type_key, classify("Pokemon TCG " + b).type_key
    if ta and tb and ta != tb and "other" not in (ta, tb):
        return 0.0                                         # an ETB is not a booster bundle
    if na and nb and not (na & nb):
        return 0.0
    return len(wa & wb) / len(wa | wb)


# ---- robust middle -------------------------------------------------------------------------------
def fair_middle(totals: list[float]) -> tuple[float | None, list[float]]:
    """(median of the totals after dropping outliers, the totals kept). Tukey's fences: outside 1.5 x IQR."""
    xs = sorted(x for x in totals if x and x > 0)
    if len(xs) < 3:
        return (statistics.median(xs) if xs else None), xs
    q1, q3 = _quantile(xs, 0.25), _quantile(xs, 0.75)
    spread = q3 - q1
    lo, hi = q1 - 1.5 * spread, q3 + 1.5 * spread
    kept = [x for x in xs if lo <= x <= hi] or xs
    return round(statistics.median(kept), 2), kept


def _quantile(xs: list[float], q: float) -> float:
    pos = (len(xs) - 1) * q
    i = int(pos)
    return xs[i] + (xs[min(i + 1, len(xs) - 1)] - xs[i]) * (pos - i)


def egregious_shipping(price: float, shipping: float | None) -> bool:
    return shipping is not None and shipping > max(SHIP_CAP, 0.5 * price)


# ---- risk ----------------------------------------------------------------------------------------
def risk(listing: dict, fair: float | None, now: float | None = None) -> tuple[int, str, list[str]]:
    """(score 0-100, "low" / "medium" / "high", reasons) for one eBay listing."""
    now = now or time.time()
    score, why = 0, []
    fb = listing.get("feedback")
    pct = listing.get("positive")
    if fb is None:
        score += 15
        why.append("seller feedback not shown")
    elif fb < 10:
        score += 40
        why.append(f"only {fb} feedback ratings")
    elif fb < 50:
        score += 25
        why.append(f"only {fb} feedback ratings")
    elif fb < 200:
        score += 10
        why.append(f"{fb} feedback ratings")
    if pct is not None:
        if pct < 95:
            score += 35
            why.append(f"{pct:g}% positive")
        elif pct < 98:
            score += 20
            why.append(f"{pct:g}% positive")
        elif pct < 99.5 and (fb or 0) < 1000:
            score += 8
            why.append(f"{pct:g}% positive")
    total = listing.get("total")
    if fair and total:
        if total < 0.6 * fair:
            score += 30
            why.append(f"{round(100 * (1 - total / fair))}% under fair value (too good to be true)")
        elif total < 0.8 * fair:
            score += 10
            why.append(f"{round(100 * (1 - total / fair))}% under fair value")
    created = listing.get("created")
    if created and now - created < 3 * 86400 and (fb or 0) < 100:
        score += 15
        why.append("listed in the last 3 days by a small seller")
    if listing.get("country") and listing["country"] != "US":
        score += 20
        why.append(f"ships from {listing['country']}")
    if listing.get("returns") is False:
        score += 10
        why.append("no returns")
    if (listing.get("quantity") or 0) >= 3 and (fb or 0) < 100 and fair and total and total < 0.85 * fair:
        score += 10
        why.append(f"{listing['quantity']} available cheap from a small seller")
    if egregious_shipping(listing.get("price") or 0, listing.get("shipping")):
        score += 10
        why.append(f"${listing['shipping']:.2f} shipping")
    score = min(100, score)
    level = "low" if score < 20 else "medium" if score < 45 else "high"
    return score, level, why


# ---- reading eBay ----------------------------------------------------------------------------------
def _money(text) -> float | None:
    m = re.search(r"(\d[\d,]*\.?\d*)", str(text or ""))
    try:
        return float(m.group(1).replace(",", "")) if m else None
    except ValueError:
        return None


def _count(text: str) -> int | None:
    m = re.search(r"([\d.,]+)\s*([kKmM]?)", text or "")
    if not m:
        return None
    n = float(m.group(1).replace(",", ""))
    return int(n * {"k": 1000, "m": 1_000_000}.get(m.group(2).lower(), 1))


def from_api(item: dict) -> dict:
    price = _money((item.get("price") or {}).get("value"))
    ship = None
    for opt in item.get("shippingOptions") or []:
        cost = (opt.get("shippingCost") or {}).get("value")
        if cost is not None:
            ship = _money(cost) or 0.0
            break
        if opt.get("shippingCostType") == "FIXED" and cost is None:
            ship = 0.0
    seller = item.get("seller") or {}
    created = item.get("itemCreationDate") or item.get("itemOriginDate")
    return {
        "id": str(item.get("itemId") or ""), "title": str(item.get("title") or ""), "url": clean_url(item.get("itemWebUrl")),
        "price": price, "shipping": ship, "total": round(price + (ship or 0), 2) if price else None,
        "seller": seller.get("username", ""), "feedback": seller.get("feedbackScore"),
        "positive": _money(seller.get("feedbackPercentage")), "country": (item.get("itemLocation") or {}).get("country", ""),
        "created": _iso(created), "best_offer": "BEST_OFFER" in (item.get("buyingOptions") or []),
        "image": (item.get("image") or {}).get("imageUrl", ""), "condition": item.get("condition", ""),
    }


def _iso(value) -> float | None:
    if not value:
        return None
    try:
        import datetime as dt
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


ITEM_SPLIT = re.compile(r'(?=<li[^>]+(?:data-listingid|class="s-(?:item|card)\b))', re.I)
TAGS = re.compile(r"<[^>]+>")


def from_html(page: str) -> list[dict]:
    """eBay's public search page (no key): each result card's title, price, delivery and seller line."""
    import html as htmllib
    out = []
    for block in ITEM_SPLIT.split(page or "")[1:]:
        m = re.search(r'href="(https://www\.ebay\.com/itm/(\d+)[^"]*)"', block)
        if not m:
            continue
        text = re.sub(r"\s+", " ", htmllib.unescape(TAGS.sub(" | ", block)))
        bits = [b.strip() for b in text.split("|") if b.strip()]
        title = next((b for b in bits if len(b) > 15 and not b.startswith(("$", "New Listing", "Opens in"))
                      and "Shop on eBay" not in b), "")
        title = re.sub(r"^New Listing\s*", "", title)
        price = next((_money(b) for b in bits if re.match(r"^\$\d", b)), None)
        ship_text = next((b for b in bits if re.search(r"(?i)deliver|shipping", b)), "")
        ship = 0.0 if re.search(r"(?i)free (delivery|shipping)", ship_text) else _money(ship_text) if ship_text else None
        seller = re.search(r"(?i)([a-z0-9._-]{3,64})\s+(\d{1,3}(?:\.\d)?)%\s+positive\s*\(([\d.,]+[kKmM]?)\)", text)
        country = re.search(r"(?i)located in ([A-Za-z ]+?)(?: \||$)", text)
        out.append({
            "id": m.group(2), "title": title, "url": clean_url(m.group(1)), "price": price, "shipping": ship,
            "total": round(price + (ship or 0), 2) if price else None,
            "seller": seller.group(1) if seller else "", "positive": float(seller.group(2)) if seller else None,
            "feedback": _count(seller.group(3)) if seller else None,
            "country": ("US" if country and "united states" in country.group(1).lower() else
                        (country.group(1).strip()[:30] if country else "")),
            "created": time.time() if "New Listing" in text else None, "best_offer": "best offer" in text.lower(),
            "image": "", "condition": "",
        })
    return [x for x in out if x["title"] and x["price"]]


class Market:
    def __init__(self, raw: dict, data_dir: str, log, version: str = "5"):
        self.raw = raw
        self.dir = data_dir
        self.log = log
        self.lock = threading.Lock()
        self.path = os.path.join(data_dir, "market.json")
        d = read_json(self.path, {}) or {}
        self.tcg: list[dict] = d.get("tcg") or []
        self.tcg_at: float = float(d.get("tcg_at") or 0)
        self.products: dict[str, dict] = d.get("products") or {}     # product name -> fair value, deals
        self.alerted: list[str] = d.get("alerted") or []
        self.turn = int(d.get("turn") or 0)
        self.http = requests.Session()
        self.http.headers.update({"User-Agent": f"Searchemon/{version}", "Accept-Language": "en-US,en;q=0.9"})
        self._token: tuple[str, float] = ("", 0.0)
        self.problem = ""

    def attach(self, raw: dict) -> None:
        self.raw = raw

    # ---- TCGplayer market prices (tcgcsv.com) --------------------------------------------------------
    def refresh_tcg(self, now: float | None = None) -> bool:
        now = now or time.time()
        if now - self.tcg_at < TCG_EVERY_S:
            return False
        try:
            groups = self.http.get(TCG_GROUPS, timeout=30).json()
            rows = groups.get("results") if isinstance(groups, dict) else groups
            recent = []
            for g in rows or []:
                t = _iso(str(g.get("publishedOn") or "")[:19])
                if t and now - t < TCG_RECENT_DAYS * 86400 and not re.search(r"(?i)promo|prize pack|jumbo|championship", str(g.get("name"))):
                    recent.append((t, g))
            recent.sort(key=lambda x: -x[0])
            out = []
            for _, g in recent[:TCG_MAX_GROUPS]:
                gid = g.get("groupId")
                prods = self.http.get(TCG_PRODUCTS.format(gid=gid), timeout=30).json()
                time.sleep(0.2)
                prices = self.http.get(TCG_PRICES.format(gid=gid), timeout=30).json()
                time.sleep(0.2)
                by_id = {}
                for p in (prices.get("results") if isinstance(prices, dict) else prices) or []:
                    if p.get("marketPrice") or p.get("midPrice"):
                        by_id.setdefault(p.get("productId"), p)
                for p in (prods.get("results") if isinstance(prods, dict) else prods) or []:
                    ext = {str(e.get("name")) for e in p.get("extendedData") or []}
                    if ext & {"Number", "Rarity"}:
                        continue                          # a single card, not sealed product
                    pr = by_id.get(p.get("productId"))
                    if not pr:
                        continue
                    out.append({"name": str(p.get("name") or ""), "set": str(g.get("name") or ""),
                                "market": pr.get("marketPrice") or pr.get("midPrice"), "low": pr.get("lowPrice"),
                                "url": clean_url(p.get("url"))})
        except Exception as exc:
            self.tcg_at = now - TCG_EVERY_S + 3 * 3600         # try again in 3 hours
            self.log.info("Market value: TCGplayer prices could not be read (%s)", str(exc)[:80])
            return False
        with self.lock:
            self.tcg, self.tcg_at = out, now
        self.save()
        self.log.info("Market value: read TCGplayer market prices for %d sealed products", len(out))
        return True

    def tcg_value(self, title: str) -> dict | None:
        best, score = None, 0.0
        with self.lock:
            for row in self.tcg:
                s = match_score(title, row["name"])
                if s > score:
                    best, score = row, s
        return dict(best, match=round(score, 2)) if best and score >= 0.45 else None

    # ---- eBay ---------------------------------------------------------------------------------------
    def _bearer(self) -> str:
        c = ebay_cfg(self.raw)
        if not (c.get("app_id") and c.get("cert_id")):
            return ""
        tok, until = self._token
        if tok and time.time() < until:
            return tok
        auth = base64.b64encode(f"{c['app_id']}:{c['cert_id']}".encode()).decode()
        r = self.http.post(EBAY_TOKEN, headers={"Authorization": f"Basic {auth}",
                                                "Content-Type": "application/x-www-form-urlencoded"},
                           data={"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"}, timeout=30)
        d = r.json()
        if not d.get("access_token"):
            raise RuntimeError(d.get("error_description") or "eBay refused the key")
        self._token = (d["access_token"], time.time() + int(d.get("expires_in") or 7200) - 120)
        return self._token[0]

    def search_ebay(self, query: str) -> list[dict]:
        c = ebay_cfg(self.raw)
        tok = self._bearer()
        if tok:
            filt = "buyingOptions:{FIXED_PRICE|BEST_OFFER},conditions:{NEW},priceCurrency:USD"
            if c.get("us_only", True):
                filt += ",itemLocationCountry:US"
            r = self.http.get(EBAY_SEARCH, params={"q": query, "filter": filt, "limit": 50},
                              headers={"Authorization": f"Bearer {tok}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"}, timeout=30)
            if r.status_code != 200:
                raise RuntimeError(f"eBay answered {r.status_code}")
            return [from_api(i) for i in r.json().get("itemSummaries") or []]
        r = self.http.get(EBAY_HTML.format(q=quote_plus(query)), timeout=30,
                          headers={"Accept": "text/html,application/xhtml+xml"})
        if r.status_code != 200:
            raise RuntimeError(f"eBay answered {r.status_code}")
        return from_html(r.text)

    def value(self, product: str, msrp: float | None, listings: list[dict]) -> dict:
        """Fair value for one product from matching eBay listings and TCGplayer."""
        relevant = []
        for x in listings:
            if NOT_SEALED.search(x["title"]) or not classify(x["title"], allow_non_english=False).is_tcg:
                continue
            if match_score(product, x["title"]) < 0.3:
                continue
            relevant.append(x)
        usable = [x["total"] for x in relevant if x.get("total") and x.get("shipping") is not None
                  and not egregious_shipping(x["price"], x["shipping"])]
        ebay_mid, kept = fair_middle(usable)
        tcg = self.tcg_value(product)
        parts = [v for v in (ebay_mid, (tcg or {}).get("market")) if v]
        fair = round(statistics.mean(parts), 2) if parts else None
        return {"product": product, "msrp": msrp, "ebay": ebay_mid, "ebay_n": len(kept), "ebay_seen": len(relevant),
                "tcg": (tcg or {}).get("market"), "tcg_name": (tcg or {}).get("name", ""), "tcg_url": (tcg or {}).get("url", ""),
                "fair": fair, "relevant": relevant}

    def check(self, products: list[dict]) -> list[dict]:
        """Look up a few wanted products on eBay (rotating). products: [{"title", "msrp"}]. Returns new deals."""
        c = ebay_cfg(self.raw)
        queries = [{"title": q, "msrp": None} for q in c.get("queries") or [] if str(q).strip()] + list(products)
        if not queries:
            return []
        n = max(1, int(c.get("products_per_check") or 4))
        start = self.turn % len(queries)
        self.turn += n
        picked = (queries[start:] + queries[:start])[:n]
        deals = []
        for p in picked:
            title = p["title"]
            q = " ".join(t for t in re.sub(r"[^\w\s&'-]", " ", title).split() if t.lower() not in ("tcg:", "-"))[:80] + " sealed"
            try:
                listings = self.search_ebay(q)
                self.problem = ""
            except Exception as exc:
                self.problem = str(exc)[:120]
                self.log.info("eBay: search for '%s' failed (%s)", title[:40], self.problem)
                continue
            v = self.value(title, p.get("msrp"), listings)
            fair = v["fair"] or p.get("msrp")
            rows = []
            for x in v.pop("relevant"):
                score, level, why = risk(x, fair)
                x.update({"risk": score, "level": level, "why": why,
                          "pct_fair": round(100 * x["total"] / fair) if fair and x.get("total") else None})
                rows.append(x)
            rows.sort(key=lambda x: (x["total"] or 9e9))
            v.update({"at": time.time(), "listings": rows[:25]})
            with self.lock:
                self.products[title] = v
            limit = float(c.get("deal_pct") or 90)
            allowed = {"low": ("low",), "medium": ("low", "medium"), "high": ("low", "medium", "high")}.get(
                str(c.get("alert_max_risk") or "low"), ("low",))
            for x in rows:
                if x["pct_fair"] is not None and x["pct_fair"] <= limit and x["level"] in allowed and x["id"] not in self.alerted:
                    deals.append({**x, "product": title, "fair": fair})
                    self.alerted = (self.alerted + [x["id"]])[-2000:]
            time.sleep(2.0)
        self.save()
        return deals

    def view(self) -> dict:
        with self.lock:
            return {"products": sorted(self.products.values(), key=lambda v: -v.get("at", 0)),
                    "tcg_count": len(self.tcg), "tcg_at": self.tcg_at, "problem": self.problem,
                    "api": bool(ebay_cfg(self.raw).get("app_id") and ebay_cfg(self.raw).get("cert_id"))}

    def save(self) -> None:
        with self.lock:
            data = {"tcg": self.tcg, "tcg_at": self.tcg_at, "products": self.products, "alerted": self.alerted,
                    "turn": self.turn}
        try:
            atomic_write_json(self.path, data)
        except OSError:
            pass
