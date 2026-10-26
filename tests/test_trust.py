import unittest

from restock import trust
from restock.panel import store_domains


def health(success, checks, last_block=""):
    return {"success": success, "checks": checks, "last_block": last_block}


CMP = [
    {"store": "cvs", "method": "direct", "runs": 12, "ok": 2, "last_ok": False, "last_kind": "denied", "avg_ms": 1, "last_t": 1},
    {"store": "cvs", "method": "my-chrome", "runs": 12, "ok": 12, "last_ok": True, "last_kind": "", "avg_ms": 1, "last_t": 1},
]
TRK = [{"method": "direct", "site": "cvs.com", "checks": 40, "blocks": 30, "streak": 0, "avg_before_block": 1,
        "best": 3, "last_block": 1, "last_kind": "denied"},
       {"method": "my-chrome", "site": "www.cvs.com", "checks": 40, "blocks": 1, "streak": 20, "avg_before_block": 20,
        "best": 30, "last_block": 1, "last_kind": "denied"}]


class TrustTests(unittest.TestCase):
    def row(self, name, h, cmp=CMP, trk=TRK, feed=None):
        return trust.store_row(name, name.title(), h, cmp, trk, store_domains(name), feed)

    def test_reliable_from_real_checks(self):
        r = self.row("cvs", health(97, 40))
        self.assertEqual(r["verdict"], "Reliable")
        self.assertEqual(r["best_method"], "my-chrome")

    def test_blocked_points_to_best_method(self):
        r = self.row("cvs", health(20, 40, "denied"))
        self.assertEqual(r["verdict"], "Blocked")
        self.assertIn("my-chrome", r["advice"])
        self.assertIn("denied", r["advice"])

    def test_flaky_band(self):
        self.assertEqual(self.row("cvs", health(75, 30))["verdict"], "Flaky")

    def test_falls_back_to_tracker_then_compare(self):
        r = self.row("cvs", health(None, 0))
        self.assertEqual(r["verdict"], "Reliable")          # my-chrome 39/40 in the tracker
        r = self.row("cvs", health(None, 0), trk=[])
        self.assertIn("side-by-side", r["basis"])

    def test_not_enough_data(self):
        r = self.row("gamestop", health(100, 3), cmp=[], trk=[])
        self.assertEqual(r["verdict"], "Not enough data")
        self.assertIsNone(r["score"])

    def test_tracker_site_matching_is_exact_enough(self):
        trk = [{"method": "x", "site": "notcvs.com", "checks": 50, "blocks": 50, "streak": 0, "avg_before_block": 0,
                "best": 0, "last_block": 1, "last_kind": ""}]
        r = self.row("cvs", health(None, 0), cmp=[], trk=trk)
        self.assertEqual(r["verdict"], "Not enough data")

    def test_official_feed_needs_key(self):
        f = trust.feed_state("bestbuy", {"api_key": ""})
        self.assertEqual(f["state"], "needs_key")
        r = self.row("bestbuy", health(0, 12), cmp=[], trk=[], feed=f)
        self.assertEqual(r["verdict"], "Needs setup")
        self.assertIn("developer.bestbuy.com", r["advice"])
        f = trust.feed_state("bestbuy", {"api_key": "abc"})
        r = self.row("bestbuy", health(100, 30), cmp=[], trk=[], feed=f)
        self.assertEqual(r["verdict"], "Reliable")
        self.assertIn("Best Buy developer API", r["advice"])

    def test_kroger_needs_both_keys(self):
        self.assertEqual(trust.feed_state("kroger", {"client_id": "a"})["state"], "needs_key")
        self.assertEqual(trust.feed_state("kroger", {"client_id": "a", "client_secret": "b"})["state"], "on")
        self.assertIsNone(trust.feed_state("target", {}))

    def test_missing_feeds_lists_only_stores_not_running(self):
        cfgs = {"bestbuy": {}, "kroger": {"client_id": "a", "client_secret": "b"}}
        out = trust.missing_feeds(lambda n: cfgs.get(n, {}), {"target"})
        self.assertEqual([f["store"] for f in out], ["bestbuy"])
        out = trust.missing_feeds(lambda n: cfgs.get(n, {}), {"target", "bestbuy"})
        self.assertEqual(out, [])

    def test_sorted_worst_first(self):
        rows = trust.build([{"name": "cvs", "display": "CVS", **health(97, 40)},
                            {"name": "gamestop", "display": "GameStop", **health(10, 40)}],
                           CMP, TRK, store_domains, lambda n: {})
        self.assertEqual([r["store"] for r in rows], ["gamestop", "cvs"])

    def test_domains(self):
        self.assertIn("fredmeyer.com", store_domains("kroger"))
        self.assertEqual(store_domains("gamestop"), ("gamestop.com",))
        self.assertEqual(store_domains("nonsense"), ())


if __name__ == "__main__":
    unittest.main()
