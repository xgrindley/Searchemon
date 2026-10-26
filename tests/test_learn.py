import json
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

from restock import learn  # noqa: E402
from restock.retailers.browser import playwright_installed  # noqa: E402

STORES = {"stores": [{"storeId": "2201", "storeName": "GameStop Sparks", "storeQuantity": 3, "inStockAtStore": True,
                      "distance": 2.1, "authToken": "SECRET-ABC"}]}
PAGE = ("<html><body>product<script>setTimeout(function(){"
        "fetch('/api/stores?zip=89436&pid=555&radius=25&token=SECRET1');"
        "fetch('/api/theme');},1200);</script></body></html>")


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/api/stores"):
            body, ctype = json.dumps(STORES), "application/json"
        elif self.path.startswith("/api/theme"):
            body, ctype = json.dumps({"color": "red"}), "application/json"
        else:
            body, ctype = PAGE, "text/html"
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class PureTests(unittest.TestCase):
    def test_redact_url_and_json(self):
        self.assertEqual(learn.redact_url("https://x.com/a?zip=89436&token=abc&b=1#f"),
                         "https://x.com/a?zip=89436&token=REDACTED&b=1")
        out = learn.redact_json({"authToken": "x", "store": {"storeId": "1", "csrf": "y"}, "n": 3})
        self.assertEqual(out["authToken"], "REDACTED")
        self.assertEqual(out["store"], {"storeId": "1", "csrf": "REDACTED"})
        self.assertEqual(out["n"], 3)
        self.assertEqual(json.loads(learn.redact_text('{"zip":"89436","password":"p"}')),
                         {"zip": "89436", "password": "REDACTED"})
        self.assertIn("REDACTED", learn.redact_text("zip=89436&session=abc"))

    def test_interesting_filters(self):
        self.assertTrue(learn.interesting("https://www.gamestop.com/on/x", "application/json; charset=utf-8", "fetch"))
        self.assertFalse(learn.interesting("https://www.gamestop.com/a.js", "text/javascript", "script"))
        self.assertFalse(learn.interesting("https://www.google-analytics.com/c", "application/json", "xhr"))
        self.assertFalse(learn.interesting("https://x.com/a", "text/html", "xhr"))

    def test_templatize(self):
        t = learn.templatize("https://s.com/Stores-Find?postalCode=89436&radius=25&products=555:1",
                             {"zip": "89436", "pid": "555", "radius": "25"})
        self.assertEqual(t, "https://s.com/Stores-Find?postalCode={zip}&radius={radius}&products={pid}:1")
        self.assertEqual(learn.templatize("https://s.com/p/555/stores", {"pid": "555"}), "https://s.com/p/{pid}/stores")

    def test_analyze_ranks_stock_answers_first(self):
        entries = [
            {"method": "GET", "url": "https://s.com/theme", "status": 200, "post": "", "body": '{"color":"red"}'},
            {"method": "GET", "url": "https://s.com/stores?zip=89436&pid=555", "status": 200, "post": "",
             "body": json.dumps({"stores": [{"storeId": "1", "inStock": True, "quantity": 2}]})},
            {"method": "POST", "url": "https://s.com/inv", "status": 200, "post": "{}",
             "body": json.dumps({"availability": "in_stock"})},
            {"method": "GET", "url": "https://s.com/stores?zip=89436&pid=555", "status": 403, "post": "", "body": "{}"},
        ]
        out = learn.analyze(entries, {"zip": "89436", "pid": "555"})
        self.assertEqual(out[0]["template"], "https://s.com/stores?zip={zip}&pid={pid}")
        self.assertEqual(set(out[0]["echoes"]), {"zip", "pid"})
        self.assertFalse(any("theme" in c["url"] for c in out))
        self.assertEqual(out[1]["template"], "")           # POST answers are listed but not replayed

    def test_save_and_load_templates(self):
        d = tempfile.mkdtemp()
        try:
            good = learn.save_templates(d, "gamestop", [{"template": "https://s.com/a?z={zip}"}, {"template": "https://s.com/b"}, {"template": ""}])
            self.assertEqual(good, ["https://s.com/a?z={zip}"])
            self.assertEqual(learn.learned_templates(d, "gamestop"), good)
            learn.save_templates(d, "gamestop", [{"template": "https://s.com/c?p={pid}"}])
            self.assertEqual(learn.learned_templates(d, "gamestop")[0], "https://s.com/c?p={pid}")
            self.assertEqual(learn.learned_templates(d, "cvs"), [])
        finally:
            shutil.rmtree(d, ignore_errors=True)


@unittest.skipUnless(playwright_installed(), "Playwright is not installed")
class LiveLearnTests(unittest.TestCase):
    def test_records_a_real_page_and_finds_the_store_request(self):
        from playwright.sync_api import sync_playwright
        try:
            with sync_playwright() as pw:
                exe = pw.chromium.executable_path
        except Exception as exc:
            self.skipTest(f"Chromium unavailable: {exc}")
        if not exe or not os.path.exists(exe):
            self.skipTest("Chromium is not installed")

        def free():
            with socket.socket() as s:
                s.bind(("127.0.0.1", 0))
                return s.getsockname()[1]
        web, dtp, tmp = free(), free(), tempfile.mkdtemp()
        srv = ThreadingHTTPServer(("127.0.0.1", web), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        proc = subprocess.Popen([exe, f"--remote-debugging-port={dtp}", "--remote-debugging-address=127.0.0.1",
                                 f"--user-data-dir={tmp}/p", "--headless=new", "--no-sandbox", "--no-first-run",
                                 f"http://127.0.0.1:{web}/product"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(60):
                try:
                    socket.create_connection(("127.0.0.1", dtp), 0.5).close()
                    break
                except OSError:
                    time.sleep(0.25)
            else:
                self.skipTest("Chromium did not start")
            # the page was opened at launch; reload it once recording has started so its requests are seen
            import urllib.request

            def reopen():
                req = urllib.request.Request(f"http://127.0.0.1:{dtp}/json/new?http://127.0.0.1:{web}/product", method="PUT")
                urllib.request.urlopen(req, timeout=5).read()
            t = threading.Timer(1.5, reopen)
            t.start()
            entries = learn.record(dtp, 6, say=lambda *_: None)
            cands = learn.analyze(entries, {"zip": "89436", "pid": "555", "radius": "25"})
            self.assertTrue(cands, entries)
            best = cands[0]
            self.assertIn("/api/stores", best["url"])
            self.assertEqual(best["template"], f"http://127.0.0.1:{web}/api/stores?zip={{zip}}&pid={{pid}}&radius={{radius}}&token=REDACTED")
            blob = json.dumps(entries)
            self.assertNotIn("SECRET", blob)             # token in the URL and in the answer are both redacted
            self.assertIn("GameStop Sparks", blob)
        finally:
            proc.terminate()
            srv.shutdown()
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
