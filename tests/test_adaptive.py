"""The adaptive check schedule for found listings, blocking price-gouging marketplace sellers, and the new stores
(Macy's, Kohl's). All offline."""
import logging
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from restock import catalog as catmod  # noqa: E402
from restock.catalog import Catalog, wait_after  # noqa: E402
from restock.config import ALL_RETAILERS, load_config  # noqa: E402
from restock.engine import Monitor  # noqa: E402
from restock.models import StockResult  # noqa: E402
from restock.retailers import REGISTRY, route_url  # noqa: E402
from restock.sellers import SellerWatch  # noqa: E402

CFG = ("discord: {webhooks: {default: 'https://discord.com/api/webhooks/1/a'}}\n"
       "settings: {windows_toast: false, confirm_restocks: false, alert_cooldown_minutes: 0, retailer_sold_only: false}\n"
       "discovery: {enabled: false, places: false}\nbrowser: {enabled: false}\n")


def listing(store, pid, title="Pokemon TCG Black Bolt Booster Bundle", price=26.99, upc=None):
    return StockResult(store, store.title(), pid, title, f"https://x.test/{pid}", price=price, upc=upc, online_status="UNCHECKED")


class Tmp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "config.yaml")
        with open(self.path, "w") as fh:
            fh.write(CFG)
        self.raw = load_config(self.path).raw

    def tearDown(self):
        for h in list(logging.getLogger("restock").handlers):
            h.close()
            logging.getLogger("restock").removeHandler(h)
        shutil.rmtree(self.dir, ignore_errors=True)


class ScheduleTests(Tmp):
    def test_the_formula(self):
        self.assertEqual([wait_after(m) for m in (0, 4)], [0, 0])          # the first misses cost nothing
        self.assertEqual(wait_after(5), 30 * 60)
        self.assertEqual(wait_after(10), 60 * 60)
        self.assertEqual(wait_after(15), 2 * 3600)
        self.assertEqual(wait_after(500), 24 * 3600)                      # never more than a day: never "never"

    def check(self, cat, store, pid, in_stock=False, price=26.99, over_cap=False):
        cat.note_stock(StockResult(store, store, pid, "t", "u", price=price, online=in_stock), over_cap=over_cap)

    def test_a_listing_never_in_stock_is_checked_less_and_less_but_never_dropped(self):
        cat = Catalog(self.dir)
        cat.merge("bam", [listing("bam", "1")], self.raw, mark_run=True)
        for _ in range(12):
            self.check(cat, "bam", "1")
        item = cat.items["bam:1"]
        self.assertEqual(item["misses"], 12)
        self.assertGreater(item["next_due"], time.time() + 50 * 60)        # waits about an hour now
        self.assertEqual(cat.rotation("bam", 5, {}), [])                    # not due: skipped this round
        item["next_due"] = time.time() - 1
        self.assertEqual(len(cat.rotation("bam", 5, {})), 1)                # due again: checked
        self.assertIn("Checked less often", cat.schedule_view({**item, "next_due": time.time() + 3600})["text"])

    def test_stock_a_price_change_or_a_restock_elsewhere_resets_it(self):
        cat = Catalog(self.dir)
        cat.merge("bam", [listing("bam", "1", upc="196214110001")], self.raw, mark_run=True)
        cat.merge("gamestop", [listing("gamestop", "9", upc="196214110001")], self.raw, mark_run=True)
        for _ in range(20):
            self.check(cat, "bam", "1")
        self.assertGreater(cat.items["bam:1"]["next_due"], time.time() + 3600)
        self.check(cat, "bam", "1", price=19.99)                             # price moved: worth a look soon
        self.assertEqual(cat.items["bam:1"]["misses"], catmod.FREE_MISSES - 1)
        self.assertEqual(cat.items["bam:1"]["next_due"], 0)
        for _ in range(20):
            self.check(cat, "bam", "1", price=19.99)
        cat.boost_siblings(StockResult("gamestop", "GameStop", "9", "t", "u", online=True))
        self.assertEqual(cat.items["bam:1"]["next_due"], 0)                  # restocked at another store
        self.check(cat, "bam", "1", in_stock=True, price=19.99)
        self.assertEqual(cat.items["bam:1"]["misses"], 0)

    def test_priced_over_your_limit_counts_as_a_miss(self):
        cat = Catalog(self.dir)
        cat.merge("bam", [listing("bam", "1", price=54.99)], self.raw, mark_run=True)
        for _ in range(6):
            self.check(cat, "bam", "1", in_stock=True, price=54.99, over_cap=True)
        self.assertEqual(cat.items["bam:1"]["misses"], 6)
        self.assertEqual(cat.items["bam:1"]["over_cap"], 6)

    def test_longest_waiting_listing_goes_first(self):
        cat = Catalog(self.dir)
        cat.merge("bam", [listing("bam", str(i), title=f"Pokemon TCG Booster Bundle {i}") for i in range(3)], self.raw, mark_run=True)
        now = time.time()
        for i, ago in enumerate((60, 600, 6000)):
            cat.items[f"bam:{i}"]["last_checked"] = now - ago
        self.assertEqual([v["id"] for v in cat.rotation("bam", 3, {})], ["2", "1", "0"])


class SellerTests(Tmp):
    def test_a_gouging_seller_is_blocked_and_let_back_when_it_prices_fairly(self):
        sw = SellerWatch(self.dir)
        for price in (54.99, 59.99, 49.99):
            sw.record("walmart", "Cards4Less LLC", price, 26.99, 28.34, "Booster Bundle")
        blocked, why = sw.blocked("walmart", "cards4less llc")
        self.assertTrue(blocked, why)
        self.assertIn("over MSRP", why)
        for _ in range(5):
            sw.record("walmart", "Cards4Less LLC", 26.99, 26.99, 28.34)
        self.assertFalse(sw.blocked("walmart", "Cards4Less LLC")[0])

    def test_two_offers_are_not_enough_to_judge_and_a_small_markup_is_not_gouging(self):
        sw = SellerWatch(self.dir)
        sw.record("amazon", "A", 60, 27, 28)
        sw.record("amazon", "A", 60, 27, 28)
        self.assertFalse(sw.blocked("amazon", "A")[0])
        for _ in range(4):
            sw.record("amazon", "B", 29.5, 27, 28)          # over the 5% limit, but only ~9% over MSRP
        self.assertFalse(sw.blocked("amazon", "B")[0])

    def test_your_choice_wins_and_is_saved(self):
        sw = SellerWatch(self.dir)
        sw.record("walmart", "Fair Seller", 26.99, 26.99, 28.34)
        key = sw.key("walmart", "Fair Seller")
        self.assertTrue(sw.set_mode(key, "block"))
        self.assertTrue(SellerWatch(self.dir).blocked("walmart", "Fair Seller")[0])
        sw.set_mode(key, "allow")
        self.assertFalse(sw.blocked("walmart", "Fair Seller")[0])

    def test_the_monitor_skips_a_blocked_seller_and_checks_its_listing_less(self):
        posts = []
        with mock.patch("restock.notify.requests.post", side_effect=lambda url, json=None, timeout=None:
                        (posts.append(json), mock.Mock(status_code=204))[1]):
            mon = Monitor(self.path)
            mon.catalog.merge("walmart", [listing("walmart", "5", title="Pokemon TCG Booster Bundle", price=59.99)], mon.cfg.raw, mark_run=True)
            for i in range(4):
                res = StockResult("walmart", "Walmart", "5", "Pokemon TCG Booster Bundle", "https://www.walmart.com/ip/5",
                                  price=59.99 - i, online=True, third_party=True, seller="Cards4Less LLC")
                mon.handle(res, None, None)
            self.assertEqual(posts, [])                                     # over the limit, then blocked as a seller
            self.assertTrue(mon.sellers.blocked("walmart", "Cards4Less LLC")[0])
            self.assertTrue(res.note.startswith("ignored:"), res.note)
            self.assertGreaterEqual(mon.catalog.items["walmart:5"]["misses"], 4)
            mon.close()


class NewStoreTests(unittest.TestCase):
    def test_macys_and_kohls_are_full_stores(self):
        for name in ("macys", "kohls"):
            self.assertIn(name, REGISTRY)
            self.assertIn(name, ALL_RETAILERS)
            self.assertTrue(REGISTRY[name].supports_search)
        self.assertEqual(route_url("https://www.macys.com/shop/product/pokemon-etb?ID=123")[0], "macys")
        self.assertEqual(route_url("https://www.kohls.com/product/prd-123/pokemon-etb.jsp")[0], "kohls")


if __name__ == "__main__":
    unittest.main()
