"""Online alerts and in-store alerts go to their own channels and show only their own side."""
import logging
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from restock.geo import Area  # noqa: E402
from restock.models import StockResult, StoreStock  # noqa: E402
from restock.notify import DiscordNotifier  # noqa: E402

LOG = logging.getLogger("split")
H = "https://discord.com/api/webhooks/"


def res(online=False, stores=()):
    return StockResult(retailer="cvs", retailer_name="CVS", product_id="1", title="Pokemon Booster", url="https://x/1",
                       online=online, online_status="In stock" if online else "", stores=list(stores))


def st(sid, area="", pickup=None):
    return StoreStock(store_id=sid, name=f"CVS {sid}", qty=5, area=area, pickup=pickup)


class SplitTests(unittest.TestCase):
    def hooks(self, **kw):
        return DiscordNotifier({"webhooks": kw}, LOG, kw.pop("areas", ()))

    def test_online_channel_never_shows_stores_and_store_channel_never_shows_online(self):
        n = self.hooks(online=H + "o", in_store=H + "s")
        routes = dict(n.routes(res(online=True, stores=[st("1"), st("2")])))
        self.assertEqual(routes[H + "o"].stores, [])
        self.assertTrue(routes[H + "o"].online)
        self.assertFalse(routes[H + "s"].online)
        self.assertEqual(len(routes[H + "s"].stores), 2)

    def test_in_store_only_stock_skips_the_online_channel(self):
        n = self.hooks(online=H + "o", in_store=H + "s")
        self.assertEqual([u for u, _ in n.routes(res(stores=[st("1")]))], [H + "s"])

    def test_online_only_stock_skips_the_store_channel(self):
        n = self.hooks(online=H + "o", in_store=H + "s")
        self.assertEqual([u for u, _ in n.routes(res(online=True))], [H + "o"])

    def test_only_the_side_that_changed_is_posted(self):
        n = self.hooks(online=H + "o", in_store=H + "s")
        item = res(online=True, stores=[st("1")])          # both in stock now, but only stores are new
        self.assertEqual([u for u, _ in n.routes(item, new_online=False, new_stores=True)], [H + "s"])
        self.assertEqual([u for u, _ in n.routes(item, new_online=True, new_stores=False)], [H + "o"])

    def test_one_shared_channel_gets_one_combined_alert(self):
        n = self.hooks(default=H + "d")
        out = n.routes(res(online=True, stores=[st("1")]))
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0][1].online)
        self.assertEqual(len(out[0][1].stores), 1)

    def test_area_channel_shows_only_stores(self):
        areas = [Area("Reno", "89502", 10, webhook=H + "reno")]
        n = DiscordNotifier({"webhooks": {"online": H + "o", "in_store": H + "s"}}, LOG, areas)
        routes = dict(n.routes(res(online=True, stores=[st("1", "Reno"), st("2", "Tulsa")])))
        self.assertFalse(routes[H + "reno"].online)
        self.assertEqual([s.store_id for s in routes[H + "reno"].stores], ["1"])

    def test_store_named_channel_still_shows_everything(self):
        n = self.hooks(cvs=H + "c", online=H + "o")
        routes = n.routes(res(online=True, stores=[st("1")]))
        self.assertEqual(len(routes), 1)
        self.assertTrue(routes[0][1].online and routes[0][1].stores)

    def test_reason_text_matches_each_channel(self):
        item = res(online=True, stores=[st("1"), st("2"), st("3")])
        r = "online restock, in stock at 21 new store(s)"
        self.assertEqual(DiscordNotifier.reason_for(res(online=True), r, ("1", "2")), "online restock")
        self.assertEqual(DiscordNotifier.reason_for(res(stores=item.stores), r, ("1", "2")), "in stock at 2 new store(s)")

    def test_posts_end_to_end(self):
        n = DiscordNotifier({"webhooks": {"online": H + "o", "in_store": H + "s"}}, LOG)
        sent = []
        n._post = lambda url, payload: sent.append((url, payload["embeds"][0])) or True
        item = res(online=True, stores=[st("1"), st("2")])
        self.assertTrue(n.restock(item, "online restock, in stock at 2 new store(s)", ("1", "2")))
        by = dict(sent)
        online_text = by[H + "o"].get("description", "") + " ".join(f["name"] + f["value"] for f in by[H + "o"]["fields"])
        store_text = by[H + "s"].get("description", "") + " ".join(f["name"] + f["value"] for f in by[H + "s"]["fields"])
        self.assertNotIn("CVS 1", online_text)
        self.assertNotIn("near you", online_text)
        self.assertNotIn("Online", [f["name"] for f in by[H + "s"]["fields"]])
        self.assertNotIn("Online restock", store_text)
        self.assertIn("CVS 1", store_text)
        # only stores new: online channel stays quiet
        sent.clear()
        n.restock(item, "in stock at 1 new store(s)", ("2",))
        self.assertEqual([u for u, _ in sent], [H + "s"])


if __name__ == "__main__":
    unittest.main()
