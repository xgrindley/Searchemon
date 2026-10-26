"""Stores without a product API find Pokemon products by searching their own site and by looking up what other
stores list, so nobody has to paste links."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from restock.catalog import Catalog  # noqa: E402
from restock.models import StockResult  # noqa: E402
from restock.retailers.base import FetchResult  # noqa: E402
from restock.retailers.pages import CVS, GameStop, Costco, parse_listing, slug_title  # noqa: E402
from restock.tcg import classify  # noqa: E402

CVS_PAGE = ('<a href="/shop/pok-mon-tcg-mega-evolution-foil-booster-pack-assorted-prodid-804830"><img></a>'
            '<a href="/shop/pokemon-tcg-elite-trainer-box-prodid-123456">Pokémon TCG Elite Trainer Box</a>'
            '<a href="/shop/some-shampoo-prodid-99999">Shampoo</a>'
            '<script>{"u":"\\/shop\\/pok-mon-tcg-30th-anniversary-mini-tin-assorted-prodid-777777"}</script>')


class ListingTests(unittest.TestCase):
    def test_links_titles_and_script_data_are_all_found(self):
        got = dict(parse_listing(CVS_PAGE, CVS.product_re, "https://www.cvs.com"))
        self.assertEqual(len(got), 4)
        self.assertIn("https://www.cvs.com/shop/pok-mon-tcg-mega-evolution-foil-booster-pack-assorted-prodid-804830", got)
        tcg = [t for t in got.values() if classify(t).is_tcg]
        self.assertEqual(len(tcg), 3)

    def test_slug_title(self):
        self.assertEqual(slug_title("/toys/products/pokemon-trading-card-game-elite-trainer-box/449048.html"),
                         "Pokemon Trading Card Game Elite Trainer Box")

    def test_each_store_recognizes_its_own_product_links(self):
        self.assertTrue(GameStop.product_re.search("/toys-games/trading-cards/products/x-y/449048.html"))
        self.assertTrue(Costco.product_re.search("/pokemon-box.product.100123456.html"))
        self.assertFalse(Costco.product_re.search("/about.html"))


class SearchTests(unittest.TestCase):
    def shop(self, html):
        s = CVS.__new__(CVS)
        s.fetch_html = lambda url: (setattr(s, "seen", url), FetchResult(200, html, url, {}))[1]
        s.dump = lambda *a, **k: None
        s.pause = lambda *a, **k: None
        s.link_delay = lambda: 0
        import logging
        s.log = logging.getLogger("t")
        return s

    def test_search_returns_unchecked_listings(self):
        s = self.shop(CVS_PAGE)
        res = s.search("820650850011", 10)
        self.assertIn("searchTerm=820650850011", s.seen)
        self.assertEqual(len(res), 4)
        self.assertTrue(all(r.online_status == "UNCHECKED" and r.retailer == "cvs" for r in res))


class CrossQueryTests(unittest.TestCase):
    def test_products_found_elsewhere_become_lookups_and_rotate(self):
        with tempfile.TemporaryDirectory() as d:
            cat = Catalog(d)
            raw = {"settings": {}}
            def res(r, pid, title, upc):
                return StockResult(r, r, pid, title, "https://x/" + pid, upc=upc, online_status="In stock")
            cat.merge("target", [res("target", "1", "Pokemon TCG Mega Evolution Elite Trainer Box", "820650850011"),
                                 res("target", "2", "Pokemon TCG Scarlet Violet Booster Bundle Box", ""),
                                 res("target", "3", "Pokemon TCG Mini Tin Assorted", "820650850033")], raw, True)
            cat.merge("cvs", [res("cvs", "a", "Pokemon TCG Mini Tin Assorted", "820650850033")], raw, True)
            first = cat.cross_queries("cvs", 1)
            second = cat.cross_queries("cvs", 1)
            self.assertEqual(len(first), 1)
            self.assertNotEqual(first, second)
            both = set(first + second)
            self.assertIn("820650850011", both)                          # UPC used when known
            self.assertNotIn("820650850033", both)                       # already listed at CVS
            self.assertTrue(any(q.startswith("Pokemon TCG Scarlet") for q in both))   # title when no UPC


if __name__ == "__main__":
    unittest.main()


class BoostTests(unittest.TestCase):
    def test_restock_boosts_same_product_at_other_stores(self):
        import time
        with tempfile.TemporaryDirectory() as d:
            cat = Catalog(d)
            raw = {"settings": {}}
            mk = lambda r, pid, upc: StockResult(r, r, pid, "Pokemon TCG Elite Trainer Box", "u", upc=upc, online_status="In stock")
            cat.merge("target", [mk("target", "1", "820650850011")], raw, True)
            cat.merge("cvs", [mk("cvs", "2", "820650850011")], raw, True)
            cat.merge("cvs", [mk("cvs", "3", "820650850099")], raw, True)
            hit = mk("target", "1", "820650850011")
            hit.online = True
            self.assertEqual(cat.boost_siblings(hit), 1)
            hot = cat.rotation("cvs", 1, {})
            self.assertEqual([v["id"] for v in hot], ["2"])           # the boosted sibling, not the unrelated item
