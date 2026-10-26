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


class PhoneAccess(unittest.TestCase):
    def make(self, cp):
        tmp = tempfile.mkdtemp()
        cfg = os.path.join(tmp, "config.yaml")
        open(cfg, "w").write("discord: {webhooks: {}}\nwatchlist: []\nsearches: []\ndiscovery: {enabled: false, places: false}\n" + cp)
        return Monitor(cfg)

    def test_states_explain_what_to_do(self):
        m = self.make("control_panel: {allow_lan: false}\n")
        self.assertEqual(PanelServer(m).phone_status()["state"], "off")
        m = self.make("control_panel: {allow_lan: true, pin: '12'}\n")
        self.assertEqual(PanelServer(m).phone_status()["state"], "needs_pin")
        m = self.make("control_panel: {allow_lan: true, pin: '1234', port: 8771}\n")
        p = PanelServer(m)
        self.assertEqual(p.phone_status()["state"], "restart")       # saved, not restarted yet
        self.assertIn("-LocalPort 8771", p.phone_status()["firewall"])
        self.assertIn("-Profile Private", p.phone_status()["firewall"])

    def test_any_private_address_is_answered_but_names_and_public_addresses_are_not(self):
        from restock.panel import private_ip_literal
        for ok in ("192.168.1.20", "10.0.0.5", "172.20.1.9"):
            self.assertTrue(private_ip_literal(ok), ok)
        for bad in ("evil.example.com", "8.8.8.8", "127.0.0.1", "localhost", "192.168.1.20.evil.com", ""):
            self.assertFalse(private_ip_literal(bad), bad)

    def test_address_list_is_private_ipv4_only(self):
        from restock.panel import lan_addresses
        for a in lan_addresses():
            self.assertTrue(a.startswith(("10.", "192.168.", "172.")))
