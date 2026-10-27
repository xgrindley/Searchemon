"""Ideas taken from other restock monitors (v4.1): three new trial methods, settling on the best method once
everything is scored, community restock tips, the newest set names in store searches, and reading a page's buy
button when it has no stock data. All offline."""
import logging
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from restock import community as cm  # noqa: E402
from restock.catalog import Catalog  # noqa: E402
from restock.config import load_config  # noqa: E402
from restock.engine import Monitor  # noqa: E402
from restock.models import StockResult  # noqa: E402
from restock.retailers import base  # noqa: E402
from restock.retailers.browser import FetchResult, _skip_heavy  # noqa: E402
from restock.retailers.pages import parse_product_page, stock_from_buttons  # noqa: E402
from restock.sessions import BlockTracker  # noqa: E402
from restock.trials import BY_KEY, INTRODUCED, OTHERS, TrialPlan  # noqa: E402
from restock.util import atomic_write_json  # noqa: E402

LOG = logging.getLogger("others")
CFG = ("discord: {webhooks: {default: 'https://discord.com/api/webhooks/1/a'}}\n"
       "settings: {windows_toast: false, confirm_restocks: false, alert_cooldown_minutes: 0}\n"
       "discovery: {enabled: false, places: false}\nbrowser: {enabled: false}\n")


class Tmp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        for h in list(logging.getLogger("restock").handlers):
            h.close()
            logging.getLogger("restock").removeHandler(h)
        shutil.rmtree(self.dir, ignore_errors=True)


# ---- trial methods ------------------------------------------------------------------------
class NewMethodTests(Tmp):
    def test_the_new_methods_are_grouped_and_described(self):
        for key in ("direct-fresh", "browser-light", "browser-warm"):
            arm = BY_KEY[key]
            self.assertEqual(arm.group, OTHERS)
            self.assertTrue(arm.idea and "streetmerchant" in arm.source)
            self.assertIn(key, INTRODUCED)

    def test_new_methods_are_switched_on_once_for_an_existing_install(self):
        atomic_write_json(os.path.join(self.dir, "trial-state.json"), {"active": ["direct-h2"]})
        raw = {"trials": {"enabled": True}}
        p = TrialPlan(raw, self.dir, LOG, BlockTracker(self.dir))
        for key in INTRODUCED:
            self.assertIn(key, p.active_keys())
        self.assertEqual(p.snapshot()["events"][-1]["kind"], "new")
        p.set_active("browser-light", False)                         # you turn one off...
        p2 = TrialPlan({"trials": {"enabled": True}}, self.dir, LOG, BlockTracker(self.dir))
        self.assertNotIn("browser-light", p2.active_keys())          # ...and it stays off after a restart
        self.assertIn("direct-fresh", p2.active_keys())

    def test_nothing_is_switched_on_while_trials_are_off(self):
        atomic_write_json(os.path.join(self.dir, "trial-state.json"), {"active": []})
        p = TrialPlan({"trials": {"enabled": False}}, self.dir, LOG, BlockTracker(self.dir))
        self.assertEqual(p.active_keys(), [])

    def test_once_everything_is_scored_the_best_gets_most_turns(self):
        raw = {"trials": {"enabled": True, "slice_checks": 20, "active": ["direct-h2", "direct-fresh"]}}
        p = TrialPlan(raw, self.dir, LOG, BlockTracker(self.dir))
        arms = [BY_KEY["direct"], BY_KEY["direct-h2"], BY_KEY["direct-fresh"]]
        for ok_list, key in (([True] * 12, "direct-fresh"), ([True] * 6 + [False] * 6, "direct"),
                             ([True] * 4 + [False] * 3, "direct-h2")):
            for ok in ok_list:
                p.note("cvs", BY_KEY[key], ok, "" if ok else "challenge")
        self.assertFalse(p._settled("cvs", arms))                   # direct-h2 has only 7 checks
        mid = p._turn_length("cvs", arms, BY_KEY["direct-fresh"])
        for ok in [False, True]:
            p.note("cvs", BY_KEY["direct-h2"], ok, "" if ok else "challenge")
        p.note("cvs", BY_KEY["direct-h2"], False, "challenge")
        self.assertTrue(p._settled("cvs", arms))
        best = p._turn_length("cvs", arms, BY_KEY["direct-fresh"])
        self.assertGreater(best, mid)
        self.assertGreaterEqual(best, 70)                             # about 4 normal turns
        self.assertLess(p._turn_length("cvs", arms, BY_KEY["direct-h2"]), 20)
        view = [b for b in p.snapshot()["balance"] if b["store"] == "cvs"][0]
        self.assertTrue(view["settled"])
        self.assertEqual(view["arms"][0]["key"], "direct-fresh")


class StampTests(unittest.TestCase):
    def test_the_stamp_is_added_and_dropped_again(self):
        url = "https://www.walgreens.com/store/c/pokemon/ID=1-product?skuId=9"
        stamped = base.add_stamp(url)
        self.assertRegex(stamped, r"skuId=9&_=\d{13}$")
        self.assertEqual(base.drop_stamp(stamped), url)
        self.assertRegex(base.add_stamp("https://x.test/p"), r"/p\?_=\d{13}$")


class FakeShop(base.Retailer):
    name = "fakeshop"
    display = "Fake Shop"


class ArmRunTests(Tmp):
    def shop(self):
        cfg = load_config(self._cfg())
        r = FakeShop(cfg, LOG)
        return r

    def _cfg(self):
        path = os.path.join(self.dir, "config.yaml")
        with open(path, "w") as fh:
            fh.write(CFG)
        return path

    def test_never_a_cached_copy_sends_the_stamp_and_hides_it(self):
        r = self.shop()
        seen = []
        resp = mock.Mock(status_code=200, text="<h1>ok</h1>", headers={}, url="https://x.test/p?a=1&_=1700000000000")
        r.session.get = lambda url, **kw: (seen.append(url), resp)[1]
        status, text, headers, final = r._fresh_get("https://x.test/p?a=1")
        self.assertIn("&_=", seen[0])
        self.assertEqual(final, "https://x.test/p?a=1")

    def test_text_only_asks_the_browser_for_no_pictures(self):
        r = self.shop()
        r.browser = mock.Mock(usable=True)
        r.browser.fetch.return_value = FetchResult(200, "<h1>x</h1>", "https://x.test/p", None)
        plan = mock.Mock()
        with mock.patch.object(base, "TRIALS", plan):
            res = r._browser_arm(BY_KEY["browser-light"], "https://x.test/p")
        self.assertIsNotNone(res)
        kw = r.browser.fetch.call_args.kwargs
        self.assertTrue(kw.get("light"))
        self.assertEqual(kw.get("label"), "browser-light")
        plan.note.assert_called_once_with("fakeshop", BY_KEY["browser-light"], True)

    def test_browse_the_front_page_first_then_not_again_for_a_while(self):
        r = self.shop()
        r.browser = mock.Mock(usable=True)
        r.browser.fetch.return_value = FetchResult(200, "<h1>x</h1>", "u", None)
        with mock.patch.object(base, "TRIALS", mock.Mock()), mock.patch.object(base.time, "sleep"):
            r._browser_arm(BY_KEY["browser-warm"], "https://x.test/p/1")
            r._browser_arm(BY_KEY["browser-warm"], "https://x.test/p/2")
        urls = [c.args[0] for c in r.browser.fetch.call_args_list]
        self.assertEqual(urls, ["https://x.test/", "https://x.test/p/1", "https://x.test/p/2"])

    def test_heavy_files_are_skipped(self):
        for kind, aborted in (("image", True), ("font", True), ("media", True), ("document", False), ("script", False)):
            route = mock.Mock()
            route.request.resource_type = kind
            _skip_heavy(route)
            self.assertEqual(route.abort.called, aborted, kind)
            self.assertEqual(route.continue_.called, not aborted, kind)


# ---- community tips ------------------------------------------------------------------------------
def post(pid, title, url="", age=60, **extra):
    return {"data": {"id": pid, "title": title, "url": url, "created_utc": time.time() - age,
                     "permalink": f"/r/PokemonTCGDeals/comments/{pid}/x/", **extra}}


class CommunityParseTests(unittest.TestCase):
    def test_store_names_and_product_words(self):
        self.assertEqual(cm.stores_named("[Target] and Sam's Club restock"), ["target", "samsclub"])
        self.assertEqual(cm.stores_named("Pokemon Center ETB live"), ["pokemoncenter"])
        self.assertEqual(cm.stores_named("targeted ads"), [])
        self.assertEqual(cm.product_words("[Target] Phantasmal Flames ETB $49.99"), {"phantasmal", "flames", "elite", "trainer"})
        self.assertEqual(cm.clean_title("[Walmart] Pokemon TCG Mega Evolution Booster Bundle - $26.94 (in stock)"),
                         "Pokemon TCG Mega Evolution Booster Bundle")

    def test_posts_become_tips(self):
        seen = set()
        tips = cm.parse_posts([
            post("a1", "[Target] Phantasmal Flames ETB - $49.99", "https://www.target.com/p/x/-/A-94300001?afid=reddit&cpng=x"),
            post("a2", "Pikachu plush back at Pokemon Center"),                       # not cards
            post("a3", "[Walmart] Mega Evolution Booster Bundle", age=5 * 3600),      # too old to act on
            post("a4", "[GameStop] Surging Sparks booster box", "https://www.reddit.com/gallery/x"),
        ], seen, time.time())
        self.assertEqual([t["id"] for t in tips], ["a1", "a4"])
        self.assertEqual(tips[0]["stores"], ["target"])
        self.assertEqual(tips[0]["link"], "https://www.target.com/p/x/-/A-94300001")   # tracking stripped
        self.assertTrue(tips[0]["product"].startswith("Pokemon TCG "))
        self.assertEqual(tips[1]["link"], "")                                            # a Reddit page is not a store link
        self.assertEqual(seen, {"a1", "a2", "a3", "a4"})
        self.assertEqual(cm.parse_posts([post("a1", "[Target] again")], seen, time.time()), [])

    def test_set_list(self):
        now = time.time()
        day = lambda n: time.strftime("%Y-%m-%dT00:00:00", time.localtime(now - n * 86400))
        data = {"results": [
            {"name": "ME02: Phantasmal Flames", "publishedOn": day(20)},
            {"name": "ME: Mega Evolution", "publishedOn": day(80)},
            {"name": "ME: Mega Evolution Promos", "publishedOn": day(80)},
            {"name": "Prize Pack Series Seven", "publishedOn": day(10)},
            {"name": "SV: Prismatic Evolutions", "publishedOn": day(300)},
            {"name": "ME03: Ascended Heroes", "publishedOn": day(-30)},          # announced
        ]}
        self.assertEqual(cm.parse_sets(data, now), ["Ascended Heroes", "Phantasmal Flames", "Mega Evolution"])
        self.assertEqual(cm.parse_sets([], now), [])
        self.assertEqual(cm.parse_sets({"results": [{"name": "X", "publishedOn": "garbage"}]}, now), [])


class CommunityFeedTests(Tmp):
    def feed(self, c, children=None, status=200):
        resp = mock.Mock(status_code=status)
        resp.json.return_value = {"data": {"children": children or []}}
        c.session.get = mock.Mock(return_value=resp)

    def test_first_read_only_learns_then_new_posts_are_tips(self):
        c = cm.Community(self.dir, LOG, "4.1")
        self.assertIn("searchemon", c.session.headers["User-Agent"])
        self.feed(c, [post("old", "[Target] Phantasmal Flames ETB")])
        self.assertEqual(c.poll_feed(), [])
        self.assertFalse(c.feed_due())                               # five minutes until the next read
        c.feed["next"] = 0
        self.feed(c, [post("old", "[Target] Phantasmal Flames ETB"), post("new", "[Costco] Mega Evolution ETB 2 pack")])
        tips = c.poll_feed()
        self.assertEqual([t["id"] for t in tips], ["new"])
        again = cm.Community(self.dir, LOG, "4.1")                   # remembered across restarts
        self.assertIn("new", again.seen)
        self.assertEqual(again.view()["tips"][0]["id"], "new")

    def test_a_refusal_waits_longer_each_time(self):
        c = cm.Community(self.dir, LOG, "4.1")
        self.feed(c, status=429)
        now = time.time()
        c.poll_feed(now)
        first = c.feed["next"] - now
        c.poll_feed(c.feed["next"] + 1)
        self.assertEqual(round(first), cm.REST_START_S)
        self.assertEqual(round(c.feed["rest"]), 2 * cm.REST_START_S)
        self.assertIn("429", c.view()["feed_problem"])

    def test_set_names_once_a_day(self):
        c = cm.Community(self.dir, LOG, "4.1")
        resp = mock.Mock(status_code=200)
        resp.json.return_value = {"results": [{"name": "ME02: Phantasmal Flames",
                                               "publishedOn": time.strftime("%Y-%m-%d", time.localtime())}]}
        c.session.get = mock.Mock(return_value=resp)
        self.assertTrue(c.refresh_sets())
        self.assertFalse(c.refresh_sets())                            # not again the same day
        self.assertEqual(c.session.get.call_count, 1)
        self.assertEqual(c.set_names(), ["Phantasmal Flames"])
        self.assertIn("Searchemon", c.session.get.call_args.kwargs["headers"]["User-Agent"])


class TipUseTests(Tmp):
    def monitor(self):
        path = os.path.join(self.dir, "config.yaml")
        with open(path, "w") as fh:
            fh.write(CFG)
        return Monitor(path)

    def test_matching_listings_are_checked_now_and_a_store_link_is_added(self):
        mon = self.monitor()
        try:
            mon.catalog.merge("target", [
                StockResult("target", "Target", "111", "Pokemon TCG Mega Evolution Phantasmal Flames Elite Trainer Box", "u1"),
                StockResult("target", "Target", "222", "Pokemon TCG Mega Evolution Booster Bundle", "u2"),
                StockResult("target", "Target", "333", "Pokemon TCG Surging Sparks Elite Trainer Box", "u3")], mon.cfg.raw, mark_run=True)
            for k in ("target:111", "target:222", "target:333"):
                mon.catalog.items[k]["next_due"] = time.time() + 9999
            tip = cm.parse_posts([post("t1", "[Target] Phantasmal Flames ETB - $49.99",
                                       "https://www.target.com/p/pf-etb/-/A-94300009?afid=x")], set(), time.time())[0]
            mon.use_tip(tip)
            items = mon.catalog.items
            self.assertEqual(items["target:111"]["next_due"], 0)                       # the matching listing
            self.assertGreater(items["target:111"]["boost_until"], time.time() + 3000)
            self.assertGreater(items["target:333"]["next_due"], 0)                     # another set's ETB: left alone
            self.assertGreater(items["target:222"]["next_due"], 0)                     # same set word only once
            self.assertIn("target:94300009", items)                                    # the linked product joined
            self.assertEqual(items["target:94300009"]["found_via"], "community tip")
            self.assertEqual(items["target:94300009"]["url"], "https://www.target.com/p/pf-etb/-/A-94300009")
            used = mon.community.view()
            self.assertEqual(used["tips"], [])          # use_tip alone does not store the tip; poll_feed does
        finally:
            mon.close()

    def test_stores_you_do_not_monitor_and_switches(self):
        mon = self.monitor()
        try:
            mon.retailers.pop("costco", None)
            tip = cm.parse_posts([post("t2", "[Costco] Phantasmal Flames ETB 2 pack")], set(), time.time())[0]
            mon.use_tip(tip)                                                          # nothing to do, no error
            mon.cfg.raw["community"] = {"reddit": False, "new_sets": False}
            mon.community.session.get = mock.Mock(side_effect=AssertionError("no requests when switched off"))
            self.assertEqual(mon.community_tick(), [])
        finally:
            mon.close()

    def test_newest_set_joins_the_store_searches(self):
        mon = self.monitor()
        try:
            mon.community.sets = {"t": time.time(), "names": ["Phantasmal Flames", "Mega Evolution"]}
            asked = []
            r = mock.Mock(display="Fake")
            r.search = lambda q, n: (asked.append(q), [])[1]
            r.name = "fake"
            try:
                mon._discover(r, {"queries": ["pokemon tcg"]})
            except Exception:
                pass
            self.assertIn("pokemon phantasmal flames", asked)
        finally:
            mon.close()


class CatalogTipTests(Tmp):
    def test_wake_matching_needs_a_real_match(self):
        cat = Catalog(self.dir)
        raw = {}
        cat.merge("walmart", [StockResult("walmart", "Walmart", "1", "Pokemon TCG Phantasmal Flames Booster Bundle", "u")], raw, mark_run=True)
        self.assertEqual(cat.wake_matching(["walmart"], "Pokemon TCG Phantasmal Flames BB"), ["walmart:1"])
        self.assertEqual(cat.wake_matching(["walmart"], "Pokemon TCG restock"), [])
        self.assertEqual(cat.wake_matching(["walmart"], "Pokemon TCG Surging Sparks Booster Bundle"), [])
        self.assertEqual(cat.wake_matching(["target"], "Pokemon TCG Phantasmal Flames BB"), [])


# ---- buy buttons -----------------------------------------------------------------------------------
class ButtonTests(unittest.TestCase):
    def test_reads_the_buy_area_under_the_heading_only(self):
        page = "<header>Sold out deals</header><h1>Pokemon ETB</h1><b>$49.99</b><button>Add to Cart</button>"
        self.assertEqual(stock_from_buttons(page), "in")
        self.assertEqual(stock_from_buttons("<h1>ETB</h1><button disabled>Sold Out</button>" + "x" * 13000 +
                                            "<button>Add to cart</button>"), "out")
        self.assertEqual(stock_from_buttons("<h1>ETB</h1><button>Notify me</button><p>Add to cart</p>"), "out")
        self.assertIsNone(stock_from_buttons("<div>Add to cart</div>"))                 # no product heading
        self.assertEqual(stock_from_buttons('<h1>ETB</h1><script>"sold out"</script><button>Add to cart</button>'), "in")

    def test_structured_data_and_your_own_words_still_win(self):
        ld = ('<script type="application/ld+json">{"@type":"Product","name":"ETB","offers":{"@type":"Offer",'
              '"availability":"https://schema.org/OutOfStock"}}</script><h1>ETB</h1><button>Add to cart</button>')
        info = parse_product_page(ld)
        self.assertEqual(info["status"], "out")
        self.assertFalse(info.get("from_buttons"))
        mine = parse_product_page("<h1>ETB</h1><button>Add to cart</button>", {"out_of_stock_text": ["add to cart"]})
        self.assertEqual(mine["status"], "out")
        auto = parse_product_page("<h1>ETB</h1><button>Add to cart</button>")
        self.assertEqual((auto["status"], auto["from_buttons"]), ("in", True))


if __name__ == "__main__":
    unittest.main()
