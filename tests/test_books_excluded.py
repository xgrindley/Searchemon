"""Pokemon books, sticker books and stationery are not card product and must never alert."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from restock.catalog import Catalog
from restock.tcg import classify

BOOKS = [
    "Pokémon Epic Sticker Collection 3rd Edition: From Kanto to Paldea, Paperback",
    "Pokemon Epic Sticker Collection: From Kanto to Paldea (Hardcover)",
    "Pokemon Collection Coloring Book",
    "Pokemon Activity Collection Box of Puzzles",
    "Pokemon Official Handbook Collection",
    "Pokemon Collection Notebook and Journal Set",
]
REAL = [
    ("Pokemon TCG Scarlet & Violet Collection Box", "collection"),
    ("Pokemon Trading Card Game Elite Trainer Box", "etb"),
    ("Pokemon TCG Tech Sticker Collection", "tech_sticker"),
    ("Pokemon TCG Booster Bundle", "booster_bundle"),
]


class BookTests(unittest.TestCase):
    def test_books_and_stickers_are_not_tcg(self):
        for title in BOOKS:
            c = classify(title, allow_non_english=True)
            self.assertFalse(c.is_tcg, title)

    def test_real_products_still_recognized(self):
        for title, key in REAL:
            c = classify(title)
            self.assertTrue(c.is_tcg, title)
            self.assertEqual(c.type_key, key, title)

    def test_saved_catalog_drops_old_book_entries(self):
        with tempfile.TemporaryDirectory() as d:
            items = {
                "samsclub:1": {"retailer": "samsclub", "title": BOOKS[0], "status": "tracking"},
                "samsclub:2": {"retailer": "samsclub", "title": "Pokemon TCG Elite Trainer Box", "status": "tracking"},
            }
            with open(os.path.join(d, "catalog.json"), "w", encoding="utf-8") as f:
                json.dump({"items": items, "runs": {}}, f)
            cat = Catalog(d)
            self.assertEqual(list(cat.items), ["samsclub:2"])
            self.assertEqual(list(Catalog(d).items), ["samsclub:2"])   # and it was saved


if __name__ == "__main__":
    unittest.main()
