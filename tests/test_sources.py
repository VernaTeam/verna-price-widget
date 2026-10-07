"""Parsing tests with payloads copied from the live sources on 2026-09-29."""

import unittest

from price_widget.sources import SourceError, number, parse_nobitex, parse_tgju

NOBITEX = {"status": "ok", "stats": {
    "btc-rls": {"isClosed": False, "latest": "212500000000", "dayChange": "5.01"},
    "usdt-rls": {"isClosed": False, "latest": "2535400", "dayChange": "3.75"},
    "xyz-rls": {"isClosed": True, "latest": "10", "dayChange": "0"},
}}

TGJU = {"current": {
    "price_dollar_rl": {"p": "2,537,000", "d": "0", "dp": 0, "dt": "", "t": "۷ مهر"},
    "ons": {"p": "4,182.36", "d": "8.21", "dp": 0.2, "dt": "high", "t": "۰۱:۴۰:۳۷"},
    "crypto-bitcoin": {"p": "83570.31", "d": "77.3", "dp": 0.09, "dt": "low", "t": "۰۱:۴۲:۱۶"},
}}


class SourceTests(unittest.TestCase):
    def test_number(self):
        self.assertEqual(number("2,537,000"), 2537000.0)
        self.assertIsNone(number(""))
        self.assertIsNone(number(None))

    def test_nobitex_rial_to_toman(self):
        q = {x.key: x for x in parse_nobitex(NOBITEX, ["BTCIRT", "USDTIRT", "XYZIRT", "NOPEIRT"])}
        self.assertEqual(q["BTCIRT"].price, 21_250_000_000)
        self.assertEqual(q["USDTIRT"].price, 253_540)
        self.assertEqual(q["USDTIRT"].change_pct, 3.75)
        self.assertFalse(q["XYZIRT"].ok)  # closed market
        self.assertFalse(q["NOPEIRT"].ok)  # missing market

    def test_nobitex_bad_status(self):
        with self.assertRaises(SourceError):
            parse_nobitex({"status": "failed"}, ["BTCIRT"])

    def test_tgju_units_and_direction(self):
        q = {x.key: x for x in parse_tgju(TGJU, ["price_dollar_rl", "ons", "crypto-bitcoin", "gone"])}
        self.assertEqual(q["price_dollar_rl"].price, 253_700)  # rial -> toman
        self.assertEqual(q["ons"].price, 4182.36)  # USD stays USD
        self.assertEqual(q["ons"].change_pct, 0.2)
        self.assertEqual(q["crypto-bitcoin"].change_pct, -0.09)  # dt=low means down
        self.assertEqual(q["price_dollar_rl"].source_time, "۷ مهر")
        self.assertFalse(q["gone"].ok)

    def test_tgju_bad_payload(self):
        with self.assertRaises(SourceError):
            parse_tgju({"oops": 1}, ["ons"])


if __name__ == "__main__":
    unittest.main()
