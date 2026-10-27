"""Building trust at Akamai stores (CVS, Walgreens): stop sending what a store always refuses, treat a stalled
answer as a refusal, back off longer while a connection is flagged, and ask CVS for less. All offline.

Numbers from a real day: CVS side-by-side tests loaded with your own Chrome 20 of 20 times, plain requests 0 of 30,
and the app's own Chrome 0 of 13; Walgreens timed out 63 times without ever switching to the browser."""
import logging
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from restock.config import load_config  # noqa: E402
from restock.engine import Monitor  # noqa: E402
from restock.retailers.base import Blocked  # noqa: E402
from restock.retailers.browser import BrowserPool, FetchResult  # noqa: E402
from restock.retailers.pages import CVS, Walgreens  # noqa: E402
from restock.sessions import BlockTracker  # noqa: E402

LOG = logging.getLogger("test-trust")
CVS_RATES = {"direct": 0.0, "edge": 0.75, "chrome": 0.0, "my-chrome": 1.0}


class Worker:
    def __init__(self, name, cdp=False):
        self.name, self.usable, self.calls, self.thread, self.failed, self.on_reopen = name, True, 0, None, "", None
        self.cdp_url = "http://127.0.0.1:9222" if cdp else ""

    def waiting_domains(self):
        return []

    def fetch(self, url, timeout=120, ask=True, **kw):
        self.calls += 1
        return FetchResult(200, "ok", url, None, via=self.name, profile=self.name)


def pool(*workers):
    with tempfile.TemporaryDirectory() as d:
        p = BrowserPool({"browser": {"profiles": [{"name": "a"}], "own_chrome_port": 0, "learn_from_compare": True}}, d, LOG,
                        tracker=BlockTracker(d))
    p.workers = list(workers)
    p.prefer = lambda site: CVS_RATES if site == "cvs.com" else {}
    return p


class BrowserChoiceTests(unittest.TestCase):
    def test_a_browser_the_store_always_refuses_is_never_sent(self):
        chrome, edge = Worker("chrome"), Worker("edge")
        p = pool(chrome, edge)
        for _ in range(6):
            p.fetch("https://www.cvs.com/shop/x")
        self.assertEqual((chrome.calls, edge.calls), (0, 6))

    def test_it_waits_for_the_good_browser_instead_of_using_the_bad_one(self):
        chrome, mine = Worker("chrome"), Worker("my-chrome", cdp=True)
        p = pool(chrome, mine)
        p.rest[("my-chrome", "www.cvs.com")] = time.time() + 600       # the good one is resting
        res = p.fetch("https://www.cvs.com/shop/x")
        self.assertEqual(chrome.calls, 0)
        self.assertEqual(res.block.kind, "rate_limit")                # report "wait", do not burn the bad one

    def test_other_stores_are_unaffected(self):
        chrome, edge = Worker("chrome"), Worker("edge")
        p = pool(chrome, edge)
        for _ in range(4):
            p.fetch("https://www.gamestop.com/x")
        self.assertEqual((chrome.calls, edge.calls), (2, 2))


class Tmp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "config.yaml")
        with open(self.path, "w") as fh:
            fh.write("discord: {webhooks: {default: ''}}\nsettings: {link_delay_seconds: 0}\nbrowser: {enabled: false}\n"
                     "discovery: {enabled: false, places: false}\n")
        self.cfg = load_config(self.path)

    def tearDown(self):
        for h in list(logging.getLogger("restock").handlers):
            h.close()
            logging.getLogger("restock").removeHandler(h)
        shutil.rmtree(self.dir, ignore_errors=True)


class PlainRequestTests(Tmp):
    def test_a_store_that_refuses_plain_requests_goes_straight_to_the_browser(self):
        browser = mock.Mock(usable=True, prefer=lambda site: CVS_RATES if site == "cvs.com" else {})
        r = CVS(self.cfg, LOG, browser)
        self.assertTrue(r.using_browser())
        r.session.get = mock.Mock()
        browser.fetch.return_value = FetchResult(200, "<title>Pokemon</title>", "u", None)
        r.fetch_html("https://www.cvs.com/shop/x-prodid-1")
        r.session.get.assert_not_called()

    def test_a_stalled_answer_switches_walgreens_to_the_browser(self):
        browser = mock.Mock(usable=True, prefer=lambda site: {})
        r = Walgreens(self.cfg, LOG, browser)
        self.assertFalse(r.using_browser())
        r.session.get = mock.Mock(side_effect=requests.ReadTimeout("read timed out"))
        browser.fetch.return_value = FetchResult(200, "<title>Pokemon TCG Tin</title>", "u", None)
        res = r.fetch_html("https://www.walgreens.com/store/c/x/ID=prod1-product")
        self.assertEqual(res.status, 200)
        self.assertTrue(r.using_browser())                                # sticks for the next checks too

    def test_without_a_browser_two_stalls_in_a_row_count_as_a_block(self):
        cfg = load_config(self.path)
        cfg.raw["retailers"]["walgreens"]["fetch_mode"] = "direct"
        r = Walgreens(cfg, LOG, None)
        r.session.get = mock.Mock(side_effect=requests.ReadTimeout("read timed out"))
        with self.assertRaises(ConnectionError):
            r.fetch_html("https://www.walgreens.com/x")
        with self.assertRaises(Blocked):
            r.fetch_html("https://www.walgreens.com/x")


class SideBySideTests(Tmp):
    def test_known_bad_methods_are_retested_at_most_daily(self):
        from restock.compare import SideBySide
        p = pool(Worker("chrome"), Worker("my-chrome", cdp=True))
        sb = SideBySide(self.dir, LOG, p)
        sb.rates = lambda site: CVS_RATES
        now = time.time()
        sb.data = {"cvs": {"direct": [{"t": now - 3600, "ok": False, "kind": "denied", "ms": 1}],
                           "chrome": [{"t": now - 2 * 86400, "ok": False, "kind": "denied", "ms": 1}]}}
        with mock.patch.object(sb, "_plain", return_value=(False, "denied")) as plain, \
                mock.patch.object(sb, "_browser", return_value=(True, "")):
            out = sb.run("cvs", "https://www.cvs.com/x")
        plain.assert_not_called()                                          # refused an hour ago: skipped
        self.assertIn("chrome", out)                                       # last tried two days ago: one retest
        self.assertIn("my-chrome", out)


class BackoffTests(Tmp):
    def test_the_pause_grows_while_every_browser_keeps_being_refused(self):
        mon = Monitor(self.path)
        r = mock.Mock(display="CVS", last_via="browser", supports_search=False, rcfg={})
        r.name = "cvs"
        r.setup_needed.return_value = ""
        mon.retailers = {"cvs": r}
        pauses = []
        stop = threading.Event()

        def cycle(_r):
            raise Blocked("CVS refused the request (Akamai)", 0)

        class Wake:
            def wait(self, t=None):
                pauses.append(t)
                if len(pauses) >= 9:
                    stop.set()

            def clear(self):
                pass
        with mock.patch.object(mon, "run_cycle", side_effect=cycle), mock.patch("restock.engine.random.uniform", return_value=1.0):
            mon._loop("cvs", 0, stop, Wake())
        self.assertLessEqual(pauses[1], 1800)
        self.assertGreater(max(pauses), 2 * 3600)                         # well past the old 30 minute cap
        self.assertLessEqual(max(pauses), 3 * 3600)
        mon.close()


class CvsDietTests(Tmp):
    def test_in_store_only_items_are_not_reloaded_between_shelf_checks(self):
        r = CVS(self.cfg, LOG, None)
        r.pause = lambda s: None
        url = "https://www.cvs.com/shop/pokemon-tcg-30th-anniversary-mini-tin-prodid-662589"
        page = ('<script type="application/ld+json">{"@type":"Product","name":"Pokemon TCG 30th Anniversary Mini Tin",'
                '"offers":{"@type":"Offer","price":"9.99","availability":"InStock"}}</script>Item for in store purchase only')
        r.fetch_html = mock.Mock(return_value=FetchResult(200, page, url, None))
        r.store_stock = mock.Mock(return_value=[])
        with mock.patch.object(CVS, "in_store_enabled", return_value=True):
            first = r.check_ids([url], True)[url]
            second = r.check_ids([url], True)[url]
        self.assertEqual(r.fetch_html.call_count, 1)                       # the page was read once
        self.assertEqual(r.store_stock.call_count, 2)                      # the shelves were checked both times
        self.assertEqual((second.title, second.online_status), (first.title, "In store only"))


if __name__ == "__main__":
    unittest.main()
