"""Browser-mode tests against a local fake store with simulated bot checks.

Needs Playwright and a browser:  python -m playwright install chromium
Skipped automatically when those are missing.
"""
import logging
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from restock.retailers.blocks import classify  # noqa: E402

PRODUCT = """<html><head><title>Fake ETB</title><script type="application/ld+json">
{"@type":"Product","name":"Fake Elite Trainer Box","offers":{"@type":"Offer","price":"49.99",
"availability":"https://schema.org/InStock"}}</script></head><body>Add to cart</body></html>"""

JS_CHECK = """<html><head><title>Just a moment...</title>
<script src="/cdn-cgi/challenge-platform/h/b/orchestrate/jsch/v1"></script></head><body>
<script>setTimeout(function(){document.cookie="cleared=1; path=/"; location.reload();}, 1500);</script>
Checking your browser</body></html>"""

# A check a person can pass (PerimeterX's press-and-hold is not one: it fails in automated browsers, see blocks.py).
CAPTCHA = """<html><head><title>Robot or human?</title></head><body><div id="captcha">Verify you are human: tick the box</div>
<script>setInterval(function(){fetch('/solved').then(r=>r.text()).then(t=>{ if(t==='yes'){
document.cookie="human=1; path=/"; location.reload(); }});}, 500);</script></body></html>"""

STATE = {"solved": False}


class FakeStore(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        cookies = self.headers.get("Cookie") or ""
        if self.path == "/solved":
            return self._send(200, "yes" if STATE["solved"] else "no")
        if self.path.startswith("/ok"):
            return self._send(200, PRODUCT)
        if self.path.startswith("/js"):
            return self._send(200 if "cleared=1" in cookies else 503, PRODUCT if "cleared=1" in cookies else JS_CHECK)
        if self.path.startswith("/captcha"):
            return self._send(200, PRODUCT) if "human=1" in cookies else self._send(403, CAPTCHA)
        self._send(404, "nope")


def browser_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            pw.chromium.launch().close()
        return True
    except Exception:
        return False


class ClassifyTests(unittest.TestCase):
    def test_vendors(self):
        self.assertEqual(classify(403, CAPTCHA).vendor, "Generic")
        self.assertTrue(classify(403, CAPTCHA).needs_human)
        px = classify(200, "<div id='px-captcha'>Press &amp; Hold</div>")
        self.assertEqual((px.vendor, px.kind, px.needs_human, px.retry_after), ("PerimeterX", "challenge", False, 3600))
        self.assertEqual(classify(503, JS_CHECK).vendor, "Cloudflare")
        self.assertFalse(classify(503, JS_CHECK).needs_human)
        self.assertEqual(classify(429, "").kind, "rate_limit")
        self.assertIsNone(classify(200, PRODUCT))
        # A normal product page that mentions "access denied" in a review is not a block.
        self.assertIsNone(classify(200, PRODUCT + "<p>access denied to my card collection lol</p>"))


@unittest.skipUnless(browser_available(), "Playwright browser not installed")
class BrowserModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeStore)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        from restock.config import load_config
        self.dir = tempfile.mkdtemp()
        path = os.path.join(self.dir, "config.yaml")
        with open(path, "w") as fh:
            headless = "false" if os.environ.get("HEADED") else "true"   # HEADED=1 shows the window
            fh.write(f"browser: {{channel: chromium, headless: {headless}}}\n"
                     "retailers: {web: {enabled: true, fetch_mode: auto}}\n")
        self.cfg = load_config(path)
        self.events = []

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_auto_mode_flow(self):
        from restock.retailers.base import Blocked
        from restock.retailers.browser import BrowserWorker
        from restock.retailers.pages import WebPage

        log = logging.getLogger("restock-test")
        worker = BrowserWorker(self.cfg.raw, self.cfg.data_dir, log,
                               on_human=lambda d, u, i: self.events.append(("human", d, i.vendor)),
                               on_verified=lambda d: self.events.append(("verified", d)))
        web = WebPage(self.cfg, log, worker)
        web.session.trust_env = False   # talk to the local fake store directly
        web.pause = lambda s: None
        try:
            # 1. Plain page: direct request, no browser started.
            r = web.check_ids([self.base + "/ok/1"], False)[self.base + "/ok/1"]
            self.assertTrue(r.online)
            self.assertEqual(web.last_via, "direct")
            self.assertIsNone(worker.thread)

            # 2. JavaScript check: direct is refused, browser takes over and the check clears itself.
            r = web.check_ids([self.base + "/js/1"], False)[self.base + "/js/1"]
            self.assertTrue(r.online, r)
            self.assertEqual(web.last_via, "browser")
            self.assertTrue(web.using_browser())

            # 3. Press-and-hold check: the app asks for a person and waits without reloading.
            with self.assertRaises(Blocked) as ctx:
                web.check_ids([self.base + "/captcha/1"], False)
            self.assertTrue(ctx.exception.waiting_for_human)
            self.assertEqual(self.events[0][0], "human")
            self.assertEqual(self.events[0][2], "Generic")
            with self.assertRaises(Blocked):
                web.check_ids([self.base + "/captcha/1"], False)   # still waiting, nothing new loaded

            # The person solves it.
            STATE["solved"] = True
            time.sleep(2.5)
            r = web.check_ids([self.base + "/captcha/1"], False)[self.base + "/captcha/1"]
            self.assertTrue(r.online)
            self.assertIn(("verified", "127.0.0.1:" + self.base.rsplit(":", 1)[1]), self.events)
        finally:
            worker.stop()


if __name__ == "__main__":
    unittest.main()
