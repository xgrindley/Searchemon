"""The status webhook: everything that is not stock goes to its own channel, and stock never does."""
import logging
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from restock.models import StockResult  # noqa: E402
from restock.notify import DiscordNotifier  # noqa: E402
from restock.retailers.base import Blocked  # noqa: E402

DEF = "https://discord.com/api/webhooks/1/default"
STA = "https://discord.com/api/webhooks/2/status"


class NotifierTests(unittest.TestCase):
    def make(self, **hooks):
        return DiscordNotifier({"webhooks": hooks, "ping_status": True, "mention_role_id": "42"}, logging.getLogger("t"))

    def test_stock_alerts_never_route_to_the_status_channel(self):
        n = self.make(default=DEF, status=STA)
        res = StockResult("cvs", "CVS", "1", "Pokemon TCG Elite Trainer Box", "https://x", online=True)
        self.assertEqual([u for u, _ in n.routes(res)], [DEF])
        only_status = self.make(status=STA)
        self.assertFalse(only_status.enabled)                          # no restock channel means no stock alerts
        self.assertEqual(only_status.routes(res), [])

    def test_status_posts_embed_there_and_pings_only_when_asked(self):
        n = self.make(default=DEF, status=STA)
        posts = []
        with mock.patch("restock.notify.requests.post", side_effect=lambda u, json=None, timeout=None: (
                posts.append((u, json)), mock.Mock(status_code=204, text=""))[1]), mock.patch("restock.notify.time.sleep"):
            self.assertTrue(n.status("Sign in needed: cvs", "gone", "signin", ping=True))
            self.assertTrue(n.status("Back to normal", "ok", "recovered", ping=False))
        self.assertEqual({u for u, _ in posts}, {STA})
        self.assertIn("<@&42>", posts[0][1]["content"])
        self.assertEqual(posts[1][1]["content"], "")
        self.assertEqual(posts[0][1]["embeds"][0]["title"], "Sign in needed: cvs")

    def test_no_status_webhook_means_nothing_is_sent(self):
        n = self.make(default=DEF)
        with mock.patch("restock.notify.requests.post") as post:
            self.assertFalse(n.status("x", "y"))
            post.assert_not_called()

    def test_test_message_covers_the_status_channel(self):
        n = self.make(default=DEF, status=STA)
        with mock.patch("restock.notify.requests.post", return_value=mock.Mock(status_code=204, text="")), \
                mock.patch("restock.notify.time.sleep"):
            self.assertEqual(n.test(), {"default": True, "status": True})


class EngineTests(unittest.TestCase):
    def make(self, extra=""):
        from restock.engine import Monitor
        tmp = tempfile.mkdtemp()
        cfg = os.path.join(tmp, "config.yaml")
        open(cfg, "w").write(f"discord: {{webhooks: {{default: '{DEF}', status: '{STA}'}}{extra}}}\n"
                             "discovery: {enabled: false, places: false}\nretailers: {target: {enabled: false}}\nwatchlist: []\nsearches: []\n")
        mon = Monitor(cfg)
        self.sent = []
        mon.notifier.status = lambda title, text, kind="info", ping=False: self.sent.append((kind, title, ping)) or True
        self.threads = []
        return mon

    def flush(self):
        time.sleep(0.2)

    def test_cooldown_kinds_and_threading(self):
        mon = self.make(", status_kinds: {recovered: false}, status_cooldown_minutes: 60")
        mon.status("human", "cvs.com", "Verification needed: cvs.com", "x", ping=True)
        mon.status("human", "cvs.com", "Verification needed: cvs.com", "x", ping=True)     # same thing, inside the cooldown
        mon.status("human", "target.com", "Verification needed: target.com", "x")
        mon.status("recovered", "cvs", "Back to normal", "x")                                # switched off in settings
        self.flush()
        self.assertEqual(sorted(t for _, t, _ in self.sent), ["Verification needed: cvs.com", "Verification needed: target.com"])
        self.assertTrue(any(p for _, _, p in self.sent))

    def test_lost_sign_in_and_auto_stop_post_status(self):
        mon = self.make()

        class FakeBrowser:
            usable = True
            workers = []
            def cookie_report(self): return {"edge": {"cvs": {"total": 0, "strong": 0, "expires": 0}}}
        mon.accounts.update({"edge": {"cvs": {"total": 5, "strong": 2, "expires": 0}}})     # was signed in
        mon.browser = FakeBrowser()
        mon.scan_accounts()
        mon.browser = None
        mon._trial_event("auto_stop", "direct-h2", "30 of 40 failed or were blocked (75%)")
        self.flush()
        kinds = sorted(k for k, _, _ in self.sent)
        self.assertEqual(kinds, ["autostop", "signin"])
        self.assertIn("Sign in needed: cvs", [t for _, t, _ in self.sent])

    def test_browser_problem_is_reported_once(self):
        mon = self.make()
        mon.browser = mock.Mock(workers=[mock.Mock(failed="Browser could not start: x", **{"name": "edge"})])
        mon._check_browser_problems()
        mon._check_browser_problems()
        self.flush()
        self.assertEqual([k for k, _, _ in self.sent], ["browser"])
        mon.browser = None

    def test_repeated_blocks_notify_then_recovery(self):
        import threading
        mon = self.make()
        r = mock.Mock(display="CVS", last_via="direct", supports_search=False, rcfg={})
        r.name = "cvs"
        mon.retailers = {"cvs": r}
        calls = {"n": 0}

        def cycle(_r):
            calls["n"] += 1
            if calls["n"] <= 3:
                raise Blocked("CVS: Access Denied", 120)
            return 2
        mon.run_cycle = cycle
        stop = threading.Event()

        class Wake:
            def wait(self, t=None):
                if calls["n"] >= 5:
                    stop.set()
                return True
            def clear(self): pass
        mon._loop("cvs", 0, stop, Wake())
        self.flush()
        titles = [t for _, t, _ in self.sent]
        self.assertEqual(sum("blocking the monitor" in t for t in titles), 1, titles)    # once, on the 3rd block in a row
        self.assertTrue(any(t.startswith("Back to normal") for t in titles), titles)


if __name__ == "__main__":
    unittest.main()
