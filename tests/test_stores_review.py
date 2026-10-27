"""v5.1 store fixes (Walgreens, CVS, Sam's Club, Costco, Kroger, Target titles) and the To review list. Offline."""
import json
import logging
import os
import shutil
import sys
import tempfile
import unittest
import urllib.request
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from restock.catalog import Catalog  # noqa: E402
from restock.config import load_config  # noqa: E402
from restock.engine import Monitor  # noqa: E402
from restock.models import StockResult  # noqa: E402
from restock.notify import DiscordNotifier  # noqa: E402
from restock.retailers import REGISTRY  # noqa: E402
from restock.retailers.base import Blocked  # noqa: E402
from restock.retailers.browser import FetchResult  # noqa: E402
from restock.retailers.pages import clean_listing_title, parse_listing  # noqa: E402
from restock.review import ReviewQueue, review_id  # noqa: E402
from restock.tcg import classify  # noqa: E402

LOG = logging.getLogger("t")
CFG = ("discord: {webhooks: {default: ''}}\nsettings: {windows_toast: false, confirm_restocks: false}\n"
       "discovery: {enabled: false, places: false}\nbrowser: {enabled: false}\n")


class Tmp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "config.yaml")
        with open(self.path, "w") as fh:
            fh.write(CFG)

    def tearDown(self):
        for h in list(logging.getLogger("restock").handlers):
            h.close()
            logging.getLogger("restock").removeHandler(h)
        shutil.rmtree(self.dir, ignore_errors=True)


class TitleTests(unittest.TestCase):
    def test_store_listing_text_is_removed_from_names(self):
        raw = ("300+ bought in last month $17.79 reg&nbsp; $19.99 Sale New at Pokemon ME4 Mega Evolution Chaos Rising "
               "Checklane Blister | Toxel 2.1 2.06 out of 5 stars (17) Shipping arrives Tue, Nov 3 Ships free - exclusions apply")
        self.assertEqual(clean_listing_title(raw), "Pokemon ME4 Mega Evolution Chaos Rising Checklane Blister | Toxel")
        self.assertEqual(clean_listing_title("Pokemon TCG Booster Bundle"), "Pokemon TCG Booster Bundle")

    def test_saved_names_are_cleaned_on_start(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "catalog.json"), "w") as fh:
            json.dump({"items": {"target:1": {"retailer": "target", "id": "1", "title": "$24.99 New at Pokemon 30th Celebration "
                                              "Booster Pack 1.3 1.32 out of 5 stars (66) Shipping arrives Tue, Nov 3"}}}, fh)
        self.assertEqual(Catalog(d).items["target:1"]["title"], "Pokemon 30th Celebration Booster Pack")
        shutil.rmtree(d, ignore_errors=True)

    def test_clothing_and_model_kits_are_not_card_product(self):
        for t in ("Big & Tall Pokemon Eevee Evolution Tarot Card Graphic Tee", "Juniors Pokemon Pikachu T-Shirt",
                  "Pokemon Bulbasaur 3D Model Kit Kanto Starter Collection", "Pokemon 4D Build Charizard 223 Piece 3D Puzzle"):
            self.assertFalse(classify(t).is_tcg, t)
        for t in ("Pokemon TCG Mega Evolution Build & Battle Box", "Pokemon TCG 30th Celebration Figure Collection"):
            self.assertTrue(classify(t).is_tcg, t)


class StoreTests(Tmp):
    def store(self, name):
        return REGISTRY[name](load_config(self.path), LOG)

    def test_sams_club_menu_links_are_not_products(self):
        html = ('<a href="/cp/membership-benefits/30001760">Benefits</a>'
                '<a href="/ip/Pokemon-Scarlet-Violet-Elite-Trainer-Box/13500999">x</a>')
        links = parse_listing(html, REGISTRY["samsclub"].product_re, "https://www.samsclub.com")
        self.assertEqual([u for u, _ in links], ["https://www.samsclub.com/ip/Pokemon-Scarlet-Violet-Elite-Trainer-Box/13500999"])
        self.assertFalse(REGISTRY["samsclub"].search_by_upc)

    def test_walgreens_searches_plain_and_cvs_walgreens_search_little(self):
        self.assertFalse(REGISTRY["walgreens"].search_in_browser)
        self.assertEqual((REGISTRY["walgreens"].search_budget, REGISTRY["cvs"].search_budget), (2, 2))

    def test_links_that_are_not_pokemon_send_the_search_to_the_browser(self):
        r = self.store("costco")
        r.search_in_browser = False
        r.browser = mock.Mock(usable=True)
        plain = FetchResult(200, '<a href="/kirkland-towels.product.111.html">Kirkland Towels</a>', "u", None)
        real = FetchResult(200, '<a href="/pokemon-tcg-elite-trainer-box.product.222.html">Pokemon TCG ETB</a>', "u", None)
        with mock.patch.object(r, "fetch_html", return_value=plain), mock.patch.object(r, "_via_browser", return_value=real) as vb:
            items, _ = r.load_listing("https://www.costco.com/CatalogSearch?keyword=pokemon")
        self.assertEqual(len(items), 1)
        self.assertIn("pok", vb.call_args.kwargs["wait_re"])                 # waits for a Pokemon result, not any link

    def test_a_page_that_says_no_matches_does_not_open_the_browser(self):
        r = self.store("walgreens")
        r.browser = mock.Mock(usable=True)
        page = FetchResult(200, "<h1>Looks like we don't have any matches for \"pokemon delta reign\"</h1>", "u", None)
        with mock.patch.object(r, "fetch_html", return_value=page), mock.patch.object(r, "_via_browser") as vb:
            items, _ = r.load_listing("https://www.walgreens.com/search/results.jsp?Ntt=pokemon")
        self.assertEqual(items, [])
        vb.assert_not_called()

    def test_kroger_searches_the_whole_chain_when_the_nearest_store_has_nothing(self):
        r = self.store("kroger")
        calls = []
        def api(path, **params):
            calls.append(dict(params))
            return {"data": []} if "filter.locationId" in params else {"data": [{"productId": "1", "description": "Pokemon TCG ETB"}]}
        with mock.patch.object(r, "locations", return_value=[{"id": "70100123"}]), mock.patch.object(r, "in_store_enabled", return_value=True), \
                mock.patch.object(r, "_api", side_effect=api), mock.patch.object(r, "_parse", return_value=(None, {})), \
                mock.patch.object(r, "_result", side_effect=lambda pid, info: StockResult("kroger", "Kroger", pid, "t", "u")):
            out = r.search("pokemon trading card game", 10)
        self.assertEqual(len(out), 1)
        self.assertNotIn("filter.locationId", calls[-1])


class DiscoveryTests(Tmp):
    def test_a_refused_search_does_not_pause_the_product_checks(self):
        mon = Monitor(self.path)
        try:
            r = mock.Mock(display="Walgreens", search_budget=2, search_has_stock=False, supports_search=False)
            r.name = "walgreens"
            r.signals.return_value = []
            with mock.patch.object(mon, "_discovery_on", return_value=True), \
                    mock.patch.object(mon, "_discover", side_effect=Blocked("Walgreens refused the request (Akamai)", 1800)), \
                    mock.patch.object(mon, "targets_for", return_value={}):
                mon.run_cycle(r)                                         # no Blocked raised
            self.assertGreater(mon._discover_rest["walgreens"], 0)
        finally:
            mon.close()

    def test_search_budget_rotates_a_few_queries(self):
        mon = Monitor(self.path)
        try:
            asked = []
            r = mock.Mock(display="CVS", search_budget=2, search_url="", search_by_upc=True)
            r.name = "cvs"
            r.search = lambda q, n: (asked.append(q), [])[1]
            r.seed_products.return_value = []
            for _ in range(3):
                mon._discover(r, {"queries": ["pokemon trading card game", "pokemon tcg"]})
            self.assertEqual(len(asked), 6)
            self.assertGreater(len(set(asked)), 2)                       # different searches each refresh
        finally:
            mon.close()


class ReviewTests(Tmp):
    def test_queue_signed_links_and_choices(self):
        q = ReviewQueue(self.dir)
        e = q.add("kohls", "Kohl's", "Juniors Pokemon Pikachu Graphic Tee", "https://www.kohls.com/p", "clothing", 19.99)
        self.assertIsNotNone(e)
        self.assertIsNone(q.add("macys", "Macy's", "Juniors Pokemon Pikachu Graphic Tee", "u", "clothing"))   # same product
        self.assertEqual(set(q.items[e["id"]]["stores"]), {"kohls", "macys"})
        link = q.link("http://192.168.1.5:8765/", e["id"], "mute")
        _, _, _, _, action, rid, sig = link.split("/")
        self.assertTrue(q.check(rid, action, sig))
        self.assertFalse(q.check(rid, "accept", sig))                     # a Mute link cannot accept
        q.decide(rid, "mute")
        self.assertEqual(ReviewQueue(self.dir).status_of("Juniors Pokemon Pikachu Graphic Tee"), "muted")   # saved

    def test_skipped_merch_goes_to_review_and_accepted_is_tracked(self):
        mon = Monitor(self.path)
        try:
            tee = StockResult("kohls", "Kohl's", "9", "Juniors Pokemon Eevee Tarot Card Graphic Tee", "https://www.kohls.com/p/9")
            mon.catalog.merge("kohls", [tee], mon.cfg.raw, mark_run=True)
            self.assertNotIn("kohls:9", mon.catalog.items)
            posted = []
            mon.notifier.review_url = "https://discord.com/api/webhooks/1/r"
            with mock.patch.object(mon.notifier, "review", side_effect=lambda out: posted.append(out)), \
                    mock.patch("restock.engine.threading.Thread", side_effect=lambda target, daemon: mock.Mock(start=target)):
                self.assertEqual(mon.flush_review(), 1)
            self.assertIn("/r/accept/", posted[0][0]["accept"])
            mon.review.decide(review_id(tee.title), "accept")
            mon.catalog.merge("kohls", [tee], mon.cfg.raw, mark_run=True)
            self.assertIn("kohls:9", mon.catalog.items)                    # you accepted it: tracked now
            self.assertEqual(mon.flush_review(), 0)
        finally:
            mon.close()

    def test_a_search_hit_that_is_merch_is_not_alerted(self):
        mon = Monitor(self.path)
        try:
            res = StockResult("macys", "Macy's", "5", "Pokemon Bulbasaur 3D Model Kit Kanto Starter Collection", "u",
                              price=29.99, online=True, source="search: pokemon")
            with mock.patch.object(mon.notifier, "restock") as sent:
                mon.handle(res, None, None)
            sent.assert_not_called()
            self.assertIn("To review", res.note)
            self.assertEqual(mon.review.counts()["pending"], 1)
        finally:
            mon.close()

    def test_review_webhook_has_accept_and_mute_links(self):
        n = DiscordNotifier({"webhooks": {"review": "https://discord.com/api/webhooks/1/r"}}, LOG, [])
        self.assertFalse(n.enabled)                                         # it is not a stock channel
        posted = []
        with mock.patch("restock.notify.requests.post", side_effect=lambda url, json=None, timeout=None:
                        (posted.append(json), mock.Mock(status_code=204))[1]):
            n.review([{"title": "Pokemon Tee", "reason": "clothing", "store": "Kohl's", "url": "https://x.test/p?utm_source=x",
                       "price": 20.0, "accept": "http://127.0.0.1:8765/r/accept/a/b", "mute": "http://127.0.0.1:8765/r/mute/a/c"}])
        desc = posted[0]["embeds"][0]["description"]
        self.assertIn("[Accept](http://127.0.0.1:8765/r/accept/a/b)", desc)
        self.assertNotIn("utm_source", desc)

    def test_the_panel_takes_a_signed_link_without_a_pin(self):
        from restock.panel import PanelServer
        with open(self.path, "a") as fh:
            fh.write("control_panel: {port: 8797}\n")
        mon = Monitor(self.path)
        panel = PanelServer(mon)
        try:
            self.assertTrue(panel.start())
            e = mon.review.add("kohls", "Kohl's", "Pokemon Pikachu Hoodie", "u", "clothing")
            good = mon.review.link(mon.panel_base, e["id"], "mute")
            with urllib.request.urlopen(good) as resp:
                self.assertIn("Muted", resp.read().decode())
            bad = good[:-3] + "000"
            with self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(bad)
            self.assertEqual(mon.review.status_of("Pokemon Pikachu Hoodie"), "muted")
        finally:
            panel.stop()
            mon.close()


if __name__ == "__main__":
    unittest.main()
