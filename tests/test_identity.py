"""v5.0: rotating User-Agents, proxies, the VPN reconnect command and the CAPTCHA service. All offline."""
import logging
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from restock import captcha as cap  # noqa: E402
from restock import network as net  # noqa: E402
from restock.config import load_config  # noqa: E402
from restock.engine import Monitor  # noqa: E402
from restock.retailers import base  # noqa: E402
from restock.retailers.browser import FetchResult  # noqa: E402
from restock.sessions import BlockTracker  # noqa: E402
from restock.trials import BY_KEY, IDENTITY, INTRODUCED, TrialPlan  # noqa: E402

LOG = logging.getLogger("identity")
CFG = ("discord: {webhooks: {default: ''}}\nsettings: {windows_toast: false}\n"
       "discovery: {enabled: false, places: false}\nbrowser: {enabled: false}\n")


class Tmp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "config.yaml")
        with open(self.path, "w") as fh:
            fh.write(CFG)

    def tearDown(self):
        for h in list(logging.getLogger("restock").handlers):
            h.close()
            logging.getLogger("restock").removeHandler(h)
        shutil.rmtree(self.dir, ignore_errors=True)


class ProxyTests(unittest.TestCase):
    def test_proxy_forms(self):
        self.assertEqual(net.normalize_proxy("1.2.3.4:8080"), "http://1.2.3.4:8080")
        self.assertEqual(net.normalize_proxy("1.2.3.4:8080:bob:p@ss"), "http://bob:p%40ss@1.2.3.4:8080")
        self.assertEqual(net.normalize_proxy("socks5://us.vpn.example:1080"), "socks5://us.vpn.example:1080")
        for bad in ("", "# note", "ftp://x:21", "justahost", "http://nohost"):
            self.assertEqual(net.normalize_proxy(bad), "", bad)
        self.assertEqual(net.label("http://bob:secret@1.2.3.4:8080"), "http://1.2.3.4:8080 (bob)")
        self.assertEqual(net.playwright_proxy("http://bob:p%40ss@1.2.3.4:8080"),
                         {"server": "http://1.2.3.4:8080", "username": "bob", "password": "p@ss"})

    def test_pool_rotates_and_rests_a_blocked_proxy_per_store(self):
        pool = net.ProxyPool({"network": {"proxies": ["1.1.1.1:80", "2.2.2.2:80", "1.1.1.1:80"]}})
        self.assertEqual(len(pool.all()), 2)                                  # duplicates dropped
        a, b = pool.pick("cvs"), pool.pick("cvs")
        self.assertNotEqual(a, b)
        pool.note(a, "cvs", False)
        self.assertEqual({pool.pick("cvs") for _ in range(4)}, {b})          # a rests at CVS...
        self.assertIn(a, {pool.pick("target") for _ in range(4)})            # ...not at Target
        pool.note(b, "cvs", False)
        self.assertEqual(pool.pick("cvs"), "")
        self.assertEqual(pool.view()[0]["blocks"], 1)

    def test_user_agents(self):
        self.assertEqual(net.user_agents({}), net.USER_AGENTS)
        self.assertEqual(net.user_agents({"network": {"user_agents": ["X/1"]}}), ["X/1"])


class FakeShop(base.Retailer):
    name = "fakeshop"
    display = "Fake Shop"


class ArmTests(Tmp):
    def shop(self, extra=""):
        with open(self.path, "a") as fh:
            fh.write(extra)
        return FakeShop(load_config(self.path), LOG)

    def test_each_check_is_a_different_browser_with_its_own_cookies(self):
        r = self.shop("network: {user_agents: ['UA-1', 'UA-2']}\n")
        seen = {}
        def fake_get(sess):
            def get(url, **kw):
                seen.setdefault(sess.headers["User-Agent"], set()).add(id(sess))
                return mock.Mock(status_code=200, text="ok", headers={}, url=url)
            return get
        orig = r._identity_session
        r._identity_session = lambda key, ua: (lambda s: (setattr(s, "get", fake_get(s)), s)[1])(orig(key, ua))
        for _ in range(20):
            r._ua_get("https://x.test/p")
        self.assertEqual(set(seen), {"UA-1", "UA-2"})
        self.assertEqual(len(r._identities), 2)

    def test_proxy_method_needs_proxies_then_uses_them(self):
        r = self.shop()
        plan = mock.Mock()
        with mock.patch.object(base, "TRIALS", plan), mock.patch.object(base, "PROXIES", net.ProxyPool(r.cfg.raw)):
            self.assertIsNone(r._run_arm(BY_KEY["direct-proxy"], "https://x.test/p"))
            self.assertIn("add proxies", plan.mark_unavailable.call_args.args[1])
        r = self.shop("network: {proxies: ['9.9.9.9:3128']}\n")
        pool = net.ProxyPool(r.cfg.raw)
        calls = []
        def get(url, **kw):
            calls.append(kw.get("proxies"))
            return mock.Mock(status_code=403, text="<title>Access Denied</title>", headers={"Server": "AkamaiGHost"}, url=url)
        with mock.patch.object(base, "TRIALS", mock.Mock()), mock.patch.object(base, "PROXIES", pool), \
                mock.patch.object(base.time, "sleep"), mock.patch("requests.Session.get", side_effect=get):
            self.assertIsNone(r._run_arm(BY_KEY["direct-proxy"], "https://x.test/p"))
        self.assertEqual(calls[0], {"http": "http://9.9.9.9:3128", "https": "http://9.9.9.9:3128"})
        self.assertEqual(pool.pick("fakeshop"), "")                           # blocked: resting at this store

    def test_proxy_browser_uses_its_own_profile(self):
        r = self.shop("network: {proxies: ['9.9.9.9:3128']}\n")
        r.browser = mock.Mock(usable=True)
        r.browser.fetch.return_value = FetchResult(200, "<h1>x</h1>", "u", None)
        with mock.patch.object(base, "TRIALS", mock.Mock()), mock.patch.object(base, "PROXIES", net.ProxyPool(r.cfg.raw)):
            self.assertIsNotNone(r._browser_arm(BY_KEY["browser-proxy"], "https://x.test/p"))
        r.browser.proxy_worker.assert_called_once_with("http://9.9.9.9:3128")
        self.assertEqual(r.browser.fetch.call_args.kwargs.get("pick"), "proxy")

    def test_new_methods_are_listed_and_introduced(self):
        for key in ("direct-ua", "direct-proxy", "browser-proxy"):
            self.assertEqual(BY_KEY[key].group, IDENTITY)
            self.assertEqual(INTRODUCED[key], "5.0")
        p = TrialPlan({"trials": {"enabled": True}}, self.dir, LOG, BlockTracker(self.dir))
        p.mark_unavailable("direct-proxy", "add proxies first")
        p.attach({"trials": {"enabled": True}})                               # settings saved (proxies may be new)
        self.assertNotIn("direct-proxy", p.unavailable)


class VpnTests(Tmp):
    def test_runs_after_enough_blocks_and_not_too_often(self):
        raw = {"network": {"vpn_reconnect_command": f'"{sys.executable}" -c "print(1)"', "vpn_after_blocks": 2}}
        v = net.VpnSwitch(raw, LOG)
        with mock.patch.object(net.time, "sleep"):
            self.assertFalse(v.maybe("CVS", 1))
            self.assertTrue(v.maybe("CVS", 2))
            self.assertFalse(v.maybe("CVS", 5))                               # within 30 minutes of the last one
        self.assertEqual((v.runs, v.view()["set"]), (1, True))
        self.assertFalse(net.VpnSwitch({}, LOG).maybe("CVS", 9))

    def test_the_panel_cannot_set_the_command(self):
        with open(self.path, "a") as fh:
            fh.write("network: {vpn_reconnect_command: 'mullvad reconnect'}\n")
        mon = Monitor(self.path)
        try:
            raw = dict(mon.cfg.raw)
            raw["network"] = {"vpn_reconnect_command": "calc.exe", "proxies": ["1.2.3.4:80"]}
            with mock.patch.object(mon, "request_reload"):
                mon.save_settings(raw)
            saved = load_config(self.path).raw["network"]
            self.assertEqual(saved["vpn_reconnect_command"], "mullvad reconnect")
            self.assertEqual(saved["proxies"], ["1.2.3.4:80"])
        finally:
            mon.close()


class FakePage:
    def __init__(self, found, after="<h1>Product</h1>"):
        self.found, self.after, self.url, self.injected = found, after, "https://www.cvs.com/shop/x", None

    def evaluate(self, js, arg=None):
        if js is cap.DETECT_JS:
            return self.found
        self.injected = arg
        return "submitted"

    def wait_for_load_state(self, *a, **k):
        pass

    def wait_for_timeout(self, *a):
        pass


class CaptchaTests(Tmp):
    def solver(self, **c):
        raw = {"captcha": {"service": "2captcha", "api_key": "k", **c}}
        return cap.Solver(raw, self.dir, LOG, BlockTracker(self.dir))

    def test_task_names_per_service(self):
        f = {"kind": "recaptcha", "sitekey": "6Lc"}
        self.assertEqual(cap.task_for("2captcha", f, "u"), {"type": "RecaptchaV2TaskProxyless", "websiteURL": "u", "websiteKey": "6Lc"})
        self.assertEqual(cap.task_for("capsolver", {"kind": "turnstile", "sitekey": "0x4"}, "u")["type"], "AntiTurnstileTaskProxyLess")
        self.assertIsNone(cap.task_for("capsolver", {"kind": "hcaptcha", "sitekey": "a"}, "u"))
        self.assertEqual(cap.task_for("anticaptcha", {"kind": "image"}, "u", "QUJD"), {"type": "ImageToTextTask", "body": "QUJD"})
        self.assertEqual(cap.answer_from({"token": "t"}), "t")
        self.assertEqual(cap.answer_from({"text": "AB12"}), "AB12")

    def test_off_until_set_up_and_within_budget_and_sites(self):
        self.assertFalse(cap.Solver({}, self.dir, LOG).allowed("cvs.com")[0])
        self.assertFalse(cap.Solver({"captcha": {"service": "2captcha"}}, self.dir, LOG).allowed("cvs.com")[0])   # no key
        s = self.solver(stores=["amazon.com"], max_per_day=1)
        self.assertFalse(s.allowed("cvs.com")[0])
        self.assertTrue(s.allowed("www.amazon.com")[0])
        s._count("amazon.com", True)
        self.assertIn("budget", s.allowed("amazon.com")[1])

    def test_solves_puts_the_answer_in_and_counts_it(self):
        s = self.solver()
        replies = iter([{"errorId": 0, "taskId": 7}, {"errorId": 0, "status": "processing"},
                        {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "TOKEN"}}])
        s.http.post = lambda url, json=None, timeout=None: mock.Mock(json=lambda: next(replies))
        page = FakePage({"kind": "recaptcha", "sitekey": "6Lc", "callback": "done"})
        with mock.patch.object(cap.time, "sleep"):
            self.assertTrue(s.attempt(page, "cvs.com", page.url))
        self.assertEqual(page.injected, ["recaptcha", "TOKEN", "done"])
        s.outcome("cvs.com", True)
        self.assertEqual(s.view()["sites"]["cvs.com"], {"tried": 1, "solved": 1})
        self.assertEqual(s.view()["used_today"], 1)
        rows = {(r["method"], r["site"]): r for r in s.tracker.rows()}
        self.assertIn(("captcha-2captcha", "cvs.com"), rows)

    def test_a_service_error_falls_back_to_asking_you(self):
        s = self.solver()
        s.http.post = lambda url, json=None, timeout=None: mock.Mock(json=lambda: {"errorId": 1, "errorCode": "ERROR_ZERO_BALANCE"})
        page = FakePage({"kind": "turnstile", "sitekey": "0x4AAA"})
        self.assertFalse(s.attempt(page, "cvs.com", page.url))
        self.assertIsNone(page.injected)
        self.assertEqual(s.view()["sites"]["cvs.com"], {"tried": 1, "solved": 0})
        self.assertFalse(s.attempt(FakePage(None), "cvs.com", "u"))           # nothing a service can answer

    def test_the_engine_installs_it(self):
        with open(self.path, "a") as fh:
            fh.write("captcha: {service: capsolver, api_key: abc}\n")
        mon = Monitor(self.path)
        try:
            self.assertIs(cap.SOLVER, mon.solver)
            self.assertEqual(mon.solver.service, "capsolver")
            self.assertIs(base.PROXIES, mon.proxies)
        finally:
            mon.close()


if __name__ == "__main__":
    unittest.main()
