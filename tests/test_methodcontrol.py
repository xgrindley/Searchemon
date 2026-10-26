"""Method control: buttons, auto-stop rule (more than 25 attempts and 50% failed), saved state."""
import logging
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from restock.sessions import BlockTracker  # noqa: E402
from restock.trials import BY_KEY, TrialPlan  # noqa: E402

LOG = logging.getLogger("mc")


def make(tmp, active=("direct-h2",), **extra):
    raw = {"trials": {"enabled": True, "slice_checks": 5, "active": list(active), **extra}}
    return TrialPlan(raw, tmp, LOG, BlockTracker(tmp)), raw


def feed(p, key, results, store="walmart"):
    arm = BY_KEY[key]
    for ok in results:
        p.note(store, arm, ok, "" if ok else "challenge")


class AutoStopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_not_stopped_at_exactly_25_attempts(self):
        p, _ = make(self.tmp)
        feed(p, "direct-h2", [False] * 25)
        self.assertIn("direct-h2", p.active_keys())          # needs MORE than 25

    def test_stopped_at_26th_attempt_when_half_or_more_fail(self):
        p, raw = make(self.tmp)
        feed(p, "direct-h2", [True] * 13 + [False] * 13)       # 26 attempts, exactly 50% failed
        self.assertNotIn("direct-h2", p.active_keys())
        self.assertNotIn("direct-h2", raw["trials"]["active"])
        snap = {a["key"]: a for a in p.snapshot()["arms"]}["direct-h2"]
        self.assertEqual((snap["stopped"]["attempts"], snap["stopped"]["fails"], snap["stopped"]["pct"]), (26, 13, 50))
        self.assertEqual(p.snapshot()["events"][-1]["kind"], "auto_stop")

    def test_healthy_method_keeps_running(self):
        p, _ = make(self.tmp)
        feed(p, "direct-h2", [True] * 20 + [False] * 6)        # 23% failed
        self.assertIn("direct-h2", p.active_keys())

    def test_rule_can_be_turned_off_or_tuned(self):
        p, _ = make(self.tmp, auto_stop=False)
        feed(p, "direct-h2", [False] * 40)
        self.assertIn("direct-h2", p.active_keys())
        p, _ = make(tempfile.mkdtemp(), stop_after=10, stop_fail_pct=80)
        feed(p, "direct-h2", [False] * 11)
        self.assertNotIn("direct-h2", p.active_keys())

    def test_errors_count_as_failures(self):
        p, _ = make(self.tmp)
        arm = BY_KEY["direct-h2"]
        for _ in range(26):
            p.fail("walmart", arm, "ReadTimeout")
        self.assertNotIn("direct-h2", p.active_keys())

    def test_control_is_never_counted_or_stopped(self):
        p, _ = make(self.tmp)
        feed(p, "direct", [False] * 40)
        self.assertEqual(p.saved["window"], {})


class ButtonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_toggle_on_gives_a_fresh_count_and_clears_the_stop(self):
        p, _ = make(self.tmp)
        feed(p, "direct-h2", [False] * 26)
        self.assertNotIn("direct-h2", p.active_keys())
        ok, _msg = p.set_active("direct-h2", True)
        self.assertTrue(ok)
        self.assertIn("direct-h2", p.active_keys())
        arm = {a["key"]: a for a in p.snapshot()["arms"]}["direct-h2"]
        self.assertEqual((arm["attempts"], arm["fails"], arm["stopped"]), (0, 0, None))

    def test_control_cannot_be_switched(self):
        p, _ = make(self.tmp)
        self.assertFalse(p.set_active("direct", False)[0])

    def test_keep_best_and_all_off(self):
        p, _ = make(self.tmp, active=["direct-h2", "browser-solo", "browser-own", "direct-warm"])
        for key, blocks in (("direct-h2", 0), ("browser-solo", 1), ("browser-own", 5), ("direct-warm", 9)):
            for i in range(20):
                p.tracker.record(key, "walmart", i >= blocks, "" if i >= blocks else "challenge")
        self.assertEqual(p.best_keys(3), ["direct-h2", "browser-solo", "browser-own"])
        ok, _ = p.keep_best(3)
        self.assertTrue(ok)
        self.assertEqual(sorted(p.active_keys()), ["browser-own", "browser-solo", "direct-h2"])
        p.all_off()
        self.assertEqual(p.active_keys(), [])

    def test_keep_best_needs_data(self):
        p, _ = make(self.tmp)
        self.assertFalse(p.keep_best(3)[0])
        self.assertEqual(p.active_keys(), ["direct-h2"])        # nothing changed


class SavedStateTests(unittest.TestCase):
    def test_restart_brings_back_buttons_counts_and_stops(self):
        tmp = tempfile.mkdtemp()
        p, _ = make(tmp, active=["direct-h2", "browser-solo"])
        p.set_active("browser-own", True)
        feed(p, "direct-h2", [False] * 26)                      # stopped by itself
        feed(p, "browser-solo", [True] * 3)
        p._save()
        # restart: config.yaml still lists the old defaults
        p2, raw2 = make(tmp, active=["direct-h2", "browser-solo"])
        self.assertEqual(sorted(p2.active_keys()), ["browser-own", "browser-solo"])
        self.assertEqual(sorted(raw2["trials"]["active"]), ["browser-own", "browser-solo"])
        arms = {a["key"]: a for a in p2.snapshot()["arms"]}
        self.assertEqual(arms["direct-h2"]["stopped"]["attempts"], 26)
        self.assertEqual(arms["browser-solo"]["attempts"], 3)
        self.assertEqual(p2.snapshot()["events"][-1]["kind"], "auto_stop")

    def test_first_run_uses_config_until_a_button_is_used(self):
        p, _ = make(tempfile.mkdtemp(), active=["direct-warm"])
        self.assertEqual(p.active_keys(), ["direct-warm"])

    def test_corrupt_state_file_is_ignored(self):
        tmp = tempfile.mkdtemp()
        with open(os.path.join(tmp, "trial-state.json"), "w") as fh:
            fh.write("{not json")
        p, _ = make(tmp)
        self.assertEqual(p.active_keys(), ["direct-h2"])


if __name__ == "__main__":
    unittest.main()
