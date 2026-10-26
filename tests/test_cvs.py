"""CVS: in-store-only items must not be treated as in stock online; per-store counts are kept."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from restock.retailers.pages import CVS, parse_cvs_stores  # noqa: E402

PAGE = ('<html><script type="application/ld+json">{"@type":"Product","name":"Mega Evolution Foil Booster Pack",'
        '"offers":{"@type":"Offer","availability":"https://schema.org/InStock","price":"5.99"}}</script>'
        '<body><div>Pickup In store purchase only</div><div>Out of stock 2878 OAK AVE</div>'
        '<div>Item for in store purchase only</div></body></html>')


class CvsTests(unittest.TestCase):
    def shop(self):
        s = CVS.__new__(CVS)
        s.rcfg = {}
        return s

    def test_in_store_only_page_is_not_online_stock(self):
        info = self.shop().parse(PAGE, "https://www.cvs.com/shop/x-prodid-1")
        self.assertEqual(info["status"], "out")
        self.assertTrue(info["store_only"])

    def test_normal_page_still_reads_in_stock(self):
        page = PAGE.replace("In store purchase only", "").replace("Item for in store purchase only", "Add to cart")
        info = self.shop().parse(page, "https://www.cvs.com/shop/x-prodid-1")
        self.assertEqual(info["status"], "in")
        self.assertFalse(info.get("store_only"))

    def test_store_rows_keep_count_address_and_skip_empty_stores(self):
        data = {"atgResponse": [
            {"storeId": "1", "City": "ANYTOWN", "storeAddress": "2878 OAK AVE", "Zipcode": "89434", "Qty": "0", "dt": "2.1"},
            {"storeId": "2", "City": "RENO", "storeAddress": "1 MAIN ST", "Zipcode": "89501", "Qty": "7", "dt": "9.0",
             "bopus": {"Qty": "3"}},
        ]}
        rows = parse_cvs_stores(data, "Home", 50)
        self.assertEqual([(r.name, r.qty, r.pickup) for r in rows], [("CVS Reno", 7, True)])
        self.assertEqual(rows[0].stock_text(), "7 in stock")
        self.assertEqual(rows[0].address, "1 Main St")


if __name__ == "__main__":
    unittest.main()
