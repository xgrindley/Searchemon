"""Page stores (CVS, GameStop, Costco, Sam's, Walgreens, Barnes & Noble, Safeway) find Pokemon products on their
own and obey the Product types settings (alerts on/off and the MSRP cap), without any pasted links."""
import json
import os
import queue
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from restock.engine import Monitor  # noqa: E402
from restock.retailers.base import FetchResult  # noqa: E402

CONFIG = """
discord:
  webhooks: {default: "https://discord.com/api/webhooks/1/abc"}
location: {zip: "89434", radius_miles: 25}
settings: {windows_toast: false, alert_on_startup: true, confirm_restocks: false}
discovery: {enabled: true, places: false, retailers: [target], queries: [pokemon tcg]}
retailers:
  target: {enabled: false}
  bestbuy: {enabled: false}
  walmart: {enabled: false}
  kroger: {enabled: false}
  cvs: {enabled: true}
  gamestop: {enabled: true}
  costco: {enabled: true}
  samsclub: {enabled: true}
  walgreens: {enabled: true}
  barnesandnoble: {enabled: true}
  safeway: {enabled: true}
  web: {enabled: false}
{extra}
"""


def page(title, price, avail="InStock", seller=None, upc="820650000000"):
    offer = {"@type": "Offer", "availability": "https://schema.org/" + avail, "price": str(price)}
    if seller:
        offer["seller"] = {"@type": "Organization", "name": seller}
    data = {"@type": "Product", "name": title, "gtin12": upc, "offers": offer}
    return f'<html><script type="application/ld+json">{json.dumps(data)}</script><body>{title}</body></html>'


# store -> {path fragment: product page html}; search pages list the links.
STORES = {
    "cvs.com": {
        "/shop/pok-mon-tcg-mega-evolution-elite-trainer-box-prodid-1": page("Pokemon TCG Mega Evolution Elite Trainer Box", 49.99),
        "/shop/pok-mon-tcg-30th-anniversary-mini-tin-assorted-prodid-2": page("Pokemon TCG 30th Anniversary Mini Tin", 9.99, upc="820650000002"),
        "/shop/pok-mon-tcg-tin-prodid-3": page("Pokemon TCG Hidden Fates Tin", 27.99, upc="820650000003"),
        "/shop/head-shoulders-shampoo-prodid-9": page("Head & Shoulders Shampoo", 6.99),
    },
    "gamestop.com": {
        "/toys-games/trading-cards/products/pokemon-tcg-elite-trainer-box/449048.html": page("Pokemon TCG Elite Trainer Box", 79.99),
        "/toys-games/trading-cards/products/pokemon-tcg-booster-bundle/452105.html": page("Pokemon TCG Booster Bundle", 26.99, upc="820650000004"),
        "/toys-games/trading-cards/products/pokemon-card-sleeves/111111.html": page("Pokemon Card Sleeves 65 Count", 7.99),
    },
    "costco.com": {
        "/pokemon-tcg-booster-box.product.100111222.html": page("Pokemon TCG Booster Box 36 Packs", 149.99, upc="820650000005"),
        "/pokemon-tcg-ultra-premium-collection.product.100333444.html": page("Pokemon TCG Ultra Premium Collection", 179.99, "OutOfStock", upc="820650000006"),
    },
    "samsclub.com": {
        "/ip/pokemon-tcg-elite-trainer-box-bundle/12345678": page("Pokemon TCG Elite Trainer Box", 54.98, seller="Some Reseller", upc="820650000007"),
        "/ip/pokemon-tcg-premium-collection/87654321": page("Pokemon TCG Premium Collection", 39.98, seller="Sam's Club", upc="820650000008"),
    },
    "walgreens.com": {
        "/store/c/pokemon-tcg-mini-tin/ID=prod6000001-product": page("Pokemon TCG Mini Tin", 9.99, upc="820650000009"),
    },
    "barnesandnoble.com": {
        "/w/pokemon-tcg-booster-bundle/1145000001": page("Pokemon TCG Booster Bundle", 26.99, upc="820650000010"),
    },
    "safeway.com": {
        "/shop/product-details.960000001.html": page("Pokemon TCG Checklane Blister", 5.99, upc="820650000011"),
    },
}


def serve(url):
    host = url.split("/")[2].removeprefix("www.")
    path = url[url.index(host) + len(host):]
    site = STORES.get(host, {})
    if any(k in url for k in ("search", "CatalogSearch", "/s/")):          # a search page: links to every product
        links = "".join(f'<a href="{p}"><img></a>' for p in site)
        return FetchResult(200, f"<html><body>{links}</body></html>", url)
    for frag, html in site.items():
        if frag in url:
            return FetchResult(200, html, url)
    return FetchResult(404, "", url)


class PageStoreE2E(unittest.TestCase):
    def build(self, extra=""):
        self.dir = tempfile.mkdtemp()
        path = os.path.join(self.dir, "config.yaml")
        open(path, "w").write(CONFIG.replace("{extra}", extra))
        self.posts = []
        self.patches = [
            mock.patch("restock.notify.requests.post", side_effect=lambda u, json=None, timeout=None: (
                self.posts.append(json), mock.Mock(status_code=204, text=""))[1]),
            mock.patch("restock.retailers.base.Retailer.pause"),
            mock.patch("restock.retailers.pages.WebPage.fetch_html", side_effect=serve),
            mock.patch("restock.engine.Monitor.pause_between_checks"),
            mock.patch("restock.retailers.pages.CVS.store_stock", return_value=[]),
            mock.patch("restock.retailers.pages.GameStop.store_stock", return_value=[]),
        ]
        for p in self.patches:
            p.start()
        self.events = queue.Queue()
        self.mon = Monitor(path, self.events)
        return self.mon

    def tearDown(self):
        for p in getattr(self, "patches", []):
            p.stop()
        import logging
        for h in list(logging.getLogger("restock").handlers):
            h.close()
        shutil.rmtree(getattr(self, "dir", "."), ignore_errors=True)

    def cycle_all(self):
        for _ in range(2):               # discovery on the first pass, the products it found get checked
            for r in self.mon.retailers.values():
                self.mon.run_cycle(r)
        out = []
        while True:
            try:
                out.append(self.events.get_nowait())
            except queue.Empty:
                return out

    def alerts(self, events):
        return {(e[1].retailer, e[1].title) for e in events if e[0] == "alert"}

    def tracked(self, store):
        from restock.tcg import type_settings
        return {v["title"] for v in self.mon.catalog.tracked(store, type_settings(self.mon.cfg.raw))}

    def test_every_store_finds_its_own_products_with_no_links(self):
        self.build()
        events = self.cycle_all()
        self.assertTrue({"cvs", "gamestop", "costco", "samsclub", "walgreens", "barnesandnoble", "safeway"} <= set(self.mon.retailers))
        for store in ("cvs", "gamestop", "costco", "samsclub", "walgreens", "barnesandnoble", "safeway"):
            self.assertTrue(self.tracked(store), f"{store} found no products")
        self.assertFalse(any("Shampoo" in t or "Sleeves" in t for s in ("cvs", "gamestop") for t in self.tracked(s)))
        got = self.alerts(events)
        self.assertIn(("cvs", "Pokemon TCG Mega Evolution Elite Trainer Box"), got)
        self.assertIn(("barnesandnoble", "Pokemon TCG Booster Bundle"), got)
        self.assertIn(("safeway", "Pokemon TCG Checklane Blister"), got)

    def test_msrp_cap_third_party_and_sold_out_are_respected(self):
        self.build()
        got = self.alerts(self.cycle_all())
        self.assertNotIn(("gamestop", "Pokemon TCG Elite Trainer Box"), got)            # $79.99 is over the ETB cap
        self.assertIn(("gamestop", "Pokemon TCG Booster Bundle"), got)
        self.assertNotIn(("samsclub", "Pokemon TCG Elite Trainer Box"), got)            # third-party seller
        self.assertIn(("samsclub", "Pokemon TCG Premium Collection"), got)
        self.assertNotIn(("costco", "Pokemon TCG Ultra Premium Collection"), got)       # out of stock
        self.assertIn(("costco", "Pokemon TCG Booster Box 36 Packs"), got)

    def test_turning_a_product_type_off_stops_tracking_and_alerts_for_it(self):
        self.build("product_types:\n  tin: {alert: false}\n  mini_tin: {alert: false}\n")
        got = self.alerts(self.cycle_all())
        self.assertNotIn(("cvs", "Pokemon TCG Hidden Fates Tin"), got)
        self.assertNotIn(("cvs", "Pokemon TCG 30th Anniversary Mini Tin"), got)
        self.assertNotIn(("walgreens", "Pokemon TCG Mini Tin"), got)
        self.assertTrue(any("Elite Trainer" in t for t in self.tracked("cvs")))
        self.assertFalse(any("Tin" in t for t in self.tracked("cvs")))

    def test_msrp_changed_in_product_types_is_used(self):
        self.build("product_types:\n  etb: {msrp: 99.99}\n")
        got = self.alerts(self.cycle_all())
        self.assertIn(("gamestop", "Pokemon TCG Elite Trainer Box"), got)               # $79.99 now under the cap

    def test_products_found_at_other_stores_are_looked_up_by_upc(self):
        mon = self.build()
        from restock.models import StockResult
        seen = []
        orig = serve
        def spy(url):
            seen.append(url)
            return orig(url)
        mon.catalog.merge("target", [StockResult("target", "Target", "t1", "Pokemon TCG Mega Evolution Elite Trainer Box", "u",
                                                 upc="820650123456", online_status="In stock")], mon.cfg.raw, True)
        with mock.patch("restock.retailers.pages.WebPage.fetch_html", side_effect=spy):
            self.cycle_all()
        self.assertTrue(any("820650123456" in u for u in seen), "no store was searched for the Target product's UPC")


if __name__ == "__main__":
    unittest.main()
