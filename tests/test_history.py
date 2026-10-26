"""The rolling store history survives a restart and feeds the trust table."""
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
