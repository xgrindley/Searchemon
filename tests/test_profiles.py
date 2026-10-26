"""Clearing bot-check cookies and resetting a checking browser's saved profile."""
import logging
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from restock.accounts import AccountTracker  # noqa: E402
from restock.retailers.browser import BOT_COOKIE, BrowserPool, BrowserWorker, _in_domain  # noqa: E402


class FakeCtx:
    def __init__(self, cookies):
        self.jar = list(cookies)
        self.cleared_all = False

    def cookies(self):
        return list(self.jar)

    def clear_cookies(self, name=None, domain=None, path=None):
        if name is None:
            self.jar = []
            self.cleared_all = True
            return
        self.jar = [c for c in self.jar if not (c["name"] == name and c["domain"] == domain)]


def worker(tmp, name="edge", ctx=None):
    w = BrowserWorker({"browser": {}}, tmp, logging.getLogger("t"), name=name, profile_dir=os.path.join(tmp, name))
    w.ctx = ctx
    w._submit = lambda fn, timeout: fn()
    return w


class ProfileTests(unittest.TestCase):
    def test_bot_cookie_names(self):
        for n in ("_abck", "bm_sz", "ak_bmsc", "_px3", "_pxhd", "cf_clearance", "__cf_bm", "incap_ses_1_2", "datadome"):
            self.assertTrue(BOT_COOKIE.search(n), n)
        for n in ("sid", "session-id", "at_check", "login_token", "pxlogin"):
            self.assertFalse(BOT_COOKIE.search(n), n)

    def test_domain_match(self):
        self.assertTrue(_in_domain(".cvs.com", "cvs.com"))
        self.assertTrue(_in_domain("www.cvs.com", "cvs.com"))
        self.assertFalse(_in_domain(".target.com", "cvs.com"))
        self.assertTrue(_in_domain(".target.com", None))

    def test_clear_bot_cookies_keeps_logins_and_other_stores(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = FakeCtx([{"name": "_abck", "domain": ".cvs.com"}, {"name": "bm_sz", "domain": ".cvs.com"},
                           {"name": "session", "domain": ".cvs.com"}, {"name": "_abck", "domain": ".target.com"}])
            w = worker(tmp, ctx=ctx)
            self.assertEqual(w._clear_bot("cvs.com"), 2)
            self.assertEqual(sorted((c["name"], c["domain"]) for c in ctx.jar),
                             [("_abck", ".target.com"), ("session", ".cvs.com")])
            self.assertEqual(w._clear_bot(None), 1)
            self.assertEqual([c["name"] for c in ctx.jar], ["session"])

    def test_reset_deletes_the_profile_folder_and_starts_fresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = worker(tmp)
            os.makedirs(os.path.join(w.profile_dir, "Default"))
            open(os.path.join(w.profile_dir, "Default", "Cookies"), "w").write("x")
            w.pages["cvs.com"] = object()
            msg = w.reset()
            self.assertFalse(os.path.exists(w.profile_dir))
            self.assertIn("Reset", msg)
            self.assertEqual(w.pages, {})

    def test_reset_of_own_browser_clears_cookies_but_keeps_it_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = FakeCtx([{"name": "session", "domain": ".cvs.com"}])
            w = worker(tmp, name="mychrome", ctx=ctx)
            w.cdp_url = "http://127.0.0.1:9222"
            import threading
            w.thread = threading.Thread(target=time.sleep, args=(0.5,))
            w.thread.start()
            self.assertIn("Cleared every cookie", w.reset())
            self.assertTrue(ctx.cleared_all)

    def pool(self, tmp, *workers):
        p = BrowserPool.__new__(BrowserPool)
        p.workers = list(workers)
        p.rest = {}
        p._size_cache = {}
        return p

    def test_pool_reset_forgets_rest_and_reports_profiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = worker(tmp, "edge"), worker(tmp, "other")
            os.makedirs(a.profile_dir)
            p = self.pool(tmp, a, b)
            p.rest[("edge", "cvs.com")] = time.time() + 3000
            p.rest[("other", "cvs.com")] = time.time() + 3000
            info = {i["name"]: i for i in p.profiles_info()}
            self.assertEqual(info["edge"]["resting"][0]["site"], "cvs.com")
            ok, _ = p.reset_profile("edge")
            self.assertTrue(ok)
            self.assertNotIn(("edge", "cvs.com"), p.rest)
            self.assertIn(("other", "cvs.com"), p.rest)
            self.assertFalse(p.reset_profile("nope")[0])

    def test_accounts_forget_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = AccountTracker(tmp)
            t.sites = {"cvs": {"edge": {"state": "signed_in"}, "other": {"state": "signed_in"}}, "target": {"edge": {}}}
            t.forget_profile("edge")
            self.assertEqual(list(t.sites), ["cvs"])
            self.assertEqual(list(t.sites["cvs"]), ["other"])


if __name__ == "__main__":
    unittest.main()


class PanelRouteTests(unittest.TestCase):
    def test_fonts_are_served_and_profile_actions_work_over_http(self):
        import requests
        from restock.engine import Monitor
        with tempfile.TemporaryDirectory() as tmp:
            cfg = os.path.join(tmp, "config.yaml")
            open(cfg, "w").write("discord: {webhooks: {}}\nlocation: {zip: '10001', radius_miles: 25}\n"
                                 "discovery: {enabled: false, places: false}\nretailers: {target: {enabled: false}}\nwatchlist: []\nsearches: []\n")
            from restock.panel import PanelServer
            mon = Monitor(cfg)

            class FakePool:
                usable = True
                thread = None
                failed = ""
                calls = []
                def resting(self): return []
                def cookie_report(self): return {}
                def stop(self): pass
                def names(self): return ["edge"]
                def profiles_info(self): return [{"name": "edge", "kind": "app", "running": True, "mb": 12.5, "resting": [], "failed": ""}]
                def clear_bot_cookies(self, name, site=None): self.calls.append(("bot", name, site)); return True, "cleared"
                def reset_profile(self, name): self.calls.append(("reset", name)); return True, "reset done"

            mon.browser = FakePool()
            panel = PanelServer(mon)
            panel.port = 8797
            self.assertTrue(panel.start())
            s = requests.Session()
            s.trust_env = False
            try:
                hdr = {"X-Token": panel.token}
                r = s.get(panel.url + "fonts/sora.woff2")                      # no token: fonts are not private
                self.assertEqual((r.status_code, r.headers["Content-Type"]), (200, "font/woff2"))
                self.assertGreater(len(r.content), 10000)
                self.assertEqual(s.get(panel.url + "fonts/../config.yaml").status_code, 401)
                self.assertEqual(s.get(panel.url + "fonts/nope.woff2").status_code, 401)
                st = s.get(panel.url + "api/status", headers=hdr).json()
                self.assertEqual(st["browser"]["profiles"][0]["name"], "edge")
                a = s.post(panel.url + "api/action", json={"action": "profile_clear_bot", "profile": "edge", "site": "cvs.com"}, headers=hdr).json()
                self.assertEqual((a["ok"], a["message"]), (True, "cleared"))
                a = s.post(panel.url + "api/action", json={"action": "profile_reset", "profile": "edge"}, headers=hdr).json()
                self.assertEqual(a["message"], "reset done")
                self.assertEqual(mon.browser.calls, [("bot", "edge", "cvs.com"), ("reset", "edge")])
            finally:
                panel.stop()
                mon.browser = None
                mon.stop()
