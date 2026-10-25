"""Tests for webhook routing, the block tracker, profile rotation and Target search fallbacks."""
import logging
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from restock.geo import Area  # noqa: E402
from restock.models import StockResult, StoreStock  # noqa: E402
from restock.notify import DiscordNotifier  # noqa: E402
from restock.retailers.blocks import BlockInfo, classify  # noqa: E402
from restock.retailers.browser import BrowserPool, FetchResult  # noqa: E402
from restock.sessions import BlockTracker  # noqa: E402

LOG = logging.getLogger("t4")
H = "https://discord.com/api/webhooks/"


def result(online=False, stores=()):
    return StockResult(retailer="target", retailer_name="Target", product_id="1", title="Pokemon ETB",
                       url="https://x/1", online=online, stores=list(stores))


def store(sid, area):
    return StoreStock(store_id=sid, name=f"S{sid}", qty=3, area=area)


class RoutingTests(unittest.TestCase):
    def make(self, hooks, areas=()):
        return DiscordNotifier({"webhooks": hooks}, LOG, areas)

    def test_online_and_store_channels(self):
        n = self.make({"default": H + "d", "online": H + "o", "in_store": H + "s"})
        self.assertEqual([u for u, _ in n.routes(result(online=True))], [H + "o"])
        self.assertEqual([u for u, _ in n.routes(result(stores=[store("1", "Home")]))], [H + "s"])
        both = [u for u, _ in n.routes(result(online=True, stores=[store("1", "Home")]))]
        self.assertEqual(both, [H + "o", H + "s"])

    def test_default_fallback(self):
        n = self.make({"default": H + "d"})
        self.assertEqual([u for u, _ in n.routes(result(online=True))], [H + "d"])

    def test_area_hook_gets_only_its_stores(self):
        areas = [Area("Reno", "89502", 10, webhook=H + "reno"), Area("Tulsa", "74101", 10)]
        n = self.make({"default": H + "d", "in_store": H + "s"}, areas)
        res = result(stores=[store("1", "Reno"), store("2", "Tulsa")])
        routes = dict(n.routes(res))
        self.assertEqual(set(routes), {H + "s", H + "reno"})
        self.assertEqual([s.store_id for s in routes[H + "reno"].stores], ["1"])
        self.assertEqual(len(routes[H + "s"].stores), 2)

    def test_retailer_key_wins_and_no_duplicate_channel(self):
        n = self.make({"default": H + "d", "online": H + "o", "target": H + "t"})
        self.assertEqual([u for u, _ in n.routes(result(online=True))], [H + "t"])
        n = self.make({"online": H + "same", "in_store": H + "same"})
        self.assertEqual(len(n.routes(result(online=True, stores=[store("1", "A")]))), 1)

    def test_area_hook_alone_is_enabled(self):
        n = self.make({}, [Area("Reno", "89502", 10, webhook=H + "reno")])
        self.assertTrue(n.enabled)


class DeliveryTests(unittest.TestCase):
    def test_big_embed_stays_under_discord_limit(self):
        stores = [StoreStock(store_id=str(i), name=f"Target Store Number {i} Long Name", qty=4, distance=i * 1.1,
                             address="1234 Some Very Long Street Name Avenue, City", pickup=True, area=f"Area{i % 4}")
                  for i in range(60)]
        res = result(online=True, stores=stores)
        n = DiscordNotifier({"webhooks": {"default": H + "d"}}, LOG)
        sent = []
        n._post = lambda url, payload: sent.append(payload) or True
        self.assertTrue(n.restock(res, "online restock, in stock at 60 new store(s)", tuple(s.store_id for s in stores)))
        e = sent[0]["embeds"][0]
        total = len(e["title"]) + len(e.get("description", "")) + len(e["footer"]["text"]) + sum(
            len(f["name"]) + len(f["value"]) for f in e["fields"])
        self.assertLess(total, 6000)
        self.assertLessEqual(len(e["fields"]), 25)
        self.assertTrue(all(f["value"] for f in e["fields"]))

    def test_failed_send_is_retried_then_given_up(self):
        from restock.state import Change, StateStore
        with tempfile.TemporaryDirectory() as d:
            st = StateStore(d)
            res = result(online=True)
            ch = st.evaluate(res, 0, True)
            self.assertTrue(ch.alert)
            self.assertTrue(st.undo_alert(res, ch))
            ch2 = st.evaluate(res, 0, False)   # next check: still counts as new stock
            self.assertTrue(ch2.alert)
            for _ in range(10):
                if not st.undo_alert(res, ch2):
                    break
            else:
                self.fail("retries never stop")

    def test_stores_fall_back_to_default_when_no_instore_channel(self):
        n = DiscordNotifier({"webhooks": {"default": H + "d", "online": H + "o"}}, LOG)
        urls = [u for u, _ in n.routes(result(online=True, stores=[store("1", "A")]))]
        self.assertEqual(urls, [H + "o", H + "d"])


class BlockTextTests(unittest.TestCase):
    def test_dicks_twelve_hour_page(self):
        info = classify(200, "<html>This site is currently unavailable. Please try again after 12 hours.</html>")
        self.assertEqual(info.kind, "rate_limit")
        self.assertEqual(info.retry_after, 12 * 3600)

    def test_cvs_access_denied(self):
        info = classify(403, "<h1>Access Denied</h1> Reference #18.abc https://errors.edgesuite.net/18.abc")
        self.assertEqual((info.vendor, info.kind), ("Akamai", "denied"))


class TrackerTests(unittest.TestCase):
    def test_streaks(self):
        with tempfile.TemporaryDirectory() as d:
            t = BlockTracker(d)
            for _ in range(5):
                t.record("edge", "cvs.com", True)
            t.record("edge", "cvs.com", False, "denied")
            for _ in range(3):
                t.record("edge", "cvs.com", True)
            t.record("direct", "cvs.com", False, "denied")
            rows = {r["method"]: r for r in t.rows()}
            self.assertEqual(rows["edge"]["checks"], 9)
            self.assertEqual(rows["edge"]["avg_before_block"], 5)
            self.assertEqual(rows["edge"]["streak"], 3)
            self.assertEqual(rows["direct"]["avg_before_block"], 0)
            t.save()
            again = BlockTracker(d)
            self.assertEqual(len(again.rows()), 2)
            self.assertIn("edge", again.report())


class FakeWorker:
    def __init__(self, name, blocked=False, retry=0):
        self.name, self.blocked, self.retry = name, blocked, retry
        self.usable, self.calls, self.thread, self.failed = True, 0, None, ""
        self.on_reopen = None

    def waiting_domains(self):
        return []

    def fetch(self, url, timeout=120, ask=True):
        self.calls += 1
        block = BlockInfo("Akamai", "denied", False, retry_after=self.retry) if self.blocked else None
        return FetchResult(403 if block else 200, "x", url, block, via=self.name, profile=self.name)

    def stop(self):
        pass


class PoolTests(unittest.TestCase):
    def pool(self, *workers):
        with tempfile.TemporaryDirectory() as d:
            p = BrowserPool({"browser": {"profiles": [{"name": "a"}]}}, d, LOG, tracker=BlockTracker(d))
        p.workers = list(workers)
        return p

    def test_rotates_round_robin(self):
        a, b = FakeWorker("a"), FakeWorker("b")
        p = self.pool(a, b)
        for _ in range(4):
            p.fetch("https://www.cvs.com/x")
        self.assertEqual((a.calls, b.calls), (2, 2))

    def test_blocked_profile_rests_and_other_carries_on(self):
        a, b = FakeWorker("a", blocked=True, retry=3600), FakeWorker("b")
        p = self.pool(a, b)
        res = p.fetch("https://www.cvs.com/x")
        self.assertIsNone(res.block)
        self.assertEqual(res.profile, "b")
        p.fetch("https://www.cvs.com/x")
        p.fetch("https://www.cvs.com/x")
        self.assertEqual(a.calls, 1)  # resting, not asked again
        self.assertTrue(p.resting())

    def test_all_blocked_reports_block(self):
        p = self.pool(FakeWorker("a", True), FakeWorker("b", True))
        self.assertIsNotNone(p.fetch("https://www.cvs.com/x").block)
        res = p.fetch("https://www.cvs.com/x")  # both resting
        self.assertEqual(res.via, "pool")
        self.assertGreaterEqual(res.block.retry_after, 60)


class TargetSearchTests(unittest.TestCase):
    def make(self):
        from restock.config import load_config
        d = tempfile.mkdtemp()
        path = os.path.join(d, "config.yaml")
        open(path, "w").write("discord: {webhooks: {default: ''}}\nareas: []\n")
        from restock.retailers.target import Target
        return Target(load_config(path), LOG)

    def test_retries_simpler_params_until_results(self):
        t = self.make()
        empty = {"data": {"search": {"products": []}}}
        full = {"data": {"search": {"products": [{"tcin": "123"}]}}}
        with mock.patch.object(t, "get_json", side_effect=[empty, full]) as g, mock.patch.object(t, "pause"):
            out = t._search_raw("pokemon tcg", 24)
        self.assertEqual(out[0]["tcin"], "123")
        self.assertEqual(g.call_count, 2)

    def test_seed_products_used_when_search_empty(self):
        t = self.make()
        info = {"title": "Pokemon ETB", "price": 59.99, "upc": "196214158801", "image": None, "third_party": False}
        with mock.patch.object(t, "details", return_value=info), mock.patch.object(t, "pause"):
            seeds = t.seed_products()
        self.assertEqual(len(seeds), len(t.SEED_TCINS))
        self.assertEqual(seeds[0].online_status, "UNCHECKED")


if __name__ == "__main__":
    unittest.main()
