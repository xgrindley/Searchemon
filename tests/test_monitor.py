"""Offline tests with canned retailer responses. Run: python -m unittest discover tests"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from restock.config import KeywordFilter, load_config  # noqa: E402
from restock.engine import Monitor  # noqa: E402
from restock.retailers import route_url  # noqa: E402
from restock.retailers.browser import FetchResult  # noqa: E402
from restock.retailers.pages import parse_product_page  # noqa: E402
from restock.util import clean_url, normalize_text, normalize_upc  # noqa: E402

CONFIG = """
discord:
  webhooks: {default: "https://discord.com/api/webhooks/1/abc"}
  mention_role_id: "42"
location: {zip: "90210", radius_miles: 25}
settings: {windows_toast: false, alert_on_startup: true}
discovery: {enabled: false, places: false}
retailers:
  bestbuy: {enabled: true, api_key: "k"}
  target: {enabled: true}
  walmart: {enabled: true}
  walgreens: {enabled: true}
  cvs: {enabled: false}
  web: {enabled: true}
keywords: {exclude: [sleeves]}
price_rules:
  - {match: "elite trainer box", max_price: 49.99}
  - {match: "tin", max_price: 26.99}
watchlist:
  - name: ETB
    upc: "820650123456"
    msrp: 49.99
    urls: ["https://www.walgreens.com/store/c/x/ID=prod1-product?utm_source=x"]
searches:
  - name: TCG
    query: pokemon trading card game
    retailers: [target]
"""


class FakeResp:
    def __init__(self, data=None, text="", status=200):
        self._data, self.text, self.status_code, self.headers = data, text, status, {}

    def json(self):
        if self._data is None:
            raise ValueError
        return self._data


def target_api(url, params=None, **kw):
    if "nearby_stores" in url:
        return {"data": {"nearby_stores": {"stores": [{"store_id": "1111", "location_name": "Near Target", "distance": 2.1}]}}}
    if "plp_search_v2" in url:
        kwd = params["keyword"]
        if kwd.isdigit():
            return {"data": {"search": {"products": [{"tcin": "90000001", "item": {"primary_barcode": "820650123456"}}]}}}
        return {"data": {"search": {"products": [
            {"tcin": "90000002", "item": {"product_description": {"title": "Pokémon Trading Card Game: Destined Rivals Elite Trainer Box"}},
             "price": {"current_retail": 49.99}},
            {"tcin": "90000003", "item": {"product_description": {"title": "Pokémon Trading Card Game Card Sleeves"}},
             "price": {"current_retail": 9.99}},
            {"tcin": "90000004", "item": {"product_description": {"title": "Pokemon Trading Card Game Elite Trainer Box Bundle"}},
             "price": {"current_retail": 149.99}},
        ]}}}
    tcin = params.get("tcin")
    if "pdp_client" in url:
        return {"data": {"product": {"item": {"product_description": {"title": f"Item {tcin} Elite Trainer Box"},
                                              "primary_barcode": "820650123456"},
                                     "price": {"current_retail": 49.99}}}}
    if "fulfillment_and_variation" in url:
        status = "IN_STOCK" if tcin == "90000002" else "OUT_OF_STOCK"
        return {"data": {"product": {"fulfillment": {"shipping_options": {"availability_status": status}}}}}
    if "fiats" in url:
        return {"data": {"fulfillment_fiats": {"locations": [
            {"location_id": "1111", "location_name": "Near Target", "distance": 2.1,
             "location_available_to_promise_quantity": 3.0},
            {"location_id": "2222", "location_name": "Far Target", "distance": 40.0,
             "location_available_to_promise_quantity": 0.0},
        ]}}}
    raise AssertionError(url)


def bestbuy_api(url, params=None, **kw):
    if "upc=" in url:
        return {"products": [{"sku": 6500001, "name": "ETB", "upc": "820650123456"}]}
    if "stores.json" in url:
        return {"stores": [{"storeID": "10", "name": "Best Buy Reno", "distance": 5.0},
                           {"storeID": "11", "name": "Best Buy Far", "distance": 90.0}]}
    return {"products": [{"sku": 6500001, "name": "Pokemon TCG Elite Trainer Box", "upc": "820650123456",
                          "salePrice": 49.99, "onlineAvailability": False, "inStoreAvailability": True,
                          "orderable": "SoldOut", "marketplace": False}]}


WALMART_HTML = '<html><script id="__NEXT_DATA__" type="application/json">' + json.dumps({
    "props": {"pageProps": {"initialData": {
        "data": {"product": {"name": "Pokemon ETB", "availabilityStatus": "IN_STOCK", "sellerName": "Big Reseller LLC",
                             "priceInfo": {"currentPrice": {"price": 89.0}}, "upc": "820650123456"}},
        "searchResult": {"itemStacks": [{"items": [{"usItemId": "555", "__typename": "Product"}]}]},
    }}}}) + "</script></html>"

WALGREENS_HTML = """<html><head><title>x</title>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product","name":"Pokemon TCG Booster Bundle",
"gtin12":"820650999999","offers":{"@type":"Offer","price":"26.99","availability":"https://schema.org/InStock"}}</script>
</head></html>"""


class UtilTests(unittest.TestCase):
    def test_clean_url(self):
        self.assertEqual(clean_url("https://a.com/p?utm_source=x&si=1&skuId=5&fbclid=z#frag"), "https://a.com/p?skuId=5")

    def test_normalize(self):
        self.assertEqual(normalize_text("Pokémon TCG: Scarlet & Violet"), "pokemon tcg scarlet and violet")
        self.assertEqual(normalize_upc("0-820650-12345-6"), normalize_upc("820650123456"))

    def test_keywords(self):
        kf = KeywordFilter.from_dict({"include_any": ["elite trainer box"], "exclude": ["sleeves", "lot"]})
        self.assertTrue(kf.matches("Pokémon Elite Trainer Box")[0])
        self.assertFalse(kf.matches("Pokemon Card Sleeves Elite Trainer Box")[0])
        self.assertTrue(kf.matches("Pokemon Slot Elite Trainer Box")[0])  # 'lot' is a whole-word exclude
        self.assertFalse(kf.matches("Lot of 3 Elite Trainer Box")[0])

    def test_routes(self):
        self.assertEqual(route_url("https://www.target.com/p/x/-/A-12345678"), ("target", "12345678"))
        self.assertEqual(route_url("https://www.bestbuy.com/site/x/6500001.p?skuId=6500001"), ("bestbuy", "6500001"))
        self.assertEqual(route_url("https://www.walmart.com/ip/Some-Name/555"), ("walmart", "555"))
        self.assertEqual(route_url("https://www.cvs.com/shop/x-prodid-1")[0], "cvs")
        self.assertEqual(route_url("https://www.pokemoncenter.com/product/1")[0], "pokemoncenter")
        self.assertEqual(route_url("https://www.amazon.com/Pokemon-ETB/dp/B0ABCDEFGH?ref=x"), ("amazon", "B0ABCDEFGH"))
        self.assertEqual(route_url("https://www.fredmeyer.com/p/pokemon-etb/0082065012345"), ("kroger", "0082065012345"))
        self.assertEqual(route_url("https://www.example-toys.com/p/1")[0], "web")

    def test_jsonld(self):
        info = parse_product_page(WALGREENS_HTML)
        self.assertEqual((info["status"], info["price"]), ("in", 26.99))
        info = parse_product_page("<html>Sold Out</html>", {"out_of_stock_text": ["sold out"]})
        self.assertEqual(info["status"], "out")


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.cfg_path = os.path.join(self.dir, "config.yaml")
        with open(self.cfg_path, "w") as fh:
            fh.write(CONFIG)
        self.posts = []

        def fake_post(url, json=None, timeout=None):
            self.posts.append(json)
            return FakeResp(status=204)

        self.patches = [
            mock.patch("restock.notify.requests.post", side_effect=fake_post),
            mock.patch("restock.retailers.target.Target.get_json", side_effect=target_api),
            mock.patch("restock.retailers.bestbuy.BestBuy.get_json", side_effect=bestbuy_api),
            mock.patch("restock.retailers.base.Retailer.pause"),
            mock.patch("restock.engine.Monitor.pause_between_checks"),
            mock.patch("restock.retailers.walmart.Walmart.fetch_html",
                       side_effect=lambda url: FetchResult(200, WALMART_HTML, url)),
            mock.patch("restock.retailers.pages.WebPage.fetch_html",
                       side_effect=lambda url: FetchResult(200, WALGREENS_HTML, url)),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        import logging
        for h in list(logging.getLogger("restock").handlers):
            h.close()
            logging.getLogger("restock").removeHandler(h)
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_price_rule_word_boundary(self):
        cfg = load_config(self.cfg_path)
        self.assertEqual(cfg.price_limit_for("Destined Rivals Booster"), None)  # 'tin' inside 'destined'
        self.assertEqual(cfg.price_limit_for("Pokemon Collector Tin"), 26.99)

    def test_full_cycle(self):
        mon = Monitor(self.cfg_path)
        results = {r.key: r for r in mon.run_once()}

        # Target watch via UPC: online OOS, in stock at the near store only.
        t = results["target:90000001"]
        self.assertFalse(t.online)
        self.assertEqual([s.store_id for s in t.stores], ["1111"])
        self.assertEqual(t.stores[0].qty, 3)

        # Target search: ETB at MSRP in stock online; sleeves filtered; $149 bundle filtered.
        self.assertTrue(results["target:90000002"].online)
        self.assertNotIn("target:90000003", results)
        self.assertNotIn("target:90000004", results)

        # Best Buy: online sold out, near store in stock, far store dropped by radius.
        b = results["bestbuy:6500001"]
        self.assertEqual([s.store_id for s in b.stores], ["10"])

        # Walmart: third-party seller at $89 is ignored.
        w = results["walmart:555"]
        self.assertTrue(w.note.startswith("ignored"))

        # Walgreens page via watch url, tracking params stripped.
        g = [r for k, r in results.items() if k.startswith("walgreens:")][0]
        self.assertTrue(g.online)
        self.assertNotIn("utm_", g.url)

        titles = [p["embeds"][0]["title"] for p in self.posts]
        self.assertEqual(len(self.posts), 4, titles)  # target watch, target search, bestbuy, walgreens
        first = self.posts[0]
        self.assertEqual(first["content"], "<@&42>")
        self.assertEqual(first["allowed_mentions"]["roles"], ["42"])
        for p in self.posts:
            self.assertTrue(all(v for v in p["embeds"][0].values()))

        # Second pass with nothing changed: no new alerts.
        mon.run_once()
        self.assertEqual(len(self.posts), 4)

        # Restart: alert_on_startup re-announces, but cooldown suppresses repeats.
        mon2 = Monitor(self.cfg_path)
        mon2.run_once()
        self.assertEqual(len(self.posts), 4)


if __name__ == "__main__":
    unittest.main()


class PanelTests(EngineTests):
    test_full_cycle = None
    test_price_rule_word_boundary = None
    def test_panel_api(self):
        import requests
        from restock.panel import PanelServer
        mon = Monitor(self.cfg_path)
        mon.run_once()
        panel = PanelServer(mon)
        panel.port = 8798
        self.assertTrue(panel.start())
        s = requests.Session()
        s.trust_env = False
        try:
            hdr = {"X-Token": panel.token}
            self.assertEqual(s.get(panel.url + "api/status").status_code, 401)
            self.assertEqual(s.get(panel.url, headers={"Host": "attacker.test"}).status_code, 403)
            page = s.get(panel.url).text
            self.assertIn(panel.token, page)
            st = s.get(panel.url + "api/status", headers=hdr).json()
            self.assertTrue(any(i["in_stock"] for i in st["items"]))
            cfg = s.get(panel.url + "api/config", headers=hdr).json()
            cfg["keywords"]["exclude"].append("binder")
            cfg["searches"][0]["max_price"] = 55
            self.assertTrue(s.post(panel.url + "api/config", json=cfg, headers=hdr).json()["ok"])
            saved = load_config(self.cfg_path)
            self.assertIn("binder", saved.keywords.exclude)
            self.assertEqual(saved.searches[0].max_price, 55)
            bad = dict(cfg, watchlist=[{"name": "x", "msrp": "not a number"}])
            self.assertEqual(s.post(panel.url + "api/config", json=bad, headers=hdr).status_code, 400)
            v = s.post(panel.url + "api/test-filter", json={"title": "Pokemon Elite Trainer Box", "price": 80}, headers=hdr).json()
            self.assertFalse(v["alert"])
            s.post(panel.url + "api/action", json={"action": "mute", "key": "target:90000001"}, headers=hdr)
            self.assertIn("target:90000001", load_config(self.cfg_path).settings["ignored_items"])
        finally:
            panel.stop()
            mon.stop()


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_patterns_and_schedule(self):
        import time as _t
        from restock.history import History, Schedule, in_window
        from restock.models import StockResult, StoreStock
        h = History(self.dir)
        store = StoreStock("1111", "Near Target", 2.1, 3, pickup=True)
        # Three Tuesday ~7 AM restocks at one store (local time), two items on one visit.
        base = _t.mktime((2026, 10, 6, 7, 10, 0, 0, 0, -1))  # a Tuesday
        for week in range(3):
            for i, title in enumerate(("ETB", "Booster Bundle")):
                res = StockResult("target", "Target", f"9{i}", title, "u")
                h.record(res, store, when=base + week * 7 * 86400 + i * 600)
        p = h.patterns("target")
        self.assertEqual(p["total"], 3)                       # 6 events, 3 visits
        self.assertEqual(p["grid"][1][7], 3)
        self.assertTrue(p["best"][0]["label"].startswith("Tue 7 AM"))
        self.assertEqual(History(self.dir).patterns()["total"], 3)   # survives a restart

        sched = Schedule({"schedule": {"slow_windows": [{"days": "all", "start": "23:00", "end": "05:00"}]}}, h)
        tue_7 = _t.mktime((2026, 10, 27, 7, 30, 0, 0, 0, -1))
        self.assertEqual(sched.factor("target", tue_7), (0.5, "usual restock time"))
        self.assertEqual(sched.factor("walmart", tue_7)[0], 1.0)
        wed_2am = _t.mktime((2026, 10, 28, 2, 0, 0, 0, 0, -1))
        self.assertEqual(sched.factor("walmart", wed_2am), (3.0, "quiet hours"))
        # Overnight window belongs to the day it started on.
        win = {"days": ["fri"], "start": "22:00", "end": "02:00"}
        self.assertTrue(in_window(win, _t.localtime(_t.mktime((2026, 10, 31, 1, 0, 0, 0, 0, -1)))))   # Sat 1 AM
        self.assertFalse(in_window(win, _t.localtime(_t.mktime((2026, 10, 30, 1, 0, 0, 0, 0, -1)))))  # Fri 1 AM

    def test_engine_records_real_restocks_only(self):
        from restock.history import History
        from restock.models import StockResult, StoreStock
        path = os.path.join(self.dir, "config.yaml")
        with open(path, "w") as fh:
            fh.write("settings: {windows_toast: false}\nretailers: {target: {enabled: false}, walmart: {enabled: false},"
                     " walgreens: {enabled: false}, cvs: {enabled: false}, web: {enabled: false}}\n")
        mon = Monitor(path)
        res = lambda stores: StockResult("target", "Target", "1", "ETB", "u", price=49.99, stores=stores)
        s1 = StoreStock("1", "A", 1.0, 2, pickup=True)
        mon.handle(res([s1]), None, None)          # first look at startup: not a restock we witnessed
        self.assertEqual(History(mon.cfg.data_dir).patterns()["total"], 0)
        mon.handle(res([]), None, None)            # sells out
        mon.handle(res([s1]), None, None)          # comes back: real restock
        self.assertEqual(History(mon.cfg.data_dir).patterns()["total"], 1)
