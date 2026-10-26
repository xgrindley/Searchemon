"""Tests for trial methods: one arm at a time per store, slices, rest on block, fallbacks, trace."""
import json
import logging
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from restock.retailers import base as base_mod  # noqa: E402
from restock.retailers.base import Blocked, Retailer  # noqa: E402
from restock.retailers.browser import FetchResult  # noqa: E402
from restock.sessions import BlockTracker  # noqa: E402
from restock.trials import BY_KEY, CATALOG, TrialPlan  # noqa: E402

PRODUCT = '<html><script type="application/ld+json">{"@type":"Product"}</script>Add to cart</html>'
CHALLENGE = '<html><title>Just a moment...</title><script>window._cf_chl_opt={}</script></html>'
LOG = logging.getLogger("t6")


def plan(tmp, **trials):
    raw = {"trials": {"enabled": True, "slice_checks": 2, "rest_minutes": 90, "active": ["direct-h2"], **trials}}
    return TrialPlan(raw, tmp, LOG, BlockTracker(tmp))


class RotationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def sequence(self, p, store, n, family="direct"):
        out = []
        for _ in range(n):
            arm = p.arm_for(store, family)
            out.append(arm.key if arm else "normal")   # None = nothing to compare, run the normal way
            if arm:
                p.note(store, arm, True)
        return out

    def test_one_arm_at_a_time_in_slices_with_control_included(self):
        p = plan(self.tmp)
        self.assertEqual(self.sequence(p, "walmart", 8),
                         ["direct", "direct", "direct-h2", "direct-h2", "direct", "direct", "direct-h2", "direct-h2"])

    def test_stores_rotate_independently(self):
        p = plan(self.tmp)
        self.sequence(p, "walmart", 2)
        self.assertEqual(p.arm_for("cvs", "direct").key, "direct")
        self.assertEqual(p.state["walmart"]["used"], 2)

    def test_only_active_arms_run(self):
        p = plan(self.tmp, active=["browser-solo"])
        self.assertEqual(set(self.sequence(p, "walmart", 6)), {"normal"})   # a browser arm is not a direct arm
        self.assertEqual(set(self.sequence(p, "amazon", 6, "browser")), {"browser-rotate", "browser-solo"})

    def test_nothing_to_compare_means_normal_behaviour(self):
        p = plan(self.tmp, active=[])
        self.assertIsNone(p.arm_for("walmart", "direct"))

    def test_disabled_and_store_filter(self):
        self.assertIsNone(plan(self.tmp, enabled=False).arm_for("walmart", "direct"))
        p = plan(self.tmp, stores=["cvs"])
        self.assertIsNone(p.arm_for("walmart", "direct"))
        self.assertIsNotNone(p.arm_for("cvs", "direct"))

    def test_blocked_arm_rests_and_control_carries_on(self):
        p = plan(self.tmp)
        self.sequence(p, "walmart", 2)
        arm = p.arm_for("walmart", "direct")
        self.assertEqual(arm.key, "direct-h2")
        p.note("walmart", arm, False, "challenge")
        self.assertEqual(set(self.sequence(p, "walmart", 6)), {"normal"})   # only the control is left
        self.assertEqual([r["arm"] for r in p.snapshot()["resting"]], ["direct-h2"])
        p.state["walmart"]["rest"]["direct-h2"] = time.time() - 1       # rest is over
        self.assertIn("direct-h2", self.sequence(p, "walmart", 4))

    def test_blocked_control_does_not_rest_anything(self):
        p = plan(self.tmp)
        arm = p.arm_for("walmart", "direct")
        p.note("walmart", arm, False, "rate_limit")
        self.assertEqual(p.snapshot()["resting"], [])

    def test_skip_moves_on_without_counting(self):
        p = plan(self.tmp, active=["browser-own"])
        self.sequence(p, "cvs", 2, "browser")
        arm = p.arm_for("cvs", "browser")
        self.assertEqual(arm.key, "browser-own")
        p.skip("cvs", arm, "your own Chrome is not running")
        self.assertIsNone(p.arm_for("cvs", "browser"))      # only the control is left, so the normal way runs
        self.assertNotIn("browser-own", [r for r in BlockTracker(self.tmp).data])

    def test_tracker_gets_trial_results_but_not_control(self):
        p = plan(self.tmp)
        self.sequence(p, "walmart", 4)
        data = p.tracker.data
        self.assertIn("direct-h2", data)
        self.assertEqual(data["direct-h2"]["walmart"]["checks"], 2)
        self.assertNotIn("direct", data)       # the control is already counted where the request is made

    def test_unavailable_arm_is_left_out(self):
        p = plan(self.tmp)
        p.mark_unavailable("direct-h2", "needs a package")
        self.assertIsNone(p.arm_for("walmart", "direct"))
        arm = [a for a in p.snapshot()["arms"] if a["key"] == "direct-h2"][0]
        self.assertEqual(arm["unavailable"], "needs a package")

    def test_interval_factor_only_for_half_pace_arm(self):
        p = plan(self.tmp, active=["browser-slow"])
        self.assertEqual(p.interval_factor("amazon"), 1.0)
        for _ in range(4):
            arm = p.arm_for("amazon", "browser")
            if arm.key == "browser-slow":
                break
            p.note("amazon", arm, True)
        self.assertEqual(p.interval_factor("amazon"), 2.0)

    def test_trace_log_records_switches_and_blocks(self):
        p = plan(self.tmp)
        self.sequence(p, "walmart", 2)
        arm = p.arm_for("walmart", "direct")
        p.note("walmart", arm, False, "challenge")
        with open(os.path.join(self.tmp, "trial-log.jsonl"), encoding="utf-8") as fh:
            events = [json.loads(line) for line in fh]
        self.assertEqual([e["event"] for e in events], ["switch", "switch", "blocked"])
        self.assertEqual(events[-1]["arm"], "direct-h2")

    def test_stealth_arms_are_off_by_default_and_run_when_switched_on(self):
        p = plan(self.tmp)
        on = {a["key"]: a["on"] for a in p.snapshot()["arms"]}
        self.assertFalse(on["direct-impersonate"])
        self.assertFalse(on["browser-stealth"])
        p = plan(self.tmp, active=["direct-impersonate"])
        self.assertIn("direct-impersonate", self.sequence(p, "walmart", 4))

    def test_catalog_has_one_control_per_family_and_sources(self):
        for fam in ("direct", "browser"):
            self.assertEqual(len([a for a in CATALOG if a.family == fam and a.control]), 1)
        self.assertTrue(all(a.source and a.idea for a in CATALOG))
        self.assertEqual(BY_KEY["browser-slow"].interval_factor, 2.0)


class FakeShop(Retailer):
    name = "fakeshop"
    display = "Fake Shop"

    def _fetch_html_normal(self, url):
        self.normal_calls += 1
        return FetchResult(200, PRODUCT, url, None)

    def _h2_get(self, url):
        if isinstance(self.h2_result, Exception):
            raise self.h2_result
        return self.h2_result


class FetchPathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.plan = plan(self.tmp, slice_checks=1)
        base_mod.set_trials(self.plan)
        self.shop = FakeShop.__new__(FakeShop)
        self._init_shop()

    def _init_shop(self):
        import requests
        s = self.shop
        s.cfg, s.rcfg, s.log, s.browser, s.browser_until, s.last_via = None, {}, LOG, None, 0.0, "direct"
        s._h2 = s._warm_session = None
        s._warmed = {}
        s.session = requests.Session()
        s.normal_calls = 0
        s.h2_result = (200, PRODUCT, {}, "https://fake.test/p/1")

    def tearDown(self):
        base_mod.set_trials(None)

    def test_control_turn_uses_normal_path_then_trial_turn_uses_h2(self):
        self.shop.fetch_html("https://fake.test/p/1")                 # control
        self.assertEqual(self.shop.normal_calls, 1)
        res = self.shop.fetch_html("https://fake.test/p/1")           # direct-h2 turn
        self.assertEqual(self.shop.normal_calls, 1)
        self.assertEqual(res.status, 200)
        self.assertEqual(self.plan.tracker.data["direct-h2"]["fakeshop"]["checks"], 1)

    def test_blocked_trial_falls_back_to_normal_and_rests(self):
        self.shop.fetch_html("https://fake.test/p/1")
        self.shop.h2_result = (403, CHALLENGE, {}, "https://fake.test/p/1")
        res = self.shop.fetch_html("https://fake.test/p/1")
        self.assertEqual(res.text, PRODUCT)                            # the real answer came from the normal path
        self.assertEqual(self.shop.normal_calls, 2)
        self.assertEqual(self.plan.tracker.data["direct-h2"]["fakeshop"]["blocks"], 1)
        self.assertEqual(len(self.plan.snapshot()["resting"]), 1)

    def test_network_error_on_trial_is_not_counted_as_a_block(self):
        self.shop.fetch_html("https://fake.test/p/1")
        self.shop.h2_result = OSError("boom")
        res = self.shop.fetch_html("https://fake.test/p/1")
        self.assertEqual(res.text, PRODUCT)
        self.assertNotIn("direct-h2", self.plan.tracker.data)

    def test_missing_http2_package_skips_the_arm_with_a_message(self):
        self.shop.fetch_html("https://fake.test/p/1")
        self.shop.h2_result = base_mod._ArmUnavailable("needs httpx")
        res = self.shop.fetch_html("https://fake.test/p/1")
        self.assertEqual(res.text, PRODUCT)
        self.assertIn("direct-h2", self.plan.unavailable)

    def test_normal_block_on_control_turn_is_counted_and_raised(self):
        def blocked(url):
            raise Blocked("Fake Shop asked for a bot check", 900)
        self.shop._fetch_html_normal = blocked
        with self.assertRaises(Blocked):
            self.shop.fetch_html("https://fake.test/p/1")
        self.assertEqual(self.plan.state["fakeshop"]["used"], 0)       # a block ends the slice


if __name__ == "__main__":
    unittest.main()
