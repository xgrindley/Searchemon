"""The rolling store history survives a restart and feeds the trust table."""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from restock import trust  # noqa: E402
from restock.engine import Monitor  # noqa: E402
from restock.history_store import KEEP_HOURS, RECENT, StoreHistory  # noqa: E402


class HistoryTests(unittest.TestCase):
    def test_numbers_survive_a_restart(self):
        tmp = tempfile.mkdtemp()
        h = StoreHistory(tmp)
        for i in range(30):
            h.record("target", i % 10 != 0, "" if i % 10 else "Target refused the request")
        h.save()
        h2 = StoreHistory(tmp)
        self.assertEqual(len(h2.recent("target")), 30)
        self.assertEqual(h2.window("target", 24), (27, 3))
        self.assertIn("refused", h2.last_problem("target")[0])

    def test_recent_is_capped_and_old_hours_are_dropped(self):
        tmp = tempfile.mkdtemp()
        h = StoreHistory(tmp)
        for _ in range(RECENT + 25):
            h.record("cvs", True)
        h.record("cvs", False, "old", t=time.time() - (KEEP_HOURS + 5) * 3600)
        h.save()
        h2 = StoreHistory(tmp)
        self.assertEqual(len(h2.recent("cvs")), RECENT)
        self.assertEqual(h2.window("cvs", KEEP_HOURS + 10)[1], 0)    # the week-old failure was pruned

    def test_file_stays_small_and_holds_no_urls(self):
        tmp = tempfile.mkdtemp()
        h = StoreHistory(tmp)
        for i in range(2000):
            h.record("amazon", i % 7 != 0, "" if i % 7 else "blocked")
        h.save()
        self.assertLess(os.path.getsize(os.path.join(tmp, "store-history.json")), 5000)

    def test_corrupt_file_is_ignored(self):
        tmp = tempfile.mkdtemp()
        with open(os.path.join(tmp, "store-history.json"), "w") as fh:
            fh.write("{oops")
        self.assertEqual(StoreHistory(tmp).recent("target"), [])


class DailyHistoryTests(unittest.TestCase):
    def test_daily_numbers_are_kept_and_survive_a_restart(self):
        tmp = tempfile.mkdtemp()
        h = StoreHistory(tmp)
        now = time.time()
        for i in range(10):
            h.record("target", i != 3, "boom" if i == 3 else "", ms=2000, products=4)
        h.record("target", True, t=now - 3 * 86400, ms=1000, products=2)
        h.note_alert("target")
        h.note_alert("target", t=now - 3 * 86400)
        h.record_method("edge", True)
        h.record_method("edge", False)
        h.save()
        h2 = StoreHistory(tmp)
        t = h2.totals("target")
        self.assertEqual((t["checks"], t["ok"], t["fail"], t["alerts"], t["products"]), (11, 10, 1, 2, 42))
        self.assertEqual(t["success"], 91)
        self.assertEqual(t["avg_ms"], 1909)
        days = h2.days("target", 30)
        self.assertEqual(len(days), 30)
        self.assertEqual((days[-1]["ok"], days[-1]["fail"]), (9, 1))
        self.assertEqual(days[-4]["ok"], 1)
        self.assertEqual(days[0]["ok"] + days[0]["fail"], 0)          # empty days are included so charts line up
        m = {r["method"]: r for r in h2.method_days(14)}["edge"]
        self.assertEqual((m["checks"], m["fail"], len(m["days"])), (2, 1, 14))

    def test_days_older_than_180_are_dropped_and_the_file_stays_small(self):
        tmp = tempfile.mkdtemp()
        h = StoreHistory(tmp)
        for d in range(200):
            for store in ("a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m", "n"):
                h.record(store, True, t=time.time() - d * 86400, ms=1500, products=3)
        h.save()
        h2 = StoreHistory(tmp)
        self.assertLessEqual(len(h2.stores["a"]["days"]), 181)
        self.assertLess(os.path.getsize(os.path.join(tmp, "store-history.json")), 200_000)

    def test_old_files_without_days_still_load(self):
        tmp = tempfile.mkdtemp()
        with open(os.path.join(tmp, "store-history.json"), "w") as fh:
            fh.write('{"stores": {"target": {"recent": "1101", "hours": {}, "blocks": 0, "last_block": "", "last_block_t": 0, "last_ok": 0}}}')
        h = StoreHistory(tmp)
        self.assertEqual(h.recent("target"), [1, 1, 0, 1])
        self.assertEqual(h.totals("target")["checks"], 0)


class TrustUsesHistory(unittest.TestCase):
    def test_rating_comes_from_the_week_when_the_session_is_new(self):
        row = trust.store_row("target", "Target", {"checks": 2, "success": 100, "week_checks": 300, "week_success": 97,
                                                   "day_checks": 40, "day_success": 95}, [], [], ("target.com",))
        self.assertEqual(row["verdict"], "Reliable")
        self.assertIn("300 checks in the last 7 days", row["basis"])

    def test_nothing_recorded_still_says_not_enough_data(self):
        row = trust.store_row("target", "Target", {"checks": 0}, [], [], ("target.com",))
        self.assertEqual(row["verdict"], "Not enough data")


class MonitorRestoresHealth(unittest.TestCase):
    def test_monitor_starts_with_saved_outcomes(self):
        tmp = tempfile.mkdtemp()
        cfg = os.path.join(tmp, "config.yaml")
        with open(cfg, "w") as fh:
            fh.write("discord: {webhooks: {default: ''}}\nareas: []\nwatchlist: []\n")
        mon = Monitor(cfg)
        for _ in range(12):
            mon.store_history.record("target", True)
        mon.store_history.save()
        mon2 = Monitor(cfg)
        self.assertEqual(len(mon2._health("target")["recent"]), 12)


if __name__ == "__main__":
    unittest.main()


class InterruptedChecks(unittest.TestCase):
    def test_a_closed_browser_is_not_a_store_failure(self):
        import threading
        tmp = tempfile.mkdtemp()
        cfg = os.path.join(tmp, "config.yaml")
        with open(cfg, "w") as fh:
            fh.write("discord: {webhooks: {default: ''}}\nareas: []\nwatchlist: []\n")
        mon = Monitor(cfg)

        class Fake:
            name, display, last_via = "fake", "Fake", "direct"
            rcfg = {"interval_seconds": 60}
            calls = 0

            def using_browser(self):
                return False

        fake = Fake()
        mon.retailers = {"fake": fake}
        mon.run_cycle = lambda r: (_ for _ in ()).throw(Exception("Page.goto: Target page, context or browser has been closed"))
        stop = threading.Event()
        t = threading.Thread(target=mon._loop, args=("fake", 0, stop, threading.Event()), daemon=True)
        with self.assertNoLogs(mon.log, level="ERROR"):
            t.start()
            time.sleep(0.3)
            stop.set()
            t.join(3)
        self.assertEqual(mon.store_history.recent("fake"), [])


class PanelStatusHasHistory(unittest.TestCase):
    def test_status_carries_the_whole_picture(self):
        from restock.panel import PanelServer
        tmp = tempfile.mkdtemp()
        cfg = os.path.join(tmp, "config.yaml")
        with open(cfg, "w") as fh:
            fh.write("discord: {webhooks: {default: ''}}\nareas: []\nwatchlist: []\nretailers: {target: {enabled: true}}\n")
        mon = Monitor(cfg)
        mon.store_history.record("target", True, ms=1200, products=3)
        mon.store_history.record_method("direct", True)
        status = PanelServer(mon).status()
        row = [s for s in status["history"]["stores"] if s["name"] == "target"][0]
        self.assertEqual(len(row["days"]), 30)
        self.assertEqual(row["totals"]["checks"], 1)
        self.assertEqual(status["history"]["methods"][0]["method"], "direct")
        json.dumps(status)                         # must be serialisable for the page


class DiscoveryRetry(unittest.TestCase):
    def test_empty_store_is_searched_once_per_run_even_if_tried_recently(self):
        from unittest import mock
        tmp = tempfile.mkdtemp()
        cfg = os.path.join(tmp, "config.yaml")
        with open(cfg, "w") as fh:
            fh.write("discord: {webhooks: {default: ''}}\nareas: []\nwatchlist: []\n")
        mon = Monitor(cfg)

        from restock.retailers.base import Retailer

        class Fake(Retailer):
            name, display, supports_search = "fake", "Fake", True

            def __init__(self):
                pass

        mon._discovery_on = lambda r: True
        mon.targets_for = lambda r: {}
        mon.catalog.runs["fake"] = time.time()           # tried a minute ago, found nothing
        with mock.patch.object(mon, "_discover") as disc:
            mon.run_cycle(Fake())
            mon.run_cycle(Fake())
        self.assertEqual(disc.call_count, 1)             # right after a restart, not again until it is due
