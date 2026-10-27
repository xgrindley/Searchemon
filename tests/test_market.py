"""Fair market value (eBay + TCGplayer) and eBay listing risk. Offline."""
import logging
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from restock import market as mk  # noqa: E402
from restock.notify import DiscordNotifier  # noqa: E402

LOG = logging.getLogger("m")
GREN = "Pokemon TCG Mega Greninja ex Premium Collection"


def listing(total, ship=5.0, fb=500, pos=99.9, title=GREN + " Sealed", created=None, country="US", i=[0]):
    i[0] += 1
    return {"id": str(i[0]), "title": title, "url": f"https://www.ebay.com/itm/{i[0]}", "price": total - (ship or 0),
            "shipping": ship, "total": total, "seller": "s", "feedback": fb, "positive": pos, "country": country,
            "created": created, "best_offer": False, "image": "", "condition": "New"}


class MathTests(unittest.TestCase):
    def test_outliers_are_left_out(self):
        mid, kept = mk.fair_middle([44, 46, 47, 48, 50, 52, 9.99, 199])
        self.assertEqual(mid, 47.5)
        self.assertNotIn(9.99, kept)
        self.assertNotIn(199, kept)
        self.assertEqual(mk.fair_middle([]), (None, []))

    def test_egregious_shipping(self):
        self.assertTrue(mk.egregious_shipping(10, 25))       # $10 + $25 shipping is not a $10 listing
        self.assertFalse(mk.egregious_shipping(40, 10.15))
        self.assertTrue(mk.egregious_shipping(80, 45))

    def test_names_must_agree_on_set_and_type(self):
        self.assertGreater(mk.match_score(GREN, "Pokemon Mega Greninja EX Premium Collection Sealed Box"), 0.5)
        self.assertEqual(mk.match_score("Pokemon TCG Phantasmal Flames Elite Trainer Box", "Phantasmal Flames Booster Bundle"), 0)
        self.assertEqual(mk.match_score("Pokemon TCG Phantasmal Flames ETB", "Surging Sparks Elite Trainer Box"), 0)


class RiskTests(unittest.TestCase):
    def test_the_listing_from_your_screenshot_is_high_risk(self):
        x = listing(39.0, ship=0.0, fb=39, pos=95.2, created=time.time() - 86400)
        score, level, why = mk.risk(x, 50.0)
        self.assertEqual(level, "high")
        self.assertTrue(any("39 feedback" in w for w in why))
        self.assertTrue(any("95.2% positive" in w for w in why))
        self.assertTrue(any("last 3 days" in w for w in why))

    def test_an_established_seller_at_a_fair_price_is_low_risk(self):
        self.assertEqual(mk.risk(listing(48.0, fb=4200, pos=99.9), 50.0)[1], "low")

    def test_too_good_to_be_true(self):
        score, level, why = mk.risk(listing(19.0, fb=300, pos=99.9), 50.0)
        self.assertIn("too good to be true", " ".join(why))
        self.assertNotEqual(level, "low")


class ReadingTests(unittest.TestCase):
    def test_api_item(self):
        x = mk.from_api({"itemId": "v1|198748298929|0", "title": GREN, "price": {"value": "39.00", "currency": "USD"},
                         "shippingOptions": [{"shippingCostType": "FIXED", "shippingCost": {"value": "5.96", "currency": "USD"}}],
                         "seller": {"username": "tkeys916", "feedbackPercentage": "95.2", "feedbackScore": 39},
                         "itemLocation": {"country": "US"}, "itemCreationDate": "2026-10-25T10:00:00.000Z",
                         "buyingOptions": ["FIXED_PRICE", "BEST_OFFER"],
                         "itemWebUrl": "https://www.ebay.com/itm/198748298929?chn=ps&mkevt=1&mkcid=2&mkrid=711-117182"})
        self.assertEqual((x["total"], x["feedback"], x["positive"], x["best_offer"]), (44.96, 39, 95.2, True))
        self.assertEqual(x["url"], "https://www.ebay.com/itm/198748298929")       # tracking codes removed
        self.assertIsNotNone(x["created"])

    def test_public_search_page(self):
        page = ('<ul><li class="s-card" data-listingid="1"><a href="https://www.ebay.com/itm/111?hash=x">'
                '<span>Pokémon TCG First Partner Illustration Collection Series 2</span></a><span>Brand New</span>'
                '<span>$23.00</span><span>or Best Offer</span><span>+$10.15 delivery</span><span>Located in United States</span>'
                '<span>cardshop 99.6% positive (1.2K)</span></li>'
                '<li class="s-card" data-listingid="2"><a href="https://www.ebay.com/itm/222">'
                '<span>Pokemon TCG First Partner Illustration Collection Box Series 2 Sealed New</span></a>'
                '<span>$28.00</span><span>Free delivery</span></li></ul>')
        rows = mk.from_html(page)
        self.assertEqual(len(rows), 2)
        self.assertEqual((rows[0]["price"], rows[0]["shipping"], rows[0]["total"]), (23.0, 10.15, 33.15))
        self.assertEqual((rows[0]["seller"], rows[0]["positive"], rows[0]["feedback"], rows[0]["country"]), ("cardshop", 99.6, 1200, "US"))
        self.assertEqual(rows[1]["shipping"], 0.0)


class MarketTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_fair_value_uses_ebay_and_tcgplayer_and_finds_a_safe_deal(self):
        m = mk.Market({"ebay": {"enabled": True, "deal_pct": 90, "alert_max_risk": "low"}}, self.dir, LOG)
        m.tcg = [{"name": "Mega Greninja ex Premium Collection", "set": "ME", "market": 52.0, "low": 45.0, "url": "u"}]
        rows = [listing(t) for t in (49, 50, 51, 52, 53, 54)] + [
            listing(39.0, ship=0.0, fb=39, pos=95.2, created=time.time()),             # cheap, risky seller
            listing(42.0, fb=3000, pos=99.8),                                         # a real deal
            listing(15.0, ship=40.0),                                                  # huge shipping
            listing(30.0, title="Mega Greninja ex Premium Collection EMPTY BOX only"),  # not the product
        ]
        with mock.patch.object(m, "search_ebay", return_value=rows), mock.patch.object(mk.time, "sleep"):
            deals = m.check([{"title": GREN, "msrp": 39.99}])
        v = m.view()["products"][0]
        self.assertEqual(v["ebay"], 51.0)
        self.assertEqual(v["tcg"], 52.0)
        self.assertEqual(v["fair"], 51.5)
        self.assertEqual([d["total"] for d in deals], [42.0])                       # the risky $39 one is not a deal
        self.assertNotIn("EMPTY", " ".join(x["title"] for x in v["listings"]))
        with mock.patch.object(m, "search_ebay", return_value=rows), mock.patch.object(mk.time, "sleep"):
            self.assertEqual(m.check([{"title": GREN, "msrp": 39.99}]), [])         # not alerted twice

    def test_tcgplayer_prices_once_a_day_sealed_only(self):
        m = mk.Market({}, self.dir, LOG)
        now = time.time()
        day = time.strftime("%Y-%m-%dT00:00:00", time.localtime(now - 30 * 86400))
        answers = {
            mk.TCG_GROUPS: {"results": [{"groupId": 7, "name": "ME02: Phantasmal Flames", "publishedOn": day}]},
            mk.TCG_PRODUCTS.format(gid=7): {"results": [
                {"productId": 1, "name": "Phantasmal Flames Elite Trainer Box", "url": "https://www.tcgplayer.com/product/1", "extendedData": []},
                {"productId": 2, "name": "Charizard ex", "extendedData": [{"name": "Number", "value": "6"}]}]},
            mk.TCG_PRICES.format(gid=7): {"results": [{"productId": 1, "marketPrice": 61.5}, {"productId": 2, "marketPrice": 300}]},
        }
        m.http.get = lambda url, timeout=None: mock.Mock(json=lambda: answers[url])
        with mock.patch.object(mk.time, "sleep"):
            self.assertTrue(m.refresh_tcg(now))
            self.assertFalse(m.refresh_tcg(now + 60))
        self.assertEqual([r["name"] for r in m.tcg], ["Phantasmal Flames Elite Trainer Box"])
        self.assertEqual(m.tcg_value("Pokemon TCG: Mega Evolution Phantasmal Flames ETB")["market"], 61.5)

    def test_deal_message(self):
        n = DiscordNotifier({"webhooks": {"ebay": "https://discord.com/api/webhooks/1/e"}}, LOG, [])
        self.assertFalse(n.enabled)
        posted = []
        with mock.patch("restock.notify.requests.post", side_effect=lambda url, json=None, timeout=None:
                        (posted.append(json), mock.Mock(status_code=204))[1]):
            d = listing(42.0, fb=3000, pos=99.8)
            d.update({"level": "low", "risk": 0, "why": [], "pct_fair": 82, "fair": 51.5, "product": GREN})
            n.ebay([d])
        e = posted[0]["embeds"][0]
        self.assertIn("Fair value", [f["name"] for f in e["fields"]])
        self.assertIn("Risk: low", " ".join(f["name"] for f in e["fields"]))


class KeyAndBrowserTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_key_test_reports_both_outcomes(self):
        m = mk.Market({"ebay": {"app_id": "a", "cert_id": ""}}, self.dir, LOG)
        self.assertFalse(m.test_key()[0])
        m.attach({"ebay": {"app_id": "a", "cert_id": "b"}})
        m.http.post = lambda *a, **k: mock.Mock(json=lambda: {"access_token": "t", "expires_in": 7200})
        m.http.get = lambda *a, **k: mock.Mock(status_code=200)
        self.assertTrue(m.test_key()[0])
        m.http.post = lambda *a, **k: mock.Mock(json=lambda: {"error_description": "invalid_client"})
        m.attach({"ebay": {"app_id": "a", "cert_id": "c"}})         # new key clears the saved token
        ok, msg = m.test_key()
        self.assertFalse(ok)
        self.assertIn("Production", msg)

    def test_blocked_page_falls_back_to_the_browser(self):
        m = mk.Market({"ebay": {}}, self.dir, LOG)
        m.http.get = lambda *a, **k: mock.Mock(status_code=200, text="<html>Pardon Our Interruption</html>")
        m.browser = mock.Mock()
        m.browser.fetch.return_value = mock.Mock(status=200, text='<li class="s-card">ok</li>')
        self.assertIn("s-card", m._page("https://www.ebay.com/sch/i.html?_nkw=x"))
        m.browser.fetch.assert_called_once()
        m.raw = {"ebay": {"fetch_mode": "direct"}}
        with self.assertRaises(RuntimeError):
            m._page("https://www.ebay.com/sch/i.html?_nkw=x")


if __name__ == "__main__":
    unittest.main()
