"""Rules for the user's row list and the numbers stored in settings.json."""

import unittest

from price_widget import catalog
from price_widget.sources import TGJU_USD_ITEMS


class CatalogTests(unittest.TestCase):
    def test_catalog_is_consistent(self):
        ids = [(src, key) for src, key, *_ in catalog.CATALOG]
        self.assertEqual(len(ids), len(set(ids)))
        for item in catalog.DEFAULT_ITEMS:
            self.assertEqual(catalog.BY_ID[(item[0], item[1])], (item[2], item[3]))
        # A tgju item is shown in dollars exactly when the parser leaves it in dollars.
        for src, key, _, unit, _ in catalog.CATALOG:
            if src == "tgju":
                self.assertEqual(unit == catalog.USD, key in TGJU_USD_ITEMS, key)

    def test_clean_items_keeps_good_rows_and_labels(self):
        raw = [["nobitex", "USDTIRT", "My tether", "تومان"], ["tgju", "ons", "انس", "دلار"]]
        self.assertEqual(catalog.clean_items(raw), raw)

    def test_clean_items_drops_what_would_break_the_fetch(self):
        raw = [
            ["nobitex", "TONIRT", "تون", "تومان"],  # unknown market: 400 for every row
            ["nobitex", "BTCIRT", "بیت‌کوین", "تومان"],
            ["nobitex", "BTCIRT", "again", "تومان"],  # duplicate
            ["tgju", "some_new_key", "دلخواه", "تومان"],  # unknown tgju key is harmless
            ["other", "x", "y", "z"],
            ["tgju", "ons", "انس"],  # wrong shape
            "junk",
        ]
        self.assertEqual([i[1] for i in catalog.clean_items(raw)], ["BTCIRT", "some_new_key"])

    def test_clean_items_defaults_and_limit(self):
        self.assertEqual(catalog.clean_items(None), catalog.DEFAULT_ITEMS)
        self.assertEqual(catalog.clean_items([]), [])  # an emptied list stays empty
        many = [["tgju", f"k{i}", "x", "تومان"] for i in range(30)]
        self.assertEqual(len(catalog.clean_items(many)), catalog.MAX_ITEMS)

    def test_add_remove_move(self):
        items = [list(i) for i in catalog.DEFAULT_ITEMS[:2]]
        added = catalog.add_item(items, "nobitex", "SOLIRT")
        self.assertEqual(added[-1], ["nobitex", "SOLIRT", "سولانا", "تومان"])
        self.assertIs(catalog.add_item(added, "nobitex", "SOLIRT"), added)  # already there
        self.assertIs(catalog.add_item(items, "nobitex", "TONIRT"), items)  # not in catalog
        self.assertEqual([i[1] for i in catalog.move_item(added, 2, 0)],
                         ["SOLIRT", "USDTIRT", "price_dollar_rl"])
        self.assertEqual([i[1] for i in catalog.move_item(added, 0, 2)],
                         ["price_dollar_rl", "SOLIRT", "USDTIRT"])
        self.assertIs(catalog.move_item(added, 1, 1), added)  # dropped where it was
        self.assertIs(catalog.move_item(added, 0, 5), added)  # outside the list
        self.assertEqual([i[1] for i in catalog.remove_item(added, 0)], ["price_dollar_rl", "SOLIRT"])
        self.assertIs(catalog.remove_item(added, 9), added)
        self.assertEqual(len(items), 2)  # the input list is never changed

    def test_add_stops_at_the_limit(self):
        items = []
        for src, key, *_ in catalog.CATALOG:
            items = catalog.add_item(items, src, key)
        self.assertEqual(len(items), catalog.MAX_ITEMS)

    def test_clamp(self):
        self.assertEqual(catalog.clamp(1.2, *catalog.SCALE), 1.2)
        self.assertEqual(catalog.clamp(9, *catalog.SCALE), 1.5)
        self.assertEqual(catalog.clamp(0, *catalog.OPACITY), 0.3)
        self.assertEqual(catalog.clamp("big", *catalog.SCALE), 1.0)
        self.assertEqual(catalog.clamp(True, *catalog.SCALE), 1.0)


class SettingsTests(unittest.TestCase):
    def test_position_is_kept_by_one_edge(self):
        from price_widget.app import clean_settings

        def spot(stored):
            s = clean_settings(stored)
            return s["x"], s["anchor"], s["edge"]

        self.assertEqual(spot({"x": 10, "anchor": "top", "edge": 0}), (10, "top", 0))
        self.assertEqual(spot({"x": 10, "bottom": 500}), (10, "bottom", 500))  # file of 1 Oct 2026
        self.assertEqual(spot({"x": 10, "y": 100}), (10, "top", 100))  # older: top-left corner
        self.assertEqual(spot({"x": 10}), (None, None, None))
        self.assertEqual(spot({"x": True, "bottom": 5}), (None, None, None))
        self.assertEqual(spot({"x": 10, "anchor": "left", "edge": 5}), (None, None, None))
        self.assertNotIn("y", clean_settings({"x": 10, "y": 100}))
        fresh = clean_settings(None)
        self.assertTrue(fresh["docked"] and fresh["compact"] and fresh["background"])
        self.assertFalse(fresh["locked"])


if __name__ == "__main__":
    unittest.main()
