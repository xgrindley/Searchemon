"""Tests for the Cloudflare false positive and GameStop store stock by area ZIP."""
import json
import logging
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from restock.config import Config, KeywordFilter  # noqa: E402
from restock.geo import Area  # noqa: E402
from restock.retailers.blocks import classify  # noqa: E402
from restock.retailers.browser import FetchResult  # noqa: E402
from restock.retailers.pages import (CVS, GameStop, cvs_product_id, cvs_stock_request, gamestop_product_id,  # noqa: E402
                                     json_from_page, parse_cvs_stores, parse_gamestop_stores)

LOG = logging.getLogger("t5")

NORMAL_PAGE = ('<html><head><script type="application/ld+json">{"@type":"Product","name":"Pokemon ETB"}</script>'
               '</head><body>Add to cart<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>'
               '</body></html>')
CHALLENGE = ('<html><head><title>Just a moment...</title></head><body>'
             '<script>window._cf_chl_opt={cvId:"3"};</script></body></html>')


class CloudflareTests(unittest.TestCase):
    def test_normal_page_with_cloudflare_script_is_not_a_challenge(self):
        self.assertIsNone(classify(200, NORMAL_PAGE))
        self.assertIsNone(classify(200, NORMAL_PAGE, {"Server": "cloudflare"}))

    def test_server_header_alone_is_not_a_block_on_200(self):
        self.assertIsNone(classify(200, "<html>ok</html>", {"Server": "AkamaiGHost"}))

    def test_real_challenge_still_detected(self):
        info = classify(403, CHALLENGE, {"Server": "cloudflare"})
        self.assertIsNotNone(info)
        self.assertEqual(info.kind, "challenge")
        self.assertIsNotNone(classify(200, CHALLENGE))

    def test_bare_403_from_cloudflare_is_denied(self):
        info = classify(403, "nope", {"Server": "cloudflare"})
        self.assertEqual(info.kind, "denied")


ROWS = {"stores": [
    {"storeId": "4021", "storeName": "GameStop Main St", "storeAddress": "100 Main St", "storeZip": "90210",
     "storeDistanceMiles": 3.2, "inStockAtStore": True, "storeQuantity": 4, "latitude": 34.1, "longitude": -118.4},
    {"storeId": "4022", "storeName": "GameStop Oak", "storeZip": "90211", "storeDistanceMiles": 5,
     "inStockAtStore": False, "storeQuantity": 0, "stockLevel": "out_of_stock"},
    {"ID": "4023", "name": "GameStop Elm", "postalCode": "90212", "distance": 8.5, "stockLevel": "low_stock"},
]}


class GameStopParseTests(unittest.TestCase):
    def test_product_id(self):
        self.assertEqual(gamestop_product_id("https://www.gamestop.com/toys/products/pokemon-etb/11234567.html?x=1"), "11234567")
        self.assertEqual(gamestop_product_id("445744"), "445744")
        self.assertEqual(gamestop_product_id("https://www.gamestop.com/"), "")

    def test_only_in_stock_stores(self):
        rows = parse_gamestop_stores(ROWS, "Home")
        self.assertEqual({r.store_id for r in rows}, {"4021", "4023"})
        a = next(r for r in rows if r.store_id == "4021")
        self.assertEqual((a.qty, a.zip, a.via_area, a.chain), (4, "90210", "Home", "gamestop"))
        self.assertTrue(next(r for r in rows if r.store_id == "4023").low)

    def test_json_inside_browser_page(self):
        page = "<html><body><pre>" + json.dumps(ROWS).replace('"', "&quot;") + "</pre></body></html>"
        self.assertEqual(len(parse_gamestop_stores(json_from_page(page))), 2)
        self.assertIsNone(json_from_page("<html>no json</html>"))


class FakeGS(GameStop):
    def __init__(self, cfg, areas_payload):
        super().__init__(cfg, LOG, None)
        self.payload = areas_payload
        self.urls = []

    def fetch_html(self, url):
        self.urls.append(url)
        if "Stores-FindStores" in url:
            return FetchResult(200, "<pre>" + json.dumps(self.payload) + "</pre>", url)
        return FetchResult(200, NORMAL_PAGE, url)

    @staticmethod
    def pause(seconds):
        pass


class GameStopAreaTests(unittest.TestCase):
    def make(self, payload):
        raw = {"settings": {"in_store": True, "link_delay_seconds": 0}, "retailers": {"gamestop": {"enabled": True}},
               "location": {"zip": "90210", "radius_miles": 25}}
        areas = [Area("Home", "90210", 25), Area("Work", "10001", 10)]
        cfg = Config(path="x", raw=raw, watchlist=[], searches=[], keywords=KeywordFilter(), price_rules=[], areas=areas)
        return FakeGS(cfg, payload)

    def test_checks_every_area_zip(self):
        gs = self.make(ROWS)
        out = gs.check_ids(["https://www.gamestop.com/toys/products/pokemon-etb/11234567.html"], True)
        res = next(iter(out.values()))
        zips = [u.split("postalCode=")[1].split("&")[0] for u in gs.urls if "FindStores" in u]
        self.assertEqual(zips, ["90210", "10001"])
        self.assertTrue(res.stores)

    def test_unreadable_answer_is_logged_once(self):
        gs = self.make({"unexpected": True})
        with self.assertLogs("t5", level="WARNING") as cm:
            gs.check_ids(["https://www.gamestop.com/toys/products/x/11234567.html"], True)
            gs.check_ids(["https://www.gamestop.com/toys/products/x/11234567.html"], True)
        self.assertEqual(len([m for m in cm.output if "no readable answer" in m]), 1)


CVS_ANSWER = {"response": {"header": {"statusCode": "0000"}}, "atgResponse": [
    {"City": "SPARKS", "State": "NV", "Zipcode": "89431", "storeAddress": "680 N. MCCARRAN BLVD.", "storeId": "8792",
     "dt": "1.22", "Qty": 0, "bohStatus": "Out of Stock", "bopus": {"Qty": 0}},
    {"City": "SPARKS", "State": "NV", "Zipcode": "89434", "storeAddress": "2878 VISTA BLVD", "storeId": "3948",
     "dt": "2.93", "Qty": 5, "bohStatus": "In Stock", "bopus": {"Qty": 0}},
    {"City": "TRUCKEE", "State": "CA", "Zipcode": "96161", "storeAddress": "11411 DEERFIELD DR", "storeId": "9174",
     "dt": "28.67", "Qty": 1, "bohStatus": "In Stock", "bopus": {"Qty": 1}},
    {"City": "SOUTH LAKE TAHOE", "State": "CA", "Zipcode": "96150", "storeAddress": "1043 EMERALD BAY RD",
     "storeId": "9713", "dt": "45.43", "Qty": 9, "bohStatus": "In Stock", "bopus": {"Qty": 0}}]}


class CVSTests(unittest.TestCase):
    def test_product_id(self):
        self.assertEqual(cvs_product_id("https://www.cvs.com/shop/pok-mon-tcg-knockout-prodid-619797"), "619797")
        self.assertEqual(cvs_product_id("619797"), "619797")

    def test_request_shape(self):
        body = cvs_stock_request("619797", "89501")["getStoreDetailsAndInventoryRequest"]
        self.assertEqual((body["productId"], body["addressLine"]), ("619797", "89501"))
        self.assertEqual(body["header"]["channelName"], "WEB")

    def test_counts_pickup_and_radius(self):
        rows = parse_cvs_stores(CVS_ANSWER, "Home", radius=30)
        self.assertEqual([(r.store_id, r.qty, r.pickup) for r in rows], [("3948", 5, False), ("9174", 1, True)])
        self.assertTrue(rows[1].low)
        self.assertEqual(rows[0].zip, "89434")
        self.assertEqual(len(parse_cvs_stores(CVS_ANSWER, "Home", radius=50)), 3)

    def test_each_area_zip_is_asked(self):
        asked = []

        class FakeCVS(CVS):
            def fetch_html(self, url):
                return FetchResult(200, NORMAL_PAGE, url)

            def post_via_browser(self, url, payload, referer=""):
                asked.append(payload["getStoreDetailsAndInventoryRequest"]["addressLine"])
                return FetchResult(200, json.dumps(CVS_ANSWER), url)

            @staticmethod
            def pause(seconds):
                pass

        raw = {"settings": {"in_store": True, "link_delay_seconds": 0}, "retailers": {"cvs": {"enabled": True}}}
        areas = [Area("Home", "89501", 30), Area("Work", "10001", 10)]
        cfg = Config(path="x", raw=raw, watchlist=[], searches=[], keywords=KeywordFilter(), price_rules=[], areas=areas)
        out = FakeCVS(cfg, LOG, None).check_ids(["https://www.cvs.com/shop/x-prodid-619797"], True)
        self.assertEqual(asked, ["89501", "10001"])
        self.assertEqual(next(iter(out.values())).stores[0].store_id, "3948")


if __name__ == "__main__":
    unittest.main()
