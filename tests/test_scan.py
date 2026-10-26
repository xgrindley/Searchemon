"""Tests for the by-hand ZIP stock scan."""
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from restock import scan as scan_mod  # noqa: E402
from restock.engine import Monitor  # noqa: E402
from restock.models import StockResult, StoreStock  # noqa: E402
from restock.retailers.base import Blocked, Retailer  # noqa: E402

ZIP = "12345"          # Anytown, NV
POINT = (39.6, -119.7)  # fixed, so the tests do not depend on the zipcodes package (another test stubs it)


def make_monitor():
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "config.yaml")
    with open(path, "w") as fh:
        fh.write("discord: {webhooks: {default: ''}}\nareas: []\n"
                 "watchlist:\n  - {name: ETB, ids: {target: '111', cvs: '222'}, msrp: 49.99}\n")
    return Monitor(path)


def stores_around(point):
    lat, lon = point
    return [
        StoreStock("1", "Near Target", qty=4, lat=lat + 0.03, lon=lon, address="1 Main St", pickup=True),
        StoreStock("2", "Far Target", qty=9, lat=lat + 0.60, lon=lon),            # about 41 miles
        StoreStock("3", "Empty Target", qty=0, lat=lat + 0.02, lon=lon),
    ]


class FakeTarget(Retailer):
    name, display, supports_in_store = "target", "Target", True
    seen_cfg = None

    def __init__(self, cfg, log, browser=None):
        super().__init__(cfg, log, browser)
        FakeTarget.seen_cfg = cfg

    def check_ids(self, ids, in_store):
        pt = POINT
        return {i: StockResult("target", "Target", i, "Elite Trainer Box", f"https://www.target.com/p/-/A-{i}?utm_source=x",
                               price=59.99, online=True, online_status="IN_STOCK", stores=stores_around(pt)) for i in ids}


class SearchTarget(FakeTarget):
    asked: list = []

    def search(self, query, limit):
        mk = lambda i, t: StockResult("target", "Target", i, t, f"https://www.target.com/p/-/A-{i}")
        return [mk("900", "Pokemon Trading Card Game Scarlet & Violet Elite Trainer Box"),
                mk("901", "Pokemon Trading Card Game Booster Bundle"),
                mk("902", "Garden Hose 50 ft")]                      # not a card product

    def check_ids(self, ids, in_store):
        SearchTarget.asked.append(list(ids))
        return {i: StockResult("target", "Target", i, "Elite Trainer Box", f"https://www.target.com/p/-/A-{i}",
                               price=49.99, stores=stores_around(POINT)) for i in ids}


class BlockedCVS(Retailer):
    name, display, supports_in_store = "cvs", "CVS", True

    def check_ids(self, ids, in_store):
        raise Blocked("CVS refused the request", 600)


def run_scan(mon, radius=15, stores=None, online=False, wait=10, everything=False):
    ok, msg = mon.scan.start(ZIP, radius, stores, online, everything)
    assert ok, msg
    end = time.time() + wait
    while mon.scan.running and time.time() < end:
        time.sleep(0.05)
    return mon.scan.snapshot()


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.mon = make_monitor()
        for patcher in (mock.patch.dict(scan_mod.REGISTRY, {"target": FakeTarget, "cvs": BlockedCVS}),
                        mock.patch.object(scan_mod, "zip_point", lambda z: POINT),
                        mock.patch.object(scan_mod, "zip_place", lambda z: "Anytown, NV")):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_only_stores_inside_the_radius_with_stock_are_listed(self):
        snap = run_scan(self.mon, radius=15, stores=["target"])
        names = [r["store"] for r in snap["rows"]]
        self.assertEqual(names, ["Near Target"])          # far one outside 15 mi, empty one has 0 stock
        row = snap["rows"][0]
        self.assertTrue(0 < row["distance"] < 5)
        self.assertEqual(row["qty"], 4)
        self.assertTrue(row["over_msrp"])                 # 59.99 against a 49.99 MSRP plus 5%

    def test_wider_radius_finds_more_and_sorts_nearest_first(self):
        snap = run_scan(self.mon, radius=60, stores=["target"])
        self.assertEqual([r["store"] for r in snap["rows"]], ["Near Target", "Far Target"])
        self.assertLess(snap["rows"][0]["distance"], snap["rows"][1]["distance"])

    def test_tracking_parameters_are_stripped_from_links(self):
        snap = run_scan(self.mon, stores=["target"])
        self.assertNotIn("utm_", snap["rows"][0]["url"])

    def test_scan_uses_its_own_area_and_leaves_your_settings_alone(self):
        run_scan(self.mon, radius=22, stores=["target"])
        cfg = FakeTarget.seen_cfg
        self.assertEqual([(a.zip, a.radius) for a in cfg.areas], [(ZIP, 22.0)])
        self.assertEqual(cfg.location["zip"], ZIP)
        self.assertEqual(self.mon.cfg.areas, [])
        self.assertEqual(self.mon.cfg.location["zip"], "")

    def test_online_stock_only_when_asked(self):
        self.assertFalse(any(r["online"] for r in run_scan(self.mon, stores=["target"])["rows"]))
        self.assertTrue(any(r["online"] for r in run_scan(self.mon, stores=["target"], online=True)["rows"]))

    def test_a_blocked_store_does_not_stop_the_others(self):
        snap = run_scan(self.mon, stores=["target", "cvs"])
        self.assertEqual(snap["stores"]["cvs"]["state"], "bad")
        self.assertIn("Blocked", snap["stores"]["cvs"]["status"])
        self.assertEqual(snap["stores"]["target"]["state"], "ok")
        self.assertEqual(snap["state"], "done")

    def test_store_that_is_off_is_skipped_with_a_reason(self):
        self.mon.cfg.raw["retailers"]["target"]["enabled"] = False
        snap = run_scan(self.mon, stores=["target"])
        self.assertEqual(snap["stores"]["target"]["state"], "skip")
        self.assertEqual(snap["rows"], [])

    def test_bad_input_and_double_start_are_refused(self):
        self.assertFalse(self.mon.scan.start("abc", 10)[0])
        with mock.patch.object(scan_mod, "zip_point", lambda z: None):
            self.assertFalse(self.mon.scan.start("00000", 10)[0])
        self.assertFalse(self.mon.scan.start(ZIP, "far")[0])
        gate = mock.Mock(side_effect=lambda *a, **k: time.sleep(0.5) or {})
        with mock.patch.object(FakeTarget, "check_ids", gate):
            self.assertTrue(self.mon.scan.start(ZIP, 10, ["target"])[0])
            self.assertFalse(self.mon.scan.start(ZIP, 10, ["target"])[0])
            self.mon.scan.cancel()
            end = time.time() + 5
            while self.mon.scan.running and time.time() < end:
                time.sleep(0.05)

    def test_radius_is_capped(self):
        snap = run_scan(self.mon, radius=5000, stores=["target"])
        self.assertEqual(snap["radius"], float(scan_mod.MAX_RADIUS))

    def test_search_every_product_finds_products_you_never_added(self):
        SearchTarget.asked = []
        with mock.patch.dict(scan_mod.REGISTRY, {"target": SearchTarget}):
            snap = run_scan(self.mon, stores=["target"], everything=True)
        asked = {i for chunk in SearchTarget.asked for i in chunk}
        self.assertTrue({"900", "901"} <= asked)         # found by the live search, nothing added by hand
        self.assertNotIn("902", asked)                   # a garden hose is not a card product
        self.assertTrue(snap["everything"])
        self.assertTrue(snap["rows"])

    def test_the_stores_you_tick_are_the_stores_scanned_even_with_search_every_product(self):
        with mock.patch.dict(scan_mod.REGISTRY, {"target": SearchTarget}):
            snap = run_scan(self.mon, stores=["cvs"], everything=True)
        self.assertEqual(set(snap["stores"]), {"cvs"})

    def test_with_nothing_ticked_every_store_that_is_on_is_used(self):
        with mock.patch.dict(scan_mod.REGISTRY, {"target": SearchTarget}):
            snap = run_scan(self.mon, stores=[], everything=True)
        on = set(self.mon.cfg.enabled_retailers()) & set(scan_mod.SCAN_STORES)
        self.assertEqual(set(snap["stores"]), on)

    def test_walgreens_can_be_picked_and_reports_online_stock_only(self):
        class FakeWag(Retailer):
            name, display = "walgreens", "Walgreens"
            def check_ids(self, ids, in_store):
                return {i: StockResult("walgreens", "Walgreens", i, "Pokemon ETB", "https://www.walgreens.com/x", price=49.99,
                                       online=True, online_status="In stock") for i in ids}
        self.mon.cfg.watchlist[0].ids["walgreens"] = "prod1"
        with mock.patch.dict(scan_mod.REGISTRY, {"walgreens": FakeWag}), \
                mock.patch.object(type(self.mon.cfg), "enabled_retailers", lambda c: ["walgreens", "target", "cvs"]):
            snap = run_scan(self.mon, stores=["walgreens"], online=False)       # online is forced on for it
        self.assertIn("walgreens", snap["available"])
        self.assertEqual(snap["online_only"], ["walgreens"])
        self.assertTrue(any(r["retailer"] == "walgreens" and r["online"] for r in snap["rows"]))
        self.assertIn("no shelf stock", snap["stores"]["walgreens"]["status"])

    def test_cvs_needing_your_own_chrome_is_not_shown_as_blocked(self):
        class NeedsOwn(Retailer):
            name, display, supports_in_store = "cvs", "CVS", True
            def check_ids(self, ids, in_store):
                raise Blocked("CVS is rate limiting. This store usually allows your own Chrome. Start it", 600)
        with mock.patch.dict(scan_mod.REGISTRY, {"cvs": NeedsOwn}):
            snap = run_scan(self.mon, stores=["cvs"])
        st = snap["stores"]["cvs"]
        self.assertEqual(st["state"], "skip")
        self.assertNotIn("Blocked", st["status"])

    def test_search_every_product_skips_types_you_turned_alerts_off_for(self):
        SearchTarget.asked = []
        self.mon.cfg.raw["product_types"] = {"booster_bundle": {"alert": False}}
        with mock.patch.dict(scan_mod.REGISTRY, {"target": SearchTarget}):
            run_scan(self.mon, stores=["target"], everything=True)
        asked = {i for chunk in SearchTarget.asked for i in chunk}
        self.assertNotIn("901", asked)                   # the Booster Bundle type is turned off
        self.assertIn("900", asked)

    def test_off_keeps_the_old_behaviour(self):
        SearchTarget.asked = []
        with mock.patch.dict(scan_mod.REGISTRY, {"target": SearchTarget}):
            run_scan(self.mon, stores=["target"], everything=False)
        asked = {i for chunk in SearchTarget.asked for i in chunk}
        self.assertNotIn("900", asked)

    def test_nothing_is_written_to_disk(self):
        data = os.path.join(os.path.dirname(self.mon.config_path), "data")
        before = set(os.listdir(data)) if os.path.isdir(data) else set()
        run_scan(self.mon, stores=["target"])
        after = set(os.listdir(data)) if os.path.isdir(data) else set()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
