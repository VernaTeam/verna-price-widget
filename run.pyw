"""Entry point for the price widget (double-click, or the frozen VernaPriceWidget.exe)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from price_widget.app import run  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(run())
