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


class FakeInPage:
    """Stands in for the browser pool and records page-fetch calls."""
    usable = True

    def __init__(self, text='{"ok": 1}', status=200, block=None):
        self.calls, self.text, self.status, self.block = [], text, status, block

    def fetch(self, url, timeout=120, post=None, referer="", page_get=False):
        self.calls.append((url, referer, page_get))
        return FetchResult(self.status, self.text, url, self.block, profile="edge")


class PageFetchTests(unittest.TestCase):
    def target(self, browser, page_fetch=True):
        from restock.retailers.target import Target
        raw = {"settings": {}, "retailers": {"target": {"enabled": True}}, "browser": {"page_fetch": page_fetch}}
        cfg = Config(path="x", raw=raw, watchlist=[], searches=[], keywords=KeywordFilter(), price_rules=[], areas=[])
        t = Target(cfg, LOG, browser)
        return t

    def test_refused_plain_request_is_retried_from_inside_the_page(self):
        from restock.retailers.base import Blocked
        b = FakeInPage()
        t = self.target(b)

        def refuse(*a, **k):
            raise Blocked("Target refused", 60)
        t.get = refuse
        data = t.get_json("https://redsky.target.com/redsky_aggregations/v1/web/x", params={"a": "1"})
        self.assertEqual(data, {"ok": 1})
        self.assertEqual(b.calls[0][0], "https://redsky.target.com/redsky_aggregations/v1/web/x?a=1")
        self.assertEqual(b.calls[0][1:], ("https://www.target.com/", True))

    def test_stays_blocked_when_the_page_also_fails_or_is_off(self):
        from restock.retailers.base import Blocked
        for browser, on in ((FakeInPage(status=403), True), (FakeInPage(), False), (None, True)):
            t = self.target(browser, page_fetch=on)

            def refuse(*a, **k):
                raise Blocked("Target refused", 60)
            t.get = refuse
            with self.assertRaises(Blocked):
                t.get_json("https://redsky.target.com/x")


class OwnEdgeTests(unittest.TestCase):
    def pool(self, **b):
        from restock.retailers.browser import BrowserPool
        from restock.sessions import BlockTracker
        with tempfile.TemporaryDirectory() as d:
            p = BrowserPool({"browser": dict({"profiles": [{"name": "a"}]}, **b)}, d, LOG, tracker=BlockTracker(d))
        return p

    def test_edge_and_chrome_both_join_on_their_own_ports(self):
        from unittest import mock
        p = self.pool(own_chrome_port=9222, own_edge_port=9223)
        with mock.patch("restock.retailers.browser._port_open", return_value=True):
            p._own_looked = 0
            p._maybe_attach_own_chrome()
            p._own_looked = 0
            p._maybe_attach_own_chrome()
        names = [w.name for w in p.workers]
        self.assertEqual(sorted(n for n in names if n.startswith("my-")), ["my-chrome", "my-edge"])
        self.assertEqual(next(w for w in p.workers if w.name == "my-edge").cdp_url, "http://127.0.0.1:9223")

    def test_edge_off_when_port_is_zero(self):
        from unittest import mock
        p = self.pool(own_chrome_port=0, own_edge_port=0)
        with mock.patch("restock.retailers.browser._port_open", return_value=True):
            p._maybe_attach_own_chrome()
        self.assertEqual([w.name for w in p.workers], ["a"])

    def test_in_page_calls_are_counted_as_their_own_method(self):
        from restock.retailers.browser import BrowserPool
        from restock.sessions import BlockTracker

        class W:
            name, usable, failed, thread = "edge", True, "", None
            on_reopen = None

            def waiting_domains(self):
                return []

            def fetch(self, url, timeout=120, ask=True, post=None, referer="", page_get=False):
                return FetchResult(200, "{}", url, None, via="edge", profile="edge")

            def stop(self):
                pass
        with tempfile.TemporaryDirectory() as d:
            tr = BlockTracker(d)
            p = BrowserPool({"browser": {"profiles": [{"name": "a"}]}}, d, LOG, tracker=tr)
            p.workers = [W()]
            p.fetch("https://redsky.target.com/x", referer="https://www.target.com/", page_get=True)
            p.fetch("https://www.target.com/p", )
            methods = {r["method"] for r in tr.rows()}
        self.assertEqual(methods, {"edge+page", "edge"})


class SideBySideTests(unittest.TestCase):
    def setup(self, every=15):
        from restock.compare import SideBySide
        from restock.retailers.browser import BrowserPool

        class W:
            def __init__(self, name, blocked=False):
                self.name, self.blocked, self.usable, self.failed, self.thread = name, blocked, True, "", None
                self.calls = 0

            def waiting_domains(self):
                return []

            def fetch(self, url, timeout=120, ask=True, **kw):
                from restock.retailers.blocks import BlockInfo
                self.calls += 1
                assert ask is False                      # a comparison never pops a window for a person
                block = BlockInfo("Akamai", "denied", False) if self.blocked else None
                return FetchResult(403 if block else 200, "x", url, block, via=self.name, profile=self.name)

            def stop(self):
                pass
        d = tempfile.mkdtemp()
        pool = BrowserPool({"browser": {"profiles": [{"name": "a"}], "compare_every_minutes": every}}, d, LOG)
        pool.workers = [W("edge"), W("chrome", blocked=True)]
        sbs = SideBySide(d, LOG, pool)
        sbs._plain = lambda url: (True, "")
        return sbs, pool

    def test_every_method_runs_together_and_blocks_rest_the_profile(self):
        sbs, pool = self.setup()
        out = sbs.run("cvs", "https://www.cvs.com/shop/x-prodid-1")
        self.assertEqual(set(out), {"direct", "edge", "chrome"})
        self.assertTrue(out["edge"]["ok"] and not out["chrome"]["ok"])
        self.assertEqual(out["chrome"]["kind"], "denied")
        self.assertGreater(pool.rest[("chrome", "www.cvs.com")], 0)
        rows = {(r["store"], r["method"]): r for r in sbs.rows()}
        self.assertEqual(rows[("cvs", "edge")]["ok"], 1)
        self.assertFalse(rows[("cvs", "chrome")]["last_ok"])
        # a resting profile sits the next run out
        again = sbs.run("cvs", "https://www.cvs.com/shop/x-prodid-1")
        self.assertEqual(set(again), {"direct", "edge"})

    def test_due_only_every_n_minutes_and_off_at_zero(self):
        import time
        sbs, _ = self.setup(every=15)
        started = []
        sbs._guarded = lambda store, url: started.append(store)
        self.assertTrue(sbs.maybe_run("cvs", "https://www.cvs.com/x"))
        sbs.running.discard("cvs")
        self.assertFalse(sbs.maybe_run("cvs", "https://www.cvs.com/x"))     # just ran
        sbs.last_run["cvs"] = time.time() - 16 * 60
        self.assertTrue(sbs.maybe_run("cvs", "https://www.cvs.com/x"))
        off, _ = self.setup(every=0)
        self.assertFalse(off.maybe_run("cvs", "https://www.cvs.com/x"))


class LearnedRoutingTests(unittest.TestCase):
    def test_reliable_methods_go_first_and_refused_ones_last(self):
        from restock.retailers.browser import BrowserPool
        from restock.sessions import BlockTracker

        class W:
            usable, failed, thread, on_reopen = True, "", None, None

            def __init__(self, name):
                self.name, self.seen = name, 0

            def waiting_domains(self):
                return []

            def fetch(self, url, timeout=120, ask=True, **kw):
                self.seen += 1
                return FetchResult(200, "x", url, None, via=self.name, profile=self.name)

            def stop(self):
                pass
        with tempfile.TemporaryDirectory() as d:
            pool = BrowserPool({"browser": {"profiles": [{"name": "a"}], "own_chrome_port": 0, "own_edge_port": 0}}, d, LOG,
                               tracker=BlockTracker(d))
            ws = [W("edge"), W("chrome"), W("other")]
            pool.workers = ws
            pool.prefer = lambda site: {"chrome": 1.0, "edge": 0.1} if site == "cvs.com" else {}
            for _ in range(3):
                pool.fetch("https://www.cvs.com/x")
            self.assertEqual((ws[1].seen, ws[0].seen), (3, 0))       # chrome always, edge never first
            for _ in range(3):
                pool.fetch("https://www.target.com/x")                # no data: plain rotation
            self.assertTrue(all(w.seen >= 1 for w in ws))

    def test_rates_need_enough_runs_and_find_the_store_by_site(self):
        from restock.compare import SideBySide
        d = tempfile.mkdtemp()
        sbs = SideBySide(d, LOG, None)
        sbs.data = {"_domains": {"cvs": "cvs.com"},
                    "cvs": {"edge": [{"ok": True}] * 4, "chrome": [{"ok": True}] * 8 + [{"ok": False}] * 2}}
        self.assertEqual(sbs.rates("www.cvs.com".removeprefix("www.")), {"chrome": 0.8})
        self.assertEqual(sbs.rates("target.com"), {})


class FeatureTrialTests(unittest.TestCase):
    def make(self, on=True):
        from restock.features import FeatureTrial
        d = tempfile.mkdtemp()
        raw = {"browser": {"feature_trial": on}}
        return FeatureTrial(d, lambda: raw), d

    def test_trial_splits_roughly_half_and_off_always_uses_the_feature(self):
        t, _ = self.make(True)
        used = sum(t.decide("learned_routing") for _ in range(400))
        self.assertTrue(140 < used < 260, used)
        self.assertFalse(t.decide("learned_routing", configured=False))
        off, _ = self.make(False)
        self.assertTrue(all(off.decide("tab_rotation") for _ in range(50)))
        off.record("tab_rotation", True, False)
        self.assertEqual(off.rows()[1]["with_checks"], 0)          # nothing is counted when the trial is off

    def test_verdicts(self):
        t, d = self.make(True)
        self.assertEqual(t.rows()[0]["verdict"], "Too early to say")
        for _ in range(40):
            t.record("learned_routing", True, True)
        for i in range(40):
            t.record("learned_routing", False, i % 4 != 0)         # 25% blocked without it
        self.assertEqual(t.rows()[0]["verdict"], "Helping")
        t.save()
        from restock.features import FeatureTrial
        again = FeatureTrial(d, lambda: {"browser": {}})
        self.assertEqual(again.rows()[0]["without_blocks"], 10)    # kept between runs
        for _ in range(40):
            t.record("tab_rotation", True, False)
            t.record("tab_rotation", False, True)
        self.assertEqual(t.rows()[1]["verdict"], "Not helping")

    def test_pool_counts_each_check_under_the_right_side(self):
        from restock.features import FeatureTrial
        from restock.retailers.browser import BrowserPool
        from restock.sessions import BlockTracker

        class W:
            usable, failed, thread, on_reopen = True, "", None, None
            name = "edge"

            def waiting_domains(self):
                return []

            def fetch(self, url, timeout=120, ask=True, **kw):
                return FetchResult(200, "x", url, None, via="edge", profile="edge")

            def stop(self):
                pass
        with tempfile.TemporaryDirectory() as d:
            raw = {"browser": {"profiles": [{"name": "a"}], "own_chrome_port": 0, "own_edge_port": 0, "tabs_per_site": 3,
                               "feature_trial": True}}
            pool = BrowserPool(raw, d, LOG, tracker=BlockTracker(d))
            pool.workers = [W()]
            pool.prefer = lambda site: {}
            pool.trial = FeatureTrial(d, lambda: raw)
            for _ in range(60):
                pool.fetch("https://www.example.com/x")
            rows = {r["feature"]: r for r in pool.trial.rows()}
        for key in ("learned_routing", "tab_rotation"):
            self.assertEqual(rows[key]["with_checks"] + rows[key]["without_checks"], 60)
            self.assertGreater(rows[key]["with_checks"], 10)
            self.assertGreater(rows[key]["without_checks"], 10)


if __name__ == "__main__":
    unittest.main()
