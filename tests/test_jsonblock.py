"""A bot-check page delivered as JSON with a normal status must count as a block, not an empty search."""
import logging
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # noqa: E402

from restock.retailers.base import Blocked, Retailer  # noqa: E402

PX = ('{"appId":"PXGWPp4wUS","blockScript":"https://captcha.px-cdn.net/PXGWPp4wUS/captcha.js",'
      '"jsClientSrc":"https://client.perimeterx.net/PXGWPp4wUS/main.min.js","vid":""}')


class Shop(Retailer):
    name, display = "shop", "Shop"


def resp(status, text):
    r = requests.Response()
    r.status_code, r._content, r.headers = status, text.encode(), {}
    r.url = "https://x.test/api"
    return r


class JsonBlockTests(unittest.TestCase):
    def shop(self, answer):
        s = Shop.__new__(Shop)
        s.cfg, s.rcfg, s.log, s.browser, s.page_home = None, {}, logging.getLogger("t"), None, ""
        s.session = mock.Mock()
        s.session.get.return_value = answer
        return s

    def test_perimeterx_json_with_200_is_a_block(self):
        with self.assertRaises(Blocked):
            self.shop(resp(200, PX)).get("https://x.test/api", expect_json=True)

    def test_normal_json_still_passes(self):
        out = self.shop(resp(200, '{"data": {"search": {"products": []}}}')).get("https://x.test/api", expect_json=True)
        self.assertEqual(out.status_code, 200)


if __name__ == "__main__":
    unittest.main()
