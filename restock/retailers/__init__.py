"""Retailer registry and URL routing."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from .bestbuy import BestBuy
from .kroger import Kroger
from .pages import SITE_CLASSES, WebPage
from .target import Target
from .walmart import Walmart

REGISTRY = {
    "bestbuy": BestBuy,
    "target": Target,
    "kroger": Kroger,
    "walmart": Walmart,
    **{cls.name: cls for cls in SITE_CLASSES},
    "web": WebPage,
}

_KROGER_HOSTS = ("kroger.com", "fredmeyer.com", "ralphs.com", "smithsfoodanddrug.com", "kingsoopers.com",
                 "frysfood.com", "qfc.com", "dillons.com", "harristeeter.com", "food4less.com", "foodsco.net",
                 "picknsave.com", "marianos.com", "metromarket.net", "bakersplus.com", "citymarket.com",
                 "gerbes.com", "jaycfoods.com", "pay-less.com")


def _host_is(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def route_url(url: str) -> tuple[str, str]:
    """Turn a pasted product link into (retailer, id) so links 'just work'."""
    host = urlsplit(url).netloc.lower()
    if _host_is(host, "target.com"):
        m = re.search(r"A-(\d+)", url)
        if m:
            return "target", m.group(1)
    if _host_is(host, "bestbuy.com"):
        m = re.search(r"skuId=(\d+)", url) or re.search(r"/(\d{6,8})\.p", url)
        if m:
            return "bestbuy", m.group(1)
    if _host_is(host, "walmart.com"):
        m = re.search(r"/ip/(?:[^/]+/)?(\d+)", url)
        if m:
            return "walmart", m.group(1)
    if any(_host_is(host, h) for h in _KROGER_HOSTS):
        m = re.search(r"/p/[^/]*/(\d{13})", url) or re.search(r"\b(\d{13})\b", url)
        if m:
            return "kroger", m.group(1)
    if _host_is(host, "amazon.com"):
        m = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", url)
        if m:
            return "amazon", m.group(1)
    for cls in SITE_CLASSES:
        if any(_host_is(host, d) for d in cls.domains):
            return cls.name, url
    return "web", url
