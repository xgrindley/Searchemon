"""Regression tests for the v4.1 stability pass: things that used to stop a store's checks, lose or repeat
alerts, freeze the window, or refuse to start. All offline."""
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from restock import geo, single, util  # noqa: E402
from restock.config import load_config, save_config, validate  # noqa: E402
from restock.engine import Monitor  # noqa: E402
from restock.history import _minutes, _parse_days, in_window  # noqa: E402
from restock.history_store import StoreHistory  # noqa: E402
from restock.models import StockResult, StoreStock  # noqa: E402
from restock.notify import DiscordNotifier, web_link  # noqa: E402
from restock.retailers.pages import parse_product_page  # noqa: E402
from restock.rules import decide  # noqa: E402
from restock.state import StateStore  # noqa: E402

OFF = "\n".join(f"  {r}: {{enabled: false}}" for r in (
    "bestbuy", "kroger", "walmart", "pokemoncenter", "gamestop", "costco", "samsclub", "barnesandnoble",
    "booksamillion", "amazon", "dicks", "safeway", "raleys", "walgreens", "cvs", "web"))
CFG = ("discord: {webhooks: {default: 'https://discord.com/api/webhooks/1/abc'}}\n"
       "settings: {windows_toast: false, alert_on_startup: true, confirm_restocks: false, alert_cooldown_minutes: 0}\n"
       "discovery: {enabled: false, places: false}\nbrowser: {enabled: false}\n"
       f"retailers:\n  target: {{enabled: true}}\n{OFF}\n")


def close_logs():
    for h in list(logging.getLogger("restock").handlers):
        h.close()
        logging.getLogger("restock").removeHandler(h)


class TmpDir(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        close_logs()
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, text: str, name: str = "config.yaml", encoding: str = "utf-8") -> str:
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding=encoding) as fh:
            fh.write(text)
        return path


# ---- files ---------------------------------------------------------------------------------
class FileWriteTests(TmpDir):
    def test_replace_rides_out_a_briefly_locked_file(self):
        path = os.path.join(self.dir, "x.json")
        real = os.replace
        calls = {"n": 0}

        def flaky(src, dst):
            calls["n"] += 1
            if calls["n"] < 3:
                raise PermissionError("in use by another process")   # antivirus or OneDrive, for a moment
            return real(src, dst)
        with mock.patch("restock.util.os.replace", side_effect=flaky), mock.patch("time.sleep"):
            util.atomic_write_json(path, {"a": 1})
        self.assertEqual(util.read_json(path, None), {"a": 1})
        self.assertEqual([f for f in os.listdir(self.dir) if f.endswith(".tmp")], [])

    def test_a_failed_write_leaves_no_temp_file_behind(self):
        with mock.patch("restock.util.os.replace", side_effect=PermissionError("locked")), mock.patch("time.sleep"):
            with self.assertRaises(PermissionError):
                util.atomic_write_json(os.path.join(self.dir, "y.json"), {"a": 1})
        self.assertEqual(os.listdir(self.dir), [])

    def test_store_history_saves_while_other_threads_record(self):
        h = StoreHistory(self.dir)
        stop = threading.Event()
        errors = []

        def churn(n):
            i = 0
            while not stop.is_set():
                h.record(f"store{n}-{i % 50}", i % 3 != 0, t=time.time() - (i % 500) * 3600)
                i += 1

        threads = [threading.Thread(target=churn, args=(n,)) for n in range(3)]
        for t in threads:
            t.start()
        try:
            for _ in range(40):
                try:
                    h.save()
                except Exception as exc:          # used to be "dictionary changed size during iteration"
                    errors.append(exc)
        finally:
            stop.set()
            for t in threads:
                t.join()
        self.assertEqual(errors, [])
        self.assertIsInstance(util.read_json(h.path, None), dict)


# ---- settings file -----------------------------------------------------------------------------
class ConfigTests(TmpDir):
    def test_empty_sections_keep_their_defaults(self):
        cfg = load_config(self.write("settings:\ndiscord:\nkeywords:\nretailers:\n"))
        self.assertEqual(cfg.settings["alert_cooldown_minutes"], 30)
        self.assertEqual(cfg.discord["username"], "Restock Monitor")
        self.assertTrue(cfg.retailer_cfg("target")["enabled"])

    def test_bad_numbers_fall_back_and_are_reported(self):
        cfg = load_config(self.write("settings: {alert_cooldown_minutes: abc, min_store_qty: '2', link_delay_seconds: true}\n"
                                     "retailers: {target: {interval_seconds: 90s}}\n"))
        self.assertEqual(cfg.settings["alert_cooldown_minutes"], 30)
        self.assertEqual(cfg.settings["min_store_qty"], 2)
        self.assertEqual(cfg.settings["link_delay_seconds"], 4)
        self.assertEqual(cfg.retailer_cfg("target")["interval_seconds"], 90)
        problems = " ".join(validate(cfg))
        self.assertIn("alert_cooldown_minutes", problems)
        self.assertIn("interval_seconds", problems)

    def test_notepad_byte_order_mark_is_fine(self):
        cfg = load_config(self.write("settings: {min_store_qty: 3}\n", encoding="utf-8-sig"))
        self.assertEqual(cfg.settings["min_store_qty"], 3)

    def test_a_file_that_is_not_settings_is_refused_clearly(self):
        with self.assertRaises(ValueError):
            load_config(self.write("- just\n- a list\n"))

    def test_bad_area_radius_does_not_stop_the_app(self):
        cfg = load_config(self.write("areas: [{name: Home, zip: '10001', radius_miles: far}, {name: B, zip: '10002', radius_miles: 9999}]\n"))
        self.assertEqual([a.radius for a in cfg.areas], [15.0, 250.0])

    def test_save_survives_a_locked_config_file(self):
        path = self.write(CFG)
        raw = load_config(path).raw
        raw["settings"]["min_store_qty"] = 2
        real = os.replace
        calls = {"n": 0}

        def flaky(src, dst):
            calls["n"] += 1
            if calls["n"] == 1:
                raise PermissionError("locked")
            return real(src, dst)
        with mock.patch("restock.util.os.replace", side_effect=flaky), mock.patch("time.sleep"):
            save_config(path, raw)
        self.assertEqual(load_config(path).settings["min_store_qty"], 2)


# ---- times and days -------------------------------------------------------------------------------
class ScheduleParsingTests(unittest.TestCase):
    def test_times_in_every_common_spelling(self):
        self.assertEqual(_minutes("22:00"), 1320)
        self.assertEqual(_minutes(1320), 1320)          # 22:00 typed without quotes: YAML reads it as minutes
        self.assertEqual(_minutes(22), 1320)
        self.assertEqual(_minutes("10pm"), 1320)
        self.assertEqual(_minutes("10:30 PM"), 1350)
        self.assertEqual(_minutes("12am"), 0)
        self.assertEqual(_minutes("garbage"), 0)

    def test_day_ranges_and_lists(self):
        self.assertEqual(_parse_days("mon-fri"), {0, 1, 2, 3, 4})
        self.assertEqual(_parse_days("fri-mon"), {4, 5, 6, 0})
        self.assertEqual(_parse_days("sat,sun"), {5, 6})
        self.assertEqual(_parse_days("weekend"), {5, 6})
        self.assertEqual(_parse_days("typo"), set(range(7)))

    def test_a_bad_window_never_breaks_alert_decisions(self):
        lt = time.localtime()
        self.assertFalse(in_window("not a window", lt))
        res = StockResult("target", "Target", "1", "ETB", "https://x.test", online=True,
                          stores=[StoreStock("9", "Store", distance=3.0)])
        raw = {"notify": {"quiet_hours": ["nonsense", {"start": "abc", "end": "10pm"}], "max_miles": "ten"}}
        d = decide(res, True, ("9",), raw)
        self.assertTrue(d.send)


# ---- alert state ------------------------------------------------------------------------------
class StateTests(TmpDir):
    def test_a_dead_webhook_gives_up_after_a_few_tries(self):
        st = StateStore(self.dir)
        res = StockResult("target", "Target", "1", "ETB", "u", online=True)
        gave_up = None
        for attempt in range(1, 12):
            change = st.evaluate(res, 0, True)
            self.assertTrue(change.alert)
            if not st.undo_alert(res, change, max_retries=3):
                gave_up = attempt
                break
        self.assertEqual(gave_up, 4)    # used to retry forever: each check wiped the failure count


# ---- Discord -------------------------------------------------------------------------------------
class DiscordTests(unittest.TestCase):
    def setUp(self):
        self.log = logging.getLogger("test-notify")
        self.n = DiscordNotifier({"webhooks": {"default": "https://discord.com/api/webhooks/1/a"}}, self.log)

    def test_web_link(self):
        self.assertEqual(web_link("https://www.target.com/p/-/A-1?utm_source=x"), "https://www.target.com/p/-/A-1")
        self.assertEqual(web_link("prod12345"), "")
        self.assertEqual(web_link(None), "")

    def test_alert_without_a_web_link_still_posts_and_page_ids_are_not_repeated(self):
        posts = []
        with mock.patch("restock.notify.requests.post",
                        side_effect=lambda url, json=None, timeout=None: (posts.append(json), mock.Mock(status_code=204))[1]):
            self.assertTrue(self.n.restock(StockResult("web", "Shop", "abc", "Pokemon ETB", "not-a-link", online=True), "online restock"))
            page = StockResult("gamestop", "GameStop", "https://www.gamestop.com/x/123.html", "Pokemon ETB",
                               "https://www.gamestop.com/x/123.html", online=True)
            self.assertTrue(self.n.restock(page, "online restock"))
        self.assertNotIn("url", posts[0]["embeds"][0])
        names = [f["name"] for f in posts[1]["embeds"][0]["fields"]]
        self.assertNotIn("Item ID", names)

    def test_a_network_blip_is_retried(self):
        ok = mock.Mock(status_code=204)
        with mock.patch("restock.notify.requests.post", side_effect=[requests.ConnectionError("wifi"), ok]) as post, \
                mock.patch("restock.notify.time.sleep"):
            self.assertTrue(self.n.note("hello"))
        self.assertEqual(post.call_count, 2)

    def test_a_discord_outage_is_retried_then_given_up(self):
        bad = mock.Mock(status_code=502)
        bad.json.side_effect = ValueError("not json")
        with mock.patch("restock.notify.requests.post", return_value=bad) as post, mock.patch("restock.notify.time.sleep"):
            self.assertFalse(self.n.note("hello"))
        self.assertEqual(post.call_count, 4)


# ---- the monitor ---------------------------------------------------------------------------------
class MonitorTests(TmpDir):
    def setUp(self):
        super().setUp()
        self.path = self.write(CFG)
        self.posts = []
        self.ok = True
        self.p = mock.patch("restock.notify.requests.post", side_effect=self._post)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        super().tearDown()

    def _post(self, url, json=None, timeout=None):
        self.posts.append(json)
        return mock.Mock(status_code=204 if self.ok else 500, json=mock.Mock(return_value={}))

    def res(self, pid="1"):
        return StockResult("target", "Target", pid, "Pokemon TCG Elite Trainer Box", f"https://www.target.com/p/-/A-{pid}",
                           price=49.99, online=True, online_status="In Stock")

    def test_saving_settings_does_not_resend_what_is_already_in_stock(self):
        mon = Monitor(self.path)
        mon.handle(self.res(), None, None)
        self.assertEqual(len(self.posts), 1)
        mon.reload()                          # what a settings save does
        mon.handle(self.res(), None, None)
        self.assertEqual(len(self.posts), 1)
        mon.close()

    def test_a_crash_while_sending_retries_instead_of_losing_the_alert(self):
        mon = Monitor(self.path)
        with mock.patch.object(mon.notifier, "restock", side_effect=RuntimeError("surprise")), \
                mock.patch("time.sleep"):
            mon.handle(self.res(), None, None)
        self.assertEqual(self.posts, [])
        mon.handle(self.res(), None, None)       # next check: still counts as new, so it is sent now
        self.assertEqual(len(self.posts), 1)
        mon.close()

    def test_per_store_cycle_values_do_not_leak_between_threads(self):
        mon = Monitor(self.path)
        mon._from_upc = {"main"}
        seen = {}

        def other():
            seen["start"] = set(mon._from_upc)
            mon._from_upc = {"other"}
            mon._confirms_left = 0
        t = threading.Thread(target=other)
        t.start()
        t.join()
        self.assertEqual(seen["start"], set())
        self.assertEqual(mon._from_upc, {"main"})
        self.assertEqual(mon._confirms_left, 5)
        mon.close()

    def test_a_failing_save_never_ends_a_store_loop(self):
        mon = Monitor(self.path)
        r = mon.retailers["target"]
        stop = threading.Event()
        cycles = []

        def cycle(_r):
            cycles.append(1)
            if len(cycles) >= 2:
                stop.set()
            return 0
        with mock.patch.object(mon, "run_cycle", side_effect=cycle), \
                mock.patch.object(mon.state, "save", side_effect=PermissionError("locked")), \
                mock.patch.object(mon, "_next_delay", return_value=(0.01, "")):
            t = threading.Thread(target=mon._loop, args=("target", 0, stop, threading.Event()))
            t.start()
            t.join(5)
        self.assertGreaterEqual(len(cycles), 2)
        self.assertFalse(t.is_alive())
        mon.close()
        self.assertIsNotNone(r)


# ---- control panel --------------------------------------------------------------------------------
class PanelTests(TmpDir):
    def test_pin_guessing_is_locked_out_and_errors_come_back_as_json(self):
        from restock.panel import PanelServer
        path = self.write(CFG.replace("browser: {enabled: false}", "browser: {enabled: false}\ncontrol_panel: {port: 8797, pin: '4821'}"))
        mon = Monitor(path)
        panel = PanelServer(mon)
        self.assertTrue(panel.start())
        try:
            url = panel.url + "api/status"
            for _ in range(panel.PIN_TRIES):
                self.assertEqual(requests.get(url, headers={"X-Token": "0000"}, timeout=5).status_code, 401)
            # Locked out now, even with the right PIN...
            self.assertEqual(requests.get(url, headers={"X-Token": "4821"}, timeout=5).status_code, 401)
            # ...but this PC's own session token always works.
            self.assertEqual(requests.get(url, headers={"X-Token": panel.token}, timeout=5).status_code, 200)
            with mock.patch.object(panel, "status", side_effect=RuntimeError("boom")):
                r = requests.get(url, headers={"X-Token": panel.token}, timeout=5)
            self.assertEqual(r.status_code, 500)
            self.assertIn("boom", r.json()["error"])
        finally:
            panel.stop()
            mon.close()


# ---- one copy at a time -----------------------------------------------------------------------------
class SingleInstanceTests(TmpDir):
    def test_a_second_copy_from_the_same_folder_is_refused(self):
        single.release()
        self.assertTrue(single.acquire(self.dir))
        try:
            code = (f"import sys; sys.path.insert(0, {os.path.dirname(os.path.dirname(os.path.abspath(__file__)))!r}); "
                    f"from restock import single; print(single.acquire({self.dir!r}))")
            out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30).stdout.strip()
            self.assertEqual(out, "False")
            other = tempfile.mkdtemp()
            code2 = code.replace(repr(self.dir), repr(other))
            out2 = subprocess.run([sys.executable, "-c", code2], capture_output=True, text=True, timeout=30).stdout.strip()
            self.assertEqual(out2, "True")      # a copy in another folder still runs
            shutil.rmtree(other, ignore_errors=True)
        finally:
            single.release()


# ---- odd store data -----------------------------------------------------------------------------------
class StoreDataTests(TmpDir):
    def test_product_page_with_odd_structured_data(self):
        html = ('<script type="application/ld+json">{"@type":"Product","name":{"bad":1},"gtin13":123,'
                '"offers":{"@type":"Offer","price":"4.99","availability":"InStock","seller":[{"name":"Target"}]}}</script>'
                '<title>Pokemon &amp; Co</title>')
        info = parse_product_page(html)
        self.assertEqual((info["title"], info["upc"], info["status"], info["seller"]), ("Pokemon & Co", "123", "in", "Target"))
        info = parse_product_page('<script type="application/ld+json">{"@type":"Product","name":"Pok&eacute;mon   ETB"}</script>')
        self.assertEqual(info["title"], "Pokémon ETB")

    def test_unknown_coordinates_are_not_used(self):
        self.assertIsNone(geo.place_point(0, 0))
        self.assertIsNone(geo.place_point("91", "10"))
        self.assertEqual(geo.place_point("40.7", "-74"), (40.7, -74.0))

    def test_debug_copies_never_break_a_check(self):
        from restock.retailers.base import Retailer
        cfg = load_config(self.write(CFG))
        r = Retailer(cfg, logging.getLogger("test"))
        with mock.patch("builtins.open", side_effect=PermissionError("locked")):
            r.dump("x", {"a": 1}, force=True)          # must not raise

    def test_old_debug_copies_are_trimmed(self):
        from restock.retailers import base
        folder = os.path.join(self.dir, "debug")
        os.makedirs(folder)
        old = time.time() - 30 * 86400
        for i in range(base.DEBUG_KEEP + 20):
            p = os.path.join(folder, f"f{i}.html")
            with open(p, "w") as fh:
                fh.write("x")
            if i < 5:
                os.utime(p, (old, old))
        base._last_trim = 0
        base._trim_debug(folder)
        self.assertEqual(len(os.listdir(folder)), base.DEBUG_KEEP)


class BrowserBusyTests(unittest.TestCase):
    def test_a_busy_browser_times_out_cleanly_and_drops_the_stale_job(self):
        from restock.retailers import browser as bmod
        w = bmod.BrowserWorker({"browser": {"enabled": True}}, tempfile.mkdtemp(), logging.getLogger("test"))
        busy = threading.Thread(target=time.sleep, args=(2,))
        busy.start()
        w.thread = busy                         # pretend the browser thread is running and stuck on a slow page
        with mock.patch.object(bmod, "playwright_installed", return_value=True):
            with self.assertRaises(ConnectionError):
                w._submit(lambda: "page", timeout=0.2)
        fn, fut = w.jobs.get_nowait()
        self.assertTrue(fut.cancelled())        # skipped when the browser gets to it
        busy.join()

    def test_a_browser_that_failed_to_start_is_tried_again_later(self):
        from restock.retailers import browser as bmod
        w = bmod.BrowserWorker({"browser": {"enabled": True}}, tempfile.mkdtemp(), logging.getLogger("test"))
        with mock.patch.object(bmod, "playwright_installed", return_value=True):
            w.failed, w.failed_at = "Browser could not start: Edge is updating", time.time()
            self.assertFalse(w.usable)
            w.failed_at = time.time() - w.RETRY_START_S - 1
            self.assertTrue(w.usable)


if __name__ == "__main__":
    unittest.main()
