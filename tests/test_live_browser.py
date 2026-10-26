"""Runs the real browser code against a small local web server (skipped when Chromium is missing).

Covers the parts unit tests cannot: attaching to a browser started with DevTools open (how your own
Chrome and Edge join), page fetch GET and POST from inside a page (same-origin with cookies and
cross-origin), and the block detector on a normal Cloudflare-protected page versus a real challenge.
"""
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from restock.retailers.browser import BrowserPool, playwright_installed  # noqa: E402
from restock.sessions import BlockTracker  # noqa: E402

LOG = logging.getLogger("live")
NORMAL = ('<html><head><title>Pokemon ETB</title><script type="application/ld+json">'
          '{"@type":"Product","name":"ETB","offers":{"@type":"Offer","availability":"InStock","price":"49.99"}}'
          '</script></head><body>Add to cart<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>'
          '</body></html>')
CHALLENGE = '<html><head><title>Just a moment...</title></head><body><script>window._cf_chl_opt={a:1};</script></body></html>'


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/html", extra=None):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/":
            self._send(200, NORMAL, extra={"Set-Cookie": "session=abc; Path=/", "Server": "cloudflare"})
        elif self.path == "/challenge":
            self._send(403, CHALLENGE, extra={"Server": "cloudflare"})
        elif self.path.startswith("/api/data"):
            if "session=abc" in (self.headers.get("Cookie") or ""):
                self._send(200, json.dumps({"ok": True, "via": "cookie"}), "application/json")
            else:
                self._send(403, json.dumps({"ok": False}), "application/json")
        elif self.path.startswith("/api/cors"):
            self._send(200, json.dumps({"cors": True}), "application/json", {"Access-Control-Allow-Origin": "*"})
        else:
            self._send(404, "nope")

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
        if "session=abc" in (self.headers.get("Cookie") or ""):
            self._send(200, json.dumps({"echo": json.loads(body or "{}")}), "application/json")
        else:
            self._send(403, "{}", "application/json")


@unittest.skipUnless(playwright_installed(), "Playwright is not installed")
class LiveBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                exe = pw.chromium.executable_path
        except Exception as exc:
            raise unittest.SkipTest(f"Chromium unavailable: {exc}")
        if not exe or not os.path.exists(exe):
            raise unittest.SkipTest("Chromium is not installed")
        cls.web, cls.cors = free_port(), free_port()
        cls.servers = []
        for port in (cls.web, cls.cors):
            srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            cls.servers.append(srv)
        cls.dtp = free_port()
        cls.tmp = tempfile.mkdtemp()
        cls.proc = subprocess.Popen([exe, f"--remote-debugging-port={cls.dtp}", "--remote-debugging-address=127.0.0.1",
                                     f"--user-data-dir={cls.tmp}/prof", "--headless=new", "--no-sandbox",
                                     "--no-first-run", "about:blank"],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            try:
                socket.create_connection(("127.0.0.1", cls.dtp), 0.5).close()
                break
            except OSError:
                time.sleep(0.25)
        else:
            raise unittest.SkipTest("Chromium did not start")
        raw = {"browser": {"profiles": [{"name": "plain"}], "own_chrome_port": cls.dtp, "own_edge_port": 0,
                           "tabs_per_site": 2}, "settings": {"link_delay_seconds": 0}}
        cls.pool = BrowserPool(raw, cls.tmp, LOG, tracker=BlockTracker(cls.tmp))
        cls.pool.workers = [w for w in cls.pool.workers if getattr(w, "cdp_url", "")]
        cls.url = f"http://127.0.0.1:{cls.web}"

    @classmethod
    def tearDownClass(cls):
        try:
            cls.pool.stop()
        except Exception:
            pass
        cls.proc.terminate()
        for s in cls.servers:
            s.shutdown()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_1_attaches_to_a_browser_started_with_devtools(self):
        self.assertTrue(any(w.name == "my-chrome" and w.cdp_url.endswith(str(self.dtp)) for w in self.pool.workers))

    def test_2_normal_cloudflare_page_is_not_a_block(self):
        res = self.pool.fetch(self.url + "/")
        self.assertIsNone(res.block)
        self.assertIn("Add to cart", res.text)

    def test_3_real_challenge_page_is_a_block(self):
        res = self.pool.fetch(self.url + "/challenge")
        self.assertIsNotNone(res.block)
        self.assertEqual(res.block.kind, "challenge")

    def _reset(self):
        """Forget the pretend person-verification the challenge test left waiting."""
        self.pool.rest.clear()
        for w in self.pool.workers:
            w.pending.clear()

    def test_4_page_fetch_get_uses_the_pages_cookies(self):
        self._reset()
        res = self.pool.fetch(self.url + "/api/data", referer=self.url + "/", page_get=True)
        self.assertEqual(res.status, 200, res.text[:200])
        self.assertEqual(json.loads(res.text), {"ok": True, "via": "cookie"})

    def test_5_page_fetch_post_sends_json(self):
        self._reset()
        res = self.pool.fetch(self.url + "/api/post", post={"a": [1, 2]}, referer=self.url + "/")
        self.assertEqual(json.loads(res.text), {"echo": {"a": [1, 2]}})

    def test_6_page_fetch_cross_origin(self):
        self._reset()
        res = self.pool.fetch(f"http://127.0.0.1:{self.cors}/api/cors", referer=self.url + "/", page_get=True)
        self.assertEqual(json.loads(res.text), {"cors": True})

    def test_7_tracker_counts_page_fetch_separately(self):
        methods = {r["method"] for r in self.pool.tracker.rows()}
        self.assertIn("my-chrome+page", methods)
        self.assertIn("my-chrome", methods)

    def test_8_side_by_side_runs_every_method_for_real(self):
        from restock.compare import SideBySide
        self._reset()
        sbs = SideBySide(self.tmp, LOG, self.pool)
        out = sbs.run("local", self.url + "/")
        self.assertEqual(set(out), {"direct", "my-chrome"})
        self.assertTrue(out["direct"]["ok"] and out["my-chrome"]["ok"], out)
        self.assertEqual({r["method"] for r in sbs.rows()}, {"direct", "my-chrome"})


if __name__ == "__main__":
    unittest.main()
