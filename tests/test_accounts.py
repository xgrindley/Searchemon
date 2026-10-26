"""Sign-in tracking: cookies are classified by name only, saved to disk, and shown with whether the store works."""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from restock.accounts import AccountTracker, classify  # noqa: E402


def ck(name, domain=".walmart.com", expires=None):
    return {"name": name, "value": "SECRETVALUE", "domain": domain, "expires": expires if expires is not None else time.time() + 86400 * 30}


class ClassifyTests(unittest.TestCase):
    def test_login_cookies_count_and_tracking_cookies_do_not(self):
        jar = [ck("customer_id"), ck("auth_token"), ck("_pxhd"), ck("_abck"), ck("_ga"), ck("JSESSIONID"), ck("x", ".other.com")]
        got = classify(jar, "walmart.com")
        self.assertEqual((got["total"], got["strong"]), (6, 2))

    def test_anonymous_browser_is_not_signed_in(self):
        self.assertEqual(classify([ck("JSESSIONID"), ck("_px3")], "walmart.com")["strong"], 0)

    def test_expired_cookies_are_ignored_and_expiry_is_the_earliest_login_cookie(self):
        now = time.time()
        jar = [ck("auth_old", expires=now - 10), ck("auth_a", expires=now + 5 * 86400), ck("auth_b", expires=now + 9 * 86400)]
        got = classify(jar, "walmart.com", now)
        self.assertEqual(got["strong"], 2)
        self.assertAlmostEqual(got["expires"], now + 5 * 86400, delta=2)

    def test_values_are_never_kept(self):
        got = classify([ck("auth_token")], "walmart.com")
        self.assertNotIn("SECRETVALUE", str(got))


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def report(self, strong=2, total=9):
        return {"edge": {"walmart": {"total": total, "strong": strong, "expires": int(time.time()) + 86400 * 20}}}

    def view(self, t, health=None):
        return {v["site"]: v for v in t.view(lambda s: health, lambda s: s.title())}

    def test_signing_in_is_saved_and_shown(self):
        t = AccountTracker(self.tmp)
        notes = t.update(self.report())
        self.assertTrue(any("signed in and saved" in n for n in notes))
        v = self.view(t)["walmart"]
        self.assertEqual((v["state"], v["profiles"]), ("signed_in", ["edge"]))
        self.assertEqual(self.view(t)["cvs"]["state"], "none")

    def test_it_survives_a_restart(self):
        AccountTracker(self.tmp).update(self.report())
        v = self.view(AccountTracker(self.tmp))["walmart"]
        self.assertEqual(v["state"], "signed_in")
        self.assertGreater(v["since"], 0)

    def test_working_comes_from_how_the_store_is_loading(self):
        t = AccountTracker(self.tmp)
        t.update(self.report())
        good = {"success": 97, "checks": 40, "last_ok": time.time() - 60}
        bad = {"success": 30, "checks": 40, "last_ok": time.time() - 60}
        self.assertTrue(self.view(t, good)["walmart"]["working"])
        self.assertFalse(self.view(t, bad)["walmart"]["working"])
        self.assertIsNone(self.view(t, {"success": None, "checks": 0})["walmart"]["working"])

    def test_losing_the_sign_in_is_noticed(self):
        t = AccountTracker(self.tmp)
        t.update(self.report())
        notes = t.update(self.report(strong=0, total=3))
        self.assertTrue(any("is gone" in n for n in notes))
        v = self.view(t)["walmart"]
        self.assertEqual(v["state"], "none")
        self.assertGreater(v["lost"], 0)

    def test_i_signed_in_button_covers_stores_with_unrecognised_cookies(self):
        t = AccountTracker(self.tmp)
        t.update(self.report(strong=0, total=12))
        self.assertEqual(self.view(t)["walmart"]["state"], "none")
        self.assertTrue(t.confirm("walmart"))
        self.assertEqual(self.view(t)["walmart"]["state"], "signed_in")
        self.assertTrue(self.view(t)["walmart"]["confirmed"])
        t.update(self.report(strong=0, total=12))                         # next scan keeps it
        self.assertEqual(self.view(t)["walmart"]["state"], "signed_in")
        t.update(self.report(strong=0, total=0))                          # cookies wiped
        self.assertEqual(self.view(t)["walmart"]["state"], "none")

    def test_confirm_needs_saved_cookies(self):
        self.assertFalse(AccountTracker(self.tmp).confirm("walmart"))

    def test_file_has_no_cookie_values(self):
        t = AccountTracker(self.tmp)
        t.update(self.report())
        with open(os.path.join(self.tmp, "accounts.json"), encoding="utf-8") as fh:
            self.assertNotIn("SECRETVALUE", fh.read())


if __name__ == "__main__":
    unittest.main()


class EngineAndPanel(unittest.TestCase):
    def make(self):
        from restock.engine import Monitor
        tmp = tempfile.mkdtemp()
        cfg = os.path.join(tmp, "config.yaml")
        with open(cfg, "w") as fh:
            fh.write("discord: {webhooks: {default: ''}}\nareas: []\nwatchlist: []\n")
        return Monitor(cfg)

    def test_worker_reports_counts_from_its_cookie_jar(self):
        from restock.retailers.browser import BrowserWorker

        class Ctx:
            def cookies(self):
                return [ck("customer_id", ".dickssportinggoods.com"), ck("_px3", ".dickssportinggoods.com")]

        w = BrowserWorker.__new__(BrowserWorker)
        w.ctx = Ctx()
        rep = w._cookies()
        self.assertEqual(rep["dicks"]["strong"], 1)
        self.assertEqual(rep["walmart"]["total"], 0)

    def test_scan_updates_the_tracker_and_the_panel_status_shows_it(self):
        from restock.panel import PanelServer

        mon = self.make()

        class FakeBrowser:
            usable = True

            def cookie_report(self):
                return {"edge": {"dicks": {"total": 8, "strong": 2, "expires": int(time.time()) + 86400 * 10}}}

        mon.browser = FakeBrowser()
        mon.scan_accounts()
        mon.browser = None
        status = PanelServer(mon).status()
        row = {a["site"]: a for a in status["accounts"]}["dicks"]
        self.assertEqual((row["state"], row["profiles"]), ("signed_in", ["edge"]))
        self.assertEqual(row["display"], "Dick's Sporting Goods")

    def test_panel_action_confirm_and_open(self):
        mon = self.make()
        opened = []
        mon.open_in_browser = opened.append
        mon.accounts.update({"edge": {"cvs": {"total": 5, "strong": 0, "expires": 0}}})
        self.assertTrue(mon.accounts.confirm("cvs"))
        from restock.accounts import SIGN_IN
        mon.open_in_browser(SIGN_IN["cvs"])
        self.assertEqual(opened, ["https://www.cvs.com/"])
