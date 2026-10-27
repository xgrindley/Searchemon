"""Stock timeline: allocation per store, how often it restocks, how fast it sells out, and the store ranking."""
import logging
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from restock.engine import Monitor  # noqa: E402
from restock.models import StockResult, StoreStock  # noqa: E402
from restock.notify import DiscordNotifier  # noqa: E402
from restock.stockwatch import StockWatch, fmt_minutes  # noqa: E402

T0 = 1_790_000_000.0      # a fixed moment, so day and hour do not depend on when the test runs
MIN = 60


def res(stores=(), online=False, key="1", title="Pokemon TCG Phantasmal Flames Elite Trainer Box", checked=True, retailer="target"):
    r = StockResult(retailer, retailer.title(), key, title, "https://x.test", price=49.99, online=online,
                    stores=[StoreStock(sid, name, distance=d, qty=q, area="Home") for sid, name, q, d in stores],
                    type_label="Elite Trainer Box")
    r.stores_checked = checked
    return r


class Tmp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        for h in list(logging.getLogger("restock").handlers):
            h.close()
            logging.getLogger("restock").removeHandler(h)
        shutil.rmtree(self.dir, ignore_errors=True)


class TimelineTests(Tmp):
    def test_a_restock_is_timed_from_appearing_to_selling_out(self):
        sw = StockWatch(self.dir)
        sw.observe(res(), T0)                                                        # out of stock
        sw.observe(res([("11", "Sparks", 12, 3.0)]), T0 + 10 * MIN)                  # lands between checks
        sw.observe(res([("11", "Sparks", 7, 3.0)]), T0 + 20 * MIN)
        sw.observe(res([("11", "Sparks", 2, 3.0)]), T0 + 30 * MIN)
        sw.observe(res(), T0 + 40 * MIN)                                             # gone
        run = sw.runs[-1]
        self.assertEqual((run["q0"], run["qmax"], run["qlast"]), (12, 12, 2))
        self.assertEqual(run["minutes"], 30.0)                                       # 5 min in to 35 min in
        self.assertEqual(run["per_hour"], 30.0)                                      # 10 sold in 20 minutes
        self.assertEqual(run["start_precision"], 10 * MIN)
        self.assertEqual(sw.sellout_minutes("target", "store:11"), (30.0, 1))
        self.assertEqual(sw.hint("target", "store:11"), "")                          # one run is not a pattern yet

    def test_stock_already_there_or_a_gap_is_not_timed(self):
        sw = StockWatch(self.dir)
        sw.observe(res([("11", "Sparks", 5, 3.0)]), T0)                              # first ever look: start unknown
        sw.observe(res(), T0 + 10 * MIN)
        self.assertIsNone(sw.runs[-1]["minutes"])
        sw.observe(res([("11", "Sparks", 5, 3.0)]), T0 + 20 * MIN)
        sw.observe(res(), T0 + 20 * MIN + 4 * 3600)                                  # the app was off in between
        self.assertGreater(sw.runs[-1]["end_precision"], 3600)
        self.assertIsNone(sw.runs[-1]["minutes"])

    def test_an_online_only_check_does_not_end_store_stock(self):
        sw = StockWatch(self.dir)
        sw.observe(res(), T0)
        sw.observe(res([("11", "Sparks", 5, 3.0)]), T0 + 5 * MIN)
        sw.observe(res(checked=False), T0 + 10 * MIN)                                # did not look at shelves
        self.assertEqual(len(sw.runs), 0)
        self.assertEqual(len(sw.open_runs()), 1)

    def test_open_runs_survive_a_restart(self):
        sw = StockWatch(self.dir)
        sw.observe(res(), T0)
        sw.observe(res(online=True), T0 + 5 * MIN)
        sw.save()
        with mock.patch("restock.stockwatch.time.time", return_value=T0 + 10 * MIN):
            again = StockWatch(self.dir)
        self.assertEqual(len(again.open_runs()), 1)
        again.observe(res(), T0 + 15 * MIN)
        self.assertEqual(again.runs[-1]["minutes"], 7.5)                         # 2.5 min in to 10 min in
        self.assertEqual(again.runs[-1]["ch"], "online")

    def test_report_ranks_stores_and_says_where_to_go_first(self):
        sw = StockWatch(self.dir)
        t = T0
        for week in range(3):
            base = t + week * 7 * 86400
            sw.observe(res(), base)
            # Sparks: 4 units, gone in about 15 minutes. Reno: 12 units, lasts a day.
            sw.observe(res([("11", "Sparks", 4, 3.0), ("22", "Reno", 12, 9.0)]), base + 10 * MIN)
            sw.observe(res([("22", "Reno", 10, 9.0)]), base + 30 * MIN)
            for hour in range(1, 21):
                sw.observe(res([("22", "Reno", max(3, 10 - hour // 3), 9.0)]), base + hour * 3600)
            sw.observe(res(), base + 21 * 3600)
        with mock.patch("restock.stockwatch.time.time", return_value=T0 + 21 * 86400):
            rep = sw.report(60)
        rows = {r["place"]: r for r in rep["rows"]}
        self.assertEqual(rows["Sparks"]["restocks"], 3)
        self.assertEqual(rows["Sparks"]["sellout_min"], 15.0)                   # 5 min in to 20 min in
        self.assertEqual(rows["Sparks"]["advice"], "Go first: sells out fast")
        self.assertEqual(rows["Reno"]["units_per_restock"], 12)
        self.assertGreater(rows["Reno"]["sellout_min"], 20 * 60)
        self.assertEqual(rep["rows"][0]["score"], 100)
        self.assertEqual(rep["products"][0]["places"], 2)
        self.assertEqual(sw.hint("target", "store:11"), "usually sold out in 15 min")

    def test_minutes_in_words(self):
        self.assertEqual([fmt_minutes(x) for x in (None, 0.5, 20, 150, 4320)],
                         ["not known yet", "under a minute", "20 min", "2.5 h", "3 days"])


class AlertTests(Tmp):
    def test_alerts_say_how_fast_each_store_sells_out_and_where_to_go_first(self):
        path = os.path.join(self.dir, "config.yaml")
        with open(path, "w") as fh:
            fh.write("discord: {webhooks: {default: ''}}\nsettings: {windows_toast: false}\n"
                     "discovery: {enabled: false, places: false}\nbrowser: {enabled: false}\n")
        mon = Monitor(path)
        try:
            sw = mon.stockwatch
            for i in range(2):
                b = T0 + i * 86400
                sw.observe(res(), b)
                sw.observe(res([("11", "Sparks", 4, 3.0), ("22", "Reno", 12, 9.0)]), b + 10 * MIN)
                sw.observe(res([("22", "Reno", 9, 9.0)]), b + 30 * MIN)
                sw.observe(res(), b + 70 * MIN)
            live = res([("11", "Sparks", 4, 3.0), ("22", "Reno", 12, 9.0)])
            mon._sellout_hints(live)
            self.assertEqual(live.stores[0].hint, "usually sold out in 15 min")
            self.assertTrue(live.visit_plan.startswith("Go first to the store that sells out fastest: Sparks (15 min), then Reno"))
            posted = []
            n = DiscordNotifier({"webhooks": {"default": "https://discord.com/api/webhooks/1/a"}}, logging.getLogger("t"), [])
            with mock.patch("restock.notify.requests.post", side_effect=lambda url, json=None, timeout=None:
                            (posted.append(json), mock.Mock(status_code=204))[1]):
                n.restock(live, "in stock at 2 new store(s)", ("11", "22"))
            embed = posted[0]["embeds"][0]
            self.assertIn("Go first", embed["description"])
            self.assertIn("usually sold out in 15 min", " ".join(f["value"] for f in embed["fields"]))
        finally:
            mon.close()


if __name__ == "__main__":
    unittest.main()
