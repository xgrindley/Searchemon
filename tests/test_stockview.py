import os
import tempfile
import time
import unittest

from restock.engine import Monitor
from restock.models import StockResult, StoreStock
from restock.panel import PanelServer


class StockByStore(unittest.TestCase):
    def test_status_gives_each_store_what_the_page_needs(self):
        tmp = tempfile.mkdtemp()
        cfg = os.path.join(tmp, "config.yaml")
        open(cfg, "w").write("discord: {webhooks: {}}\nwatchlist: []\nsearches: []\ndiscovery: {enabled: false, places: false}\n")
        m = Monitor(cfg)
        st = StoreStock("7", "Target Sparks", qty=2, address="1 Main St", pickup=True, chain="target", lat=39.5, lon=-119.7)
        res = StockResult("target", "Target", "1", "Elite Trainer Box", "https://www.target.com/p/-/A-1", price=49.99,
                          online=False, online_status="", stores=[st])
        m.latest[res.key] = (time.time(), res)
        panel = PanelServer(m)
        items = panel.status()["items"]
        self.assertEqual(len(items), 1)
        sp = items[0]["store_points"][0]
        for key in ("id", "name", "area", "distance", "pickup", "low", "qty", "address", "chain", "stock", "point"):
            self.assertIn(key, sp)
        self.assertEqual((sp["qty"], sp["address"], sp["chain"], sp["pickup"]), (2, "1 Main St", "target", True))
        m.close()


if __name__ == "__main__":
    unittest.main()
