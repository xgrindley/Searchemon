"""Walgreens store locator (key is optional, it adds store locations only)."""
import logging
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from restock.config import Config, KeywordFilter  # noqa: E402
from restock.geo import Area  # noqa: E402
from restock.retailers.pages import Walgreens, parse_walgreens_stores  # noqa: E402

NESTED = {"results": [
    {"store": {"storeNumber": "3459", "name": "Walgreens", "address": {"street": "100 Main St", "city": "Reno", "zip": "89502-1234"}},
     "latitude": "39.52", "longitude": "-119.80", "distance": "1.2"},
    {"store": {"storeNumber": "1111", "address": {"street": "9 Elm", "city": "Anytown", "zip": "89431"}},
     "latitude": 39.54, "longitude": -119.75},
    {"store": {"storeNumber": "2222"}},                      # no position: skipped
]}
FLAT = {"stores": [{"storeNumber": 77, "latitude": 39.5, "longitude": -119.8, "street": "1 A St", "city": "Reno", "zip": "89501"}]}


class Resp:
    def __init__(self, status, body, url="https://services.walgreens.com/api/stores/search/v2"):
        self.status_code, self.body, self.url, self.text = status, body, url, str(body)

    def json(self):
        if self.body is None:
            raise ValueError
        return self.body


class WalgreensTests(unittest.TestCase):
    def make(self, key="K123"):
        raw = {"retailers": {"walgreens": {"enabled": True, "api_key": key}}, "settings": {"link_delay_seconds": 0}}
        d = tempfile.mkdtemp()
        areas = [Area("Home", "12345", 10, 39.6, -119.7)]
        cfg = Config(path=os.path.join(d, "config.yaml"), raw=raw, watchlist=[], searches=[], keywords=KeywordFilter(),
                     price_rules=[], areas=areas)
        w = Walgreens(cfg, logging.getLogger("wag"))
        w.pause = lambda s: None
        return w, areas

    def test_parse_nested_and_flat(self):
        rows = parse_walgreens_stores(NESTED)
        self.assertEqual([r.store_id for r in rows], ["3459", "1111"])
        self.assertEqual(rows[0].zip, "89502")
        self.assertEqual(rows[0].chain, "walgreens")
        self.assertEqual(rows[0].source, "chain")
        self.assertEqual(parse_walgreens_stores(FLAT)[0].store_id, "77")
        self.assertEqual(parse_walgreens_stores({"oops": 1}), [])

    def test_no_key_means_no_lookup(self):
        w, areas = self.make(key="")
        w.session.post = lambda *a, **k: self.fail("must not call Walgreens without a key")
        self.assertEqual(w.stores_near(areas), [])

    def test_lookup_sends_key_in_body_only_and_returns_stores(self):
        w, areas = self.make()
        seen = {}

        def post(url, json=None, params=None, timeout=0):
            seen.update(url=url, body=json, params=params)
            return Resp(200, NESTED)
        w.session.post = post
        rows = w.stores_near(areas)
        self.assertEqual(len(rows), 2)
        self.assertEqual(seen["body"]["apiKey"], "K123")
        self.assertIsNone(seen["params"])
        self.assertEqual(seen["body"]["lat"], "39.60000")
        self.assertNotIn("K123", seen["url"])

    def test_retries_with_key_in_query_when_body_is_refused(self):
        w, areas = self.make()
        calls = []

        def post(url, json=None, params=None, timeout=0):
            calls.append(params)
            return Resp(401, {"error": "bad key"}) if not params else Resp(200, FLAT)
        w.session.post = post
        self.assertEqual(len(w.stores_near(areas)), 1)
        self.assertEqual(calls, [None, {"apiKey": "K123"}])

    def test_bad_answer_raises_and_saves_it(self):
        w, areas = self.make()
        w.session.post = lambda *a, **k: Resp(200, {"message": "nope"})
        with self.assertRaises(ConnectionError) as cm:
            w.stores_near(areas)
        self.assertIn("Check the API key", str(cm.exception))
        self.assertTrue(os.path.isdir(os.path.join(w.cfg.data_dir, "debug")))


if __name__ == "__main__":
    unittest.main()
