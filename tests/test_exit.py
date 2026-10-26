"""Closing the app closes the browsers it opened or joined."""
import logging
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from restock import shutdown  # noqa: E402
from restock.retailers.browser import BrowserPool, playwright_installed  # noqa: E402
from restock.sessions import BlockTracker  # noqa: E402

LOG = logging.getLogger("exit")


class ShutdownHookTests(unittest.TestCase):
    def test_close_runs_once_however_it_is_triggered(self):
        calls = []
        with mock.patch("atexit.register") as reg, mock.patch("signal.signal") as sig:
            shutdown.install(lambda: calls.append(1))
            run = reg.call_args[0][0]
            handlers = {c.args[0]: c.args[1] for c in sig.call_args_list}
        run()
        run()
        self.assertEqual(calls, [1])
        self.assertTrue(handlers)                            # Ctrl+C / stop requests are covered too
        with self.assertRaises(SystemExit):
            list(handlers.values())[0](2, None)
        self.assertEqual(calls, [1])

    def test_a_failing_close_never_blocks_exit(self):
        def boom():
            raise RuntimeError("x")
        with mock.patch("atexit.register") as reg, mock.patch("signal.signal"):
            shutdown.install(boom)
            reg.call_args[0][0]()


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipUnless(playwright_installed(), "Playwright is not installed")
class OwnBrowserClosesTests(unittest.TestCase):
    def start(self, close_flag):
        from playwright.sync_api import sync_playwright
        try:
            with sync_playwright() as pw:
                exe = pw.chromium.executable_path
        except Exception as exc:
            self.skipTest(f"Chromium unavailable: {exc}")
        if not exe or not os.path.exists(exe):
            self.skipTest("Chromium is not installed")
        port, tmp = free_port(), tempfile.mkdtemp()
        proc = subprocess.Popen([exe, f"--remote-debugging-port={port}", "--remote-debugging-address=127.0.0.1",
                                 f"--user-data-dir={tmp}/p", "--headless=new", "--no-sandbox", "--no-first-run",
                                 "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            try:
                socket.create_connection(("127.0.0.1", port), 0.5).close()
                break
            except OSError:
                time.sleep(0.25)
        else:
            proc.kill()
            self.skipTest("Chromium did not start")
        raw = {"browser": {"profiles": [{"name": "plain"}], "own_chrome_port": port, "own_edge_port": 0,
                           "close_own_on_exit": close_flag}, "settings": {"link_delay_seconds": 0}}
        pool = BrowserPool(raw, tmp, LOG, tracker=BlockTracker(tmp))
        pool.workers = [w for w in pool.workers if getattr(w, "cdp_url", "")]
        self.assertTrue(pool.workers)
        # make the worker start and attach (a real fetch of a tiny data URL page)
        w = pool.workers[0]
        w._submit(lambda: None, 60)
        return pool, proc, tmp

    def test_own_browser_is_closed_with_the_app(self):
        pool, proc, tmp = self.start(True)
        try:
            pool.stop()
            for _ in range(40):
                if proc.poll() is not None:
                    break
                time.sleep(0.25)
            self.assertIsNotNone(proc.poll(), "the browser should have closed")
            self.assertTrue(pool.stopping)
        finally:
            proc.kill()
            shutil.rmtree(tmp, ignore_errors=True)

    def test_setting_off_leaves_it_open(self):
        pool, proc, tmp = self.start(False)
        try:
            pool.stop()
            time.sleep(1.5)
            self.assertIsNone(proc.poll(), "close_own_on_exit false must leave the browser open")
        finally:
            proc.kill()
            shutil.rmtree(tmp, ignore_errors=True)

    def test_nothing_joins_while_closing(self):
        pool, proc, tmp = self.start(True)
        try:
            pool.stop()
            before = len(pool.workers)
            pool._own_looked = 0
            pool._maybe_attach_own_chrome()
            self.assertEqual(len(pool.workers), before)
        finally:
            proc.kill()
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
