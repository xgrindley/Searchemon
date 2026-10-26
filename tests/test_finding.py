"""Product finding without links: the store-page readers, the browser fallback for script-built results,
Target's search-page fallback, stores that need a key, and discovery's search plan. All offline."""
import logging
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from restock.config import load_config  # noqa: E402
from restock.engine import TYPE_QUERIES, Monitor  # noqa: E402
from restock.models import StockResult  # noqa: E402
from restock.retailers.base import Blocked  # noqa: E402
from restock.retailers.blocks import classify  # noqa: E402
from restock.retailers.browser import FetchResult  # noqa: E402
from restock.retailers.kroger import Kroger  # noqa: E402
from restock.retailers.pages import BarnesAndNoble, BooksAMillion, CVS, GameStop, WebPage, gamestop_product_id  # noqa: E402
from restock.retailers.target import Target  # noqa: E402

OFF = "\n".join(f"  {r}: {{enabled: false}}" for r in (
    "bestbuy", "walmart", "pokemoncenter", "gamestop", "costco", "samsclub", "barnesandnoble",
    "booksamillion", "amazon", "dicks", "safeway", "raleys", "walgreens", "cvs", "web", "target"))
CFG = ("discord: {webhooks: {default: ''}}\nsettings: {windows_toast: false, link_delay_seconds: 0}\n"
       "discovery: {enabled: true, places: false, queries: [pokemon tcg]}\nbrowser: {enabled: false}\n"
       f"retailers:\n{OFF}\n")

BAM_PAGE = ('<a href="https://www.booksamillion.com/p/Pok%C3%A9mon-Mega-Evolution-Pitch-Black/Pok%C3%A9mon/F196214157422">'
            'Pok&eacute;mon TCG: Mega Evolution - Pitch Black Elite Trainer Box</a>'
            '<a href="https://www.booksamillion.com/search?query=pokemon">search</a>')
GAMESTOP_PAGE = ('<div class="product-tile" data-pid="445743"><a class="pdp-link" href=""></a></div>'
                 '<div class="product-tile" data-pid="445745"></div><div data-pid="445743"></div>')
WALGREENS_CHALLENGE = ('<!DOCTYPE html><html><head><title>Challenge Validation</title><script>function cp_clge_done(){}</script>'
                       '</head><body><iframe id="sec-cpt-if" provider="crypto"></iframe></body></html>')
TARGET_PAGE = ('<a href="/p/pokemon-trading-card-game-mega-evolution-elite-trainer-box/-/A-94300069" data-test="product-title">'
               'Pokémon Trading Card Game: Mega Evolution Elite Trainer Box</a>'
               '<a href="https://www.target.com/p/pokemon-tcg-booster-bundle/-/A-94300070"><img></a>')


def close_logs():
    for h in list(logging.getLogger("restock").handlers):
        h.close()
        logging.getLogger("restock").removeHandler(h)


class Tmp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "config.yaml")
        with open(self.path, "w") as fh:
            fh.write(CFG)
        self.cfg = load_config(self.path)
        self.log = logging.getLogger("test-finding")

    def tearDown(self):
        close_logs()
        shutil.rmtree(self.dir, ignore_errors=True)

    def store(self, cls, browser=None):
        r = cls(self.cfg, self.log, browser)
        r.pause = lambda s: None
        return r


class ReaderTests(Tmp):
    def test_books_a_million_links_and_barcodes(self):
        r = self.store(BooksAMillion)
        items = r.read_listing(BAM_PAGE)
        self.assertEqual(len(items), 1)
        url, title = items[0]
        self.assertIn("Elite Trainer Box", title)
        self.assertEqual(WebPage.upc_from_link(url), "196214157422")
        self.assertIsNone(WebPage.upc_from_link("https://www.gamestop.com/products/x/20012345.html"))

    def test_gamestop_tiles_built_by_script_are_read_from_their_ids(self):
        r = self.store(GameStop)
        urls = [u for u, _ in r.read_listing(GAMESTOP_PAGE)]
        self.assertEqual(len(urls), 2)
        self.assertEqual([gamestop_product_id(u) for u in urls], ["445743", "445745"])
        self.assertEqual(gamestop_product_id("https://www.gamestop.com/toys/products/x/20012345.html"), "20012345")

    def test_walgreens_challenge_page_is_recognized(self):
        info = classify(200, WALGREENS_CHALLENGE)
        self.assertIsNotNone(info)
        self.assertEqual((info.vendor, info.kind, info.needs_human), ("Akamai", "challenge", False))

    def test_search_words_are_encoded_for_where_they_go(self):
        self.assertTrue(self.store(BarnesAndNoble).search_address("pokemon tcg").endswith("/s/pokemon%20tcg"))
        self.assertIn("searchTerm=pokemon+tcg", self.store(CVS).search_address("pokemon tcg"))


class BrowserFallbackTests(Tmp):
    def test_empty_plain_page_falls_back_to_the_browser_and_remembers(self):
        browser = mock.Mock(usable=True)
        r = self.store(BooksAMillion, browser)
        r.fetch_html = mock.Mock(return_value=FetchResult(200, "<html>no results here</html>", "u", None))
        r._via_browser = mock.Mock(return_value=FetchResult(200, BAM_PAGE, "u", None))
        found = r.search("pokemon tcg", 10)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].upc, "196214157422")
        self.assertIn("wait_re", r._via_browser.call_args.kwargs)        # waits for results to appear
        r.fetch_html.reset_mock()
        r.search("pokemon etb", 10)
        r.fetch_html.assert_not_called()                                    # straight to the browser next time

    def test_a_browser_that_cannot_start_falls_back_to_a_plain_request(self):
        browser = mock.Mock()
        browser.usable = True
        r = self.store(BarnesAndNoble, browser)                             # normally searched in the browser

        def fail(*a, **k):
            browser.usable = False
            raise Blocked("Barnes & Noble: browser could not start", 1800)
        r._via_browser = mock.Mock(side_effect=fail)
        r.fetch_html = mock.Mock(return_value=FetchResult(
            200, '<a href="/w/pokemon-tcg-elite-trainer-box/1234567?ean=196214157422">Pokemon TCG Elite Trainer Box</a>', "u", None))
        self.assertEqual(len(r.search("pokemon", 10)), 1)

    def test_names_are_remembered_so_pages_are_not_reopened(self):
        r = self.store(GameStop)
        r.fetch_html = mock.Mock(side_effect=lambda url: FetchResult(
            200, '<html><title>Pokemon TCG Elite Trainer Box | GameStop</title></html>' if "Product-Show" in url else GAMESTOP_PAGE, url, None))
        r.category_urls = ()
        first = r.search("pokemon", 10)
        opened = sum("Product-Show" in c.args[0] for c in r.fetch_html.call_args_list)
        r.fetch_html.reset_mock()
        r.search("pokemon", 10)
        again = sum("Product-Show" in c.args[0] for c in r.fetch_html.call_args_list)
        self.assertEqual(len(first), 2)
        self.assertEqual((opened, again), (2, 0))


class TargetTests(Tmp):
    def test_blocked_data_search_reads_the_search_page_instead(self):
        browser = mock.Mock(usable=True)
        t = self.store(Target, browser)
        t._search_raw = mock.Mock(side_effect=Blocked("Target asked for a bot check (PerimeterX)", 900))
        t._via_browser = mock.Mock(return_value=FetchResult(200, TARGET_PAGE, "u", None))
        found = t.search("pokemon trading card game", 20)
        self.assertEqual([f.product_id for f in found], ["94300069", "94300070"])
        self.assertIn("Elite Trainer Box", found[0].title)
        self.assertIn("Booster Bundle", found[1].title)                  # named from the link when it shows no text
        self.assertEqual(found[0].online_status, "UNCHECKED")

    def test_a_blocked_search_page_backs_off_without_pausing_target(self):
        browser = mock.Mock(usable=True)
        t = self.store(Target, browser)
        t._search_raw = mock.Mock(return_value=[])
        t._via_browser = mock.Mock(side_effect=Blocked("Target asked for a bot check (PerimeterX)", 3600))
        self.assertEqual(t.search("pokemon tcg", 20), [])                 # no exception: product checks carry on
        self.assertEqual(t.search("pokemon etb", 20), [])
        self.assertEqual(t._via_browser.call_count, 1)                   # the page is not hammered again for hours

    def test_without_a_browser_a_blocked_search_finds_nothing_quietly(self):
        t = self.store(Target, None)
        t._search_raw = mock.Mock(return_value=[])
        self.assertEqual(t.search("pokemon", 20), [])


class SetupNeededTests(Tmp):
    def test_kroger_without_a_key_says_so_and_is_not_counted_as_blocked(self):
        with open(self.path, "w") as fh:
            fh.write(CFG.replace("  kroger: {enabled: false}\n", "") + "  kroger: {enabled: true}\n")
        mon = Monitor(self.path)
        r = mon.retailers["kroger"]
        self.assertIn("free Kroger key", r.setup_needed())
        stop, wake = threading.Event(), mock.Mock()
        wake.wait.side_effect = lambda t=None: stop.set()
        statuses = []
        with mock.patch.object(mon, "emit", side_effect=lambda *e: statuses.append(e)), \
                mock.patch.object(mon, "run_cycle") as cycle:
            mon._loop("kroger", 0, stop, wake)
        cycle.assert_not_called()
        self.assertTrue(any(e[0] == "status" and "free Kroger key" in e[2] for e in statuses))
        self.assertEqual(mon.store_history.recent("kroger"), [])
        mon.close()

    def test_kroger_with_a_key_is_ready(self):
        cfg = load_config(self.path)
        cfg.raw["retailers"]["kroger"].update({"client_id": "a", "client_secret": "b"})
        self.assertEqual(Kroger(cfg, self.log).setup_needed(), "")


class DiscoveryPlanTests(Tmp):
    def mon_with(self, search):
        mon = Monitor(self.path)
        r = mock.Mock(display="Shop", search_url="", supports_search=True)
        r.name = "shop"
        r.search = mock.Mock(side_effect=search)
        r.seed_products = mock.Mock(return_value=[])
        return mon, r

    def test_type_searches_rotate_and_one_failure_does_not_end_the_run(self):
        asked = []

        def search(q, n):
            asked.append(q)
            if q == TYPE_QUERIES[0]:
                raise ValueError("odd page")
            return [StockResult("shop", "Shop", "1", "Pokemon TCG Elite Trainer Box", "https://x.test/1")]
        mon, r = self.mon_with(search)
        d = mon.cfg.raw["discovery"]
        mon._discover(r, d)
        mon._discover(r, d)
        self.assertEqual(asked[0], "pokemon tcg")
        self.assertEqual(asked[1:3], list(TYPE_QUERIES[0:2]))
        self.assertEqual(asked[4:6], list(TYPE_QUERIES[2:4]))            # the next refresh asks the next two types
        self.assertIn("shop:1", mon.catalog.items)
        mon.close()

    def test_every_search_failing_is_reported(self):
        mon, r = self.mon_with(lambda q, n: (_ for _ in ()).throw(ValueError("broken")))
        with self.assertRaises(ConnectionError):
            mon._discover(r, mon.cfg.raw["discovery"])
        mon.close()

    def test_only_two_stores_search_at_once(self):
        mon = Monitor(self.path)
        running, peak, lock = [0], [0], threading.Lock()

        def slow(*a):
            with lock:
                running[0] += 1
                peak[0] = max(peak[0], running[0])
            time.sleep(0.15)
            with lock:
                running[0] -= 1
        mon._discover = slow
        mon.catalog.due = lambda name, hours: True
        stores = []
        for i in range(5):
            r = mock.Mock(display=f"S{i}", search_url="https://x.test/{q}", supports_search=True, search_has_stock=False)
            r.name = f"s{i}"
            r.signals.return_value = []
            stores.append(r)
        with mock.patch.object(mon, "_discovery_on", return_value=True), mock.patch.object(mon, "targets_for", return_value={}):
            threads = [threading.Thread(target=mon.run_cycle, args=(r,)) for r in stores]
            for t in threads:
                t.start()
            for t in threads:
                t.join(5)
        self.assertEqual(peak[0], 2)
        mon.close()

    def test_side_by_side_tests_only_run_at_stores_with_recent_trouble(self):
        mon = Monitor(self.path)
        self.assertFalse(mon._troubled("gamestop"))
        mon.store_history.record("gamestop", False, "blocked")
        self.assertTrue(mon._troubled("gamestop"))
        mon.close()


if __name__ == "__main__":
    unittest.main()
