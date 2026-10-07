"""Derived rows, the closed-market test, and the settings for fonts, story speed and alerts."""

import datetime as dt
import unittest

from price_widget import derived
from price_widget.app import clean_settings, fa_number
from price_widget.sources import TEHRAN, parse_tgju, tgju_stale


def quote(price, ok=True, stale=False):
    return {"price": price, "ok": ok, "stale": stale}


class DerivedTests(unittest.TestCase):
    def test_coin_bubble(self):
        q = derived.compute("coin_bubble", {"tgju:sekee": quote(260_000_000),
                                            "tgju:geram18": quote(25_000_000)})
        gold = 25_000_000 * 8.133 * 0.9 / 0.75
        self.assertEqual(q["price"], round(260_000_000 - gold))
        self.assertAlmostEqual(q["change_pct"], (260_000_000 - gold) / gold * 100, places=2)
        self.assertIn("بالای", q["note"])

    def test_tether_spread_and_its_sign(self):
        q = derived.compute("usdt_spread", {"nobitex:USDTIRT": quote(257_000),
                                            "tgju:price_dollar_rl": quote(258_000, stale=True)})
        self.assertEqual(q["price"], -1000)
        self.assertIn("ارزان‌تر", q["note"])
        self.assertTrue(q["stale"])  # stale when an input is

    def test_waits_for_inputs(self):
        self.assertIsNone(derived.compute("coin_bubble", {"tgju:sekee": quote(1)}))
        self.assertFalse(derived.compute("coin_bubble", {"tgju:sekee": quote(1),
                                                         "tgju:geram18": quote(None, ok=False)})["ok"])
        self.assertIsNone(derived.compute("nope", {}))


class StaleTests(unittest.TestCase):
    NOW = dt.datetime(2026, 10, 8, 14, 0, tzinfo=TEHRAN)

    def test_labels(self):
        self.assertFalse(tgju_stale("۱۳:۳۰:۰۰", self.NOW))  # changed half an hour ago
        self.assertTrue(tgju_stale("۱۲:۵۰:۰۰", self.NOW))  # over an hour ago
        self.assertTrue(tgju_stale("۱۶:۵۹:۵۶", self.NOW))  # yesterday's last change
        self.assertTrue(tgju_stale("۹ مهر", self.NOW))  # a closing date
        self.assertTrue(tgju_stale("", self.NOW))

    def test_parse_marks_it(self):
        body = {"current": {"sekee": {"p": "2,600,000,000", "dp": 1, "dt": "high", "t": "۱۳:۵۵:۰۰"}}}
        self.assertFalse(parse_tgju(body, ["sekee"], self.NOW)[0].stale)


class SettingsTests(unittest.TestCase):
    def test_font_story_and_alerts(self):
        s = clean_settings({"font": "Shabnam", "story_seconds": 99,
                            "alerts": {"tgju:sekee": {"above": 3e9, "below": -1, "x": 5},
                                       "bad": "x", "nobitex:BTCIRT": {"below": True}}})
        self.assertEqual(s["font"], "Shabnam")
        self.assertEqual(s["story_seconds"], 15)
        self.assertEqual(s["alerts"], {"tgju:sekee": {"above": 3e9}})
        fresh = clean_settings({"font": "Comic Sans"})
        self.assertEqual((fresh["font"], fresh["story_seconds"], fresh["alerts"]), ("Vazirmatn", 4, {}))

    def test_fa_number(self):
        self.assertEqual(fa_number(2585000), "۲٬۵۸۵٬۰۰۰")
        self.assertEqual(fa_number(125.5), "۱۲۵٫۵")


if __name__ == "__main__":
    unittest.main()
