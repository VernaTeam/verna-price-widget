"""Chart history: parsing, the time window, and the start-with-Windows registry value."""

import unittest
import winreg

from price_widget import history, startup
from price_widget.sources import SourceError

# Shape copied from apiv2.nobitex.ir/market/udf/history and dashboard-api.tgju.org on 2026-10-01.
UDF = {"s": "ok", "t": [1790782200, 1790778600, 1790785800], "o": [1, 2, 3],
       "c": [21379395090.0, 21340000000.0, 0], "v": [1, 1, 1]}


class HistoryTests(unittest.TestCase):
    def test_parse_udf_sorts_converts_and_skips_empty_closes(self):
        self.assertEqual(history.parse_udf(UDF, 10),
                         [[1790778600, 2134000000.0], [1790782200, 2137939509.0]])
        self.assertEqual(history.parse_udf({"s": "no_data"}, 10), [])

    def test_window_keeps_the_span_and_the_last_point(self):
        now = 1_000_000
        points = [[now - i * 60, float(i)] for i in range(1000, -1, -1)]
        recent = history.window(points, 600, now)
        self.assertEqual(recent[0][0], now - 600)
        self.assertEqual(len(recent), 11)
        thinned = history.window(points, 10 ** 9, now)
        self.assertLessEqual(len(thinned), history.MAX_POINTS + 1)
        self.assertEqual(thinned[-1], points[-1])

    def test_ranges(self):
        self.assertEqual(history.ranges_for("nobitex", "BTCIRT")[0][0], "6h")
        self.assertEqual(history.ranges_for("tgju", "sekee")[0][0], "1d")
        tether = history.ranges_for("nobitex", "USDTIRT")  # daily series only
        self.assertEqual([r[0] for r in tether], ["1w", "1m", "3m", "1y", "5y"])
        self.assertTrue(all(r[3] == "1D" for r in tether))
        with self.assertRaises(SourceError):
            history.fetch("tgju", "sekee", "nope")


class StartupTests(unittest.TestCase):
    KEY = r"Software\VernaPriceWidgetTest"  # never the real Run key

    def tearDown(self):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, self.KEY)
        except OSError:
            pass

    def test_write_and_remove(self):
        self.assertIsNone(startup.read("x", self.KEY))
        self.assertTrue(startup.set_enabled("x", True, self.KEY, '"C:\\a b\\w.exe"'))
        self.assertEqual(startup.read("x", self.KEY), '"C:\\a b\\w.exe"')
        self.assertFalse(startup.set_enabled("x", False, self.KEY))
        self.assertFalse(startup.set_enabled("x", False, self.KEY))  # removing twice is fine

    def test_source_checkout_cannot_be_registered(self):
        self.assertIsNone(startup.command())
        self.assertFalse(startup.is_enabled("x", self.KEY))
        self.assertFalse(startup.set_enabled("x", True, self.KEY))  # nothing to write


if __name__ == "__main__":
    unittest.main()
