"""Walmart.io: request signing and the official-feed path (the key below is a throwaway test key)."""
import base64
import hashlib
import logging
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from restock import walmart_auth as W  # noqa: E402
from restock.config import Config, KeywordFilter  # noqa: E402
from restock.retailers.walmart import Walmart  # noqa: E402

PKCS1 = """-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEAskoX3LQL6aCcdq9k3jz6sm3xnjYYTiYpnP64wBkJ8GROP/iU
T9lQEsODxjWm/allRsyW6hKtNLTBaoFzAubpUfYBHOK66/L8QyCYzNBVXYlK9vkd
oajqYoZ2IhYvGuMD+QE+KMAKc/FyT7hH47d9aeSw0tpCXBiU8ihv8XKRozvFz29A
3eI90q8vkSny41vinU1gmIPtn+eJc2ezdF9DHlbhqgm7prPVLW60OnkKwVa1IQow
VFykkwrVpCgzA9JeoyiHcUTqTIQ/uYH8CGD04nMZzZfKmB+7ydobt0+ahz8KTvfJ
K/fWQIQtLDO4eSso1VsJ7Yk2o2bQXtJshlv03QIDAQABAoIBAAz7jLvHR5PKXIJe
+MEfHyFFlMHQzhnIuSCDwufIGvtsjm8lloUu/Z/0KUEScJfJkUSjyrx+QisTm376
MKoOLwDHIWMdVn+ueLSZp87IP+MZB4Ku9ruqHXExueH3DBSQ4d3su35Dp680Ln8E
HAYGu0TuAHtGJe1nY9czXx1tmpHQfcADmA3QTI7416C4am2g7vmNnpmwCGm/jYi2
StOqH687OPuciHtl3mlsYUUqv7rZ8jprnPRVgwEydTTzS4K6hG4cnQd74nTDzc4I
HJsPxD159vQMivWhIjT5DZi6UGGgNiby6kkFg4567g1GKIp/fNOsydb3GLEM0owg
l7EZtxECgYEA9x7XX1KrvQMub9DL9k93Cwra+L8TWPftft6OY+dRDIC2nD4WTW+T
ifT3Bik6wsAxK2iPp+zNdKn/uPXxW7WjiHJ9njqvkk59PFBuQtiIpqagQo6G6LFT
mvD2rLTI3bI6+VdcF10CZl56sgOEugNlWVF3/9XFYRoyfDGOy7zI1zECgYEAuLIa
ihi0leebieBqsTFfKDLqjwvYFJE71VN677giRUuELWX4AxRi+C2hGIHCaR+6NOCS
fck0pUjP+atwJdMjA2C3ZwB9EsHkfXHaK4TE9uAtGYWpM9wJcCqxs9HBfBngLWO/
8epvWdzVl71s9JTNzKnR7SboxcwR+nX4ao6SZW0CgYAMu9EbP1ZMIgrVhivMYGHg
9sk7whTMI9JgFDXAHh5GB6fhOy3JBbPTiwTjk2JMwLyH4RZt77zSgyQDMuEh+aUY
ldW1Po7nehXn8rkLxr6b38AoTdHT0bdeJ4Z+db5X9iQlzwOWzJsgDURDQf0n3J7v
UExfqXNHQqNRVPhntS2gMQKBgF2kj6gs1oKap1XEntOwQJrVFe/pBWmIKVoDtXUN
WvLfUujhplmJYJSMLf2K7NL37yUYJ6328eZLgIcJ0RacckgoJVTn/oIgJIUl0IP4
ERVKnBMwnZVZnr9sJiUR2JPfWrYouQ0i28ooGXOR60gmmiGGiJVBAQwoZ4Uhgw4j
sz4RAoGBALGHfPpUOjZKwmYTQtxzSThI+7ehWK7JaX4mB8hkWBYNwhi1cm7OIuJv
DBsiR1pEnGPlt4jBxdN6FTLkhpAJSqFelKUos8QmaLi3HR5HoHSEUPAkZFMiTpnk
wBX/nzMY1vtNZqtrw3aESeT2GRHcMmyyMAgKvF9pQ2O6bvTVu9bz
-----END RSA PRIVATE KEY-----"""
PKCS8 = """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQCyShfctAvpoJx2
r2TePPqybfGeNhhOJimc/rjAGQnwZE4/+JRP2VASw4PGNab9qWVGzJbqEq00tMFq
gXMC5ulR9gEc4rrr8vxDIJjM0FVdiUr2+R2hqOpihnYiFi8a4wP5AT4owApz8XJP
uEfjt31p5LDS2kJcGJTyKG/xcpGjO8XPb0Dd4j3Sry+RKfLjW+KdTWCYg+2f54lz
Z7N0X0MeVuGqCbums9UtbrQ6eQrBVrUhCjBUXKSTCtWkKDMD0l6jKIdxROpMhD+5
gfwIYPTicxnNl8qYH7vJ2hu3T5qHPwpO98kr99ZAhC0sM7h5KyjVWwntiTajZtBe
0myGW/TdAgMBAAECggEADPuMu8dHk8pcgl74wR8fIUWUwdDOGci5IIPC58ga+2yO
byWWhS79n/QpQRJwl8mRRKPKvH5CKxObfvowqg4vAMchYx1Wf654tJmnzsg/4xkH
gq72u6odcTG54fcMFJDh3ey7fkOnrzQufwQcBga7RO4Ae0Yl7Wdj1zNfHW2akdB9
wAOYDdBMjvjXoLhqbaDu+Y2embAIab+NiLZK06ofrzs4+5yIe2XeaWxhRSq/utny
Omuc9FWDATJ1NPNLgrqEbhydB3vidMPNzggcmw/EPXn29AyK9aEiNPkNmLpQYaA2
JvLqSQWDjnruDUYoin9806zJ1vcYsQzSjCCXsRm3EQKBgQD3HtdfUqu9Ay5v0Mv2
T3cLCtr4vxNY9+1+3o5j51EMgLacPhZNb5OJ9PcGKTrCwDEraI+n7M10qf+49fFb
taOIcn2eOq+STn08UG5C2IimpqBCjobosVOa8PastMjdsjr5V1wXXQJmXnqyA4S6
A2VZUXf/1cVhGjJ8MY7LvMjXMQKBgQC4shqKGLSV55uJ4GqxMV8oMuqPC9gUkTvV
U3rvuCJFS4QtZfgDFGL4LaEYgcJpH7o04JJ9yTSlSM/5q3Al0yMDYLdnAH0SweR9
cdorhMT24C0Zhakz3AlwKrGz0cF8GeAtY7/x6m9Z3NWXvWz0lM3MqdHtJujFzBH6
dfhqjpJlbQKBgAy70Rs/VkwiCtWGK8xgYeD2yTvCFMwj0mAUNcAeHkYHp+E7LckF
s9OLBOOTYkzAvIfhFm3vvNKDJAMy4SH5pRiV1bU+jud6FefyuQvGvpvfwChN0dPR
t14nhn51vlf2JCXPA5bMmyANRENB/Sfcnu9QTF+pc0dCo1FU+Ge1LaAxAoGAXaSP
qCzWgpqnVcSe07BAmtUV7+kFaYgpWgO1dQ1a8t9S6OGmWYlglIwt/Yrs0vfvJRgn
rfbx5kuAhwnRFpxySCglVOf+giAkhSXQg/gRFUqcEzCdlVmev2wmJRHYk99atii5
DSLbyigZc5HrSCaaIYaIlUEBDChnhSGDDiOzPhECgYEAsYd8+lQ6NkrCZhNC3HNJ
OEj7t6FYrslpfiYHyGRYFg3CGLVybs4i4m8MGyJHWkScY+W3iMHF03oVMuSGkAlK
oV6UpSizxCZouLcdHkegdIRQ8CRkUyJOmeTAFf+fMxjW+01mq2vDdoRJ5PYZEdwy
bLIwCAq8X2lDY7pu9NW71vM=
-----END PRIVATE KEY-----"""


class Resp:
    def __init__(self, status, body):
        self.status_code, self.body, self.text = status, body, str(body)

    def json(self):
        if self.body is None:
            raise ValueError
        return self.body


def verify(sig: bytes, msg: bytes, n: int) -> bool:
    size = (n.bit_length() + 7) // 8
    em = pow(int.from_bytes(sig, "big"), 65537, n).to_bytes(size, "big")
    digest_info = W._SHA256_PREFIX + hashlib.sha256(msg).digest()
    return em == b"\x00\x01" + b"\xff" * (size - len(digest_info) - 3) + b"\x00" + digest_info


class AuthTests(unittest.TestCase):
    def test_signature_verifies_for_both_key_formats(self):
        for pem in (PKCS1, PKCS8):
            key = W.parse_private_key(pem)
            h = W.headers("consumer-1", "1", key, 1700000000000)
            self.assertEqual(h["WM_CONSUMER.ID"], "consumer-1")
            self.assertEqual(h["WM_CONSUMER.INTIMESTAMP"], "1700000000000")
            self.assertEqual(h["WM_SEC.KEY_VERSION"], "1")
            self.assertTrue(verify(base64.b64decode(h["WM_SEC.AUTH_SIGNATURE"]),
                                   b"consumer-1\n1700000000000\n1\n", key[0]))
            self.assertFalse(verify(base64.b64decode(h["WM_SEC.AUTH_SIGNATURE"]), b"other", key[0]))

    def test_bad_keys_give_readable_errors(self):
        for bad, word in (("hello", "PEM"), ("-----BEGIN ENCRYPTED PRIVATE KEY-----\nAAAA\n-----END ENCRYPTED PRIVATE KEY-----", "password"),
                          ("-----BEGIN RSA PRIVATE KEY-----\nAAAA\n-----END RSA PRIVATE KEY-----", "read")):
            with self.assertRaises(W.KeyError_) as cm:
                W.parse_private_key(bad)
            self.assertIn(word, str(cm.exception))


ITEMS = {"items": [
    {"itemId": 111, "name": "Pokemon ETB", "salePrice": 49.94, "upc": "820650858004", "stock": "Available",
     "availableOnline": True, "offerType": "ONLINE_AND_STORE", "marketplace": False, "mediumImage": "https://i/x.jpg"},
    {"itemId": 222, "name": "Pokemon Tin", "salePrice": 24.99, "stock": "Not available", "availableOnline": False},
    {"itemId": 333, "name": "Third party", "salePrice": 99, "stock": "Available", "availableOnline": True, "marketplace": True},
]}


class ApiTests(unittest.TestCase):
    def make(self, keyfile=True, extra=None):
        d = tempfile.mkdtemp()
        kp = os.path.join(d, "private.pem")
        open(kp, "w").write(PKCS8)
        rc = {"enabled": True, "consumer_id": "cid", "private_key_file": kp if keyfile else "", "key_version": "1",
              "publisher_id": "pub9"}
        rc.update(extra or {})
        cfg = Config(path=os.path.join(d, "config.yaml"), raw={"retailers": {"walmart": rc}, "settings": {"link_delay_seconds": 0}},
                     watchlist=[], searches=[], keywords=KeywordFilter(), price_rules=[], areas=[])
        w = Walmart(cfg, logging.getLogger("wm"))
        w.pause = lambda s: None
        return w

    def test_stock_comes_from_the_official_feed_and_site_is_not_touched(self):
        w = self.make()
        seen = {}

        def get(url, params=None, headers=None, timeout=0):
            seen.update(url=url, params=params, headers=headers)
            return Resp(200, ITEMS)
        w.session.get = get
        w._next_data = lambda url: self.fail("website must not be used when the feed answers")
        out = w.check_ids(["111", "222", "333"], False)
        self.assertTrue(out["111"].online)
        self.assertEqual(out["111"].price, 49.94)
        self.assertEqual(out["111"].online_status, "Available")
        self.assertEqual(out["111"].third_party, False)
        self.assertFalse(out["222"].online)
        self.assertTrue(out["333"].third_party)
        self.assertEqual(seen["params"], {"ids": "111,222,333", "publisherId": "pub9"})
        self.assertEqual(set(seen["headers"]), {"WM_SEC.AUTH_SIGNATURE", "WM_CONSUMER.INTIMESTAMP", "WM_CONSUMER.ID", "WM_SEC.KEY_VERSION"})
        self.assertNotIn("private", seen["url"])

    def test_missing_items_fall_back_to_the_website(self):
        w = self.make()
        w.session.get = lambda *a, **k: Resp(200, {"items": [ITEMS["items"][0]]})
        pages = []
        w._next_data = lambda url: pages.append(url) or {}
        out = w.check_ids(["111", "999"], False)
        self.assertIn("111", out)
        self.assertEqual(pages, ["https://www.walmart.com/ip/999"])

    def test_refused_signature_turns_the_feed_off_for_a_while_and_uses_the_website(self):
        w = self.make()
        calls = []
        w.session.get = lambda *a, **k: calls.append(1) or Resp(401, {"error": "bad"})
        pages = []
        w._next_data = lambda url: pages.append(url) or {}
        w.check_ids(["111"], False)
        w.check_ids(["111"], False)
        self.assertEqual(len(calls), 1)              # not retried every cycle
        self.assertEqual(len(pages), 2)

    def test_unreadable_answer_is_saved_and_site_is_used(self):
        w = self.make()
        w.session.get = lambda *a, **k: Resp(200, {"unexpected": "shape"})
        pages = []
        w._next_data = lambda url: pages.append(url) or {}
        w.check_ids(["111"], False)
        self.assertEqual(len(pages), 1)
        self.assertTrue(any(f.startswith("walmart_api_items") for f in os.listdir(os.path.join(w.cfg.data_dir, "debug"))))

    def test_no_keys_means_website_only(self):
        w = self.make(keyfile=False)
        w.session.get = lambda *a, **k: self.fail("no feed call without keys")
        w._next_data = lambda url: {}
        self.assertEqual(w.check_ids(["111"], False), {})

    def test_unreadable_key_file_falls_back(self):
        w = self.make(extra={"private_key_file": "C:/nope/missing.pem"})
        w.session.get = lambda *a, **k: self.fail("must not call without a usable key")
        pages = []
        w._next_data = lambda url: pages.append(url) or {}
        w.check_ids(["111"], False)
        self.assertEqual(len(pages), 1)

    def test_upc_lookup_uses_the_feed(self):
        w = self.make()
        w.session.get = lambda url, params=None, **k: Resp(200, {"items": [ITEMS["items"][0]]}) if params.get("upc") else self.fail("x")
        self.assertEqual(w.resolve_upc("820650858004"), "111")


if __name__ == "__main__":
    unittest.main()
