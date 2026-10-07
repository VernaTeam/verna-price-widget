"""Price history for the chart view. Every value leaves here in TOMAN (USD items in USD).

Nobitex  GET https://apiv2.nobitex.ir/market/udf/history?symbol=BTCIRT&resolution=60&from=&to=
         Official (TradingView UDF). Already in TOMAN for an ...IRT symbol, unlike
         /market/stats, which answers in rial. Honours from/to. Resolutions used: 5, 15, 60, 240, D.
         USDTIRT answers {"s": "no_data"} for every range (2026-10-01), so Tether is charted
         from tgju's daily series instead.
tgju     GET https://dashboard-api.tgju.org/v1/tv2/history?symbol=price_dollar_rl&resolution=60
         UNOFFICIAL, the feed behind tgju's own charts. Ignores from/to and returns the whole
         series every time: hourly since 2024 for `60` (about 250 KB), daily since the item
         began for `1D`. Some items are slow (Brent: 9 s) and some hourly series are stale
         (`ons` stopped in July 2026), so a stale hourly series falls back to the daily one.
"""

from __future__ import annotations

import time
import urllib.parse

from .sources import NOBITEX_STATS, TGJU_USD_ITEMS, SourceError, _get

NOBITEX_HISTORY = NOBITEX_STATS.replace("/market/stats", "/market/udf/history")
TGJU_HISTORY = "https://dashboard-api.tgju.org/v1/tv2/history"
HOUR, DAY = 3600, 86400
MAX_POINTS = 200

# (id, label, seconds back, resolution)
NOBITEX_RANGES = [
    ("6h", "۶ ساعت", 6 * HOUR, "5"),
    ("1d", "۲۴ ساعت", DAY, "15"),
    ("1w", "هفته", 7 * DAY, "60"),
    ("1m", "ماه", 30 * DAY, "240"),
    ("3m", "۳ ماه", 90 * DAY, "D"),
    ("1y", "سال", 365 * DAY, "D"),
]
TGJU_RANGES = [
    ("1d", "۲۴ ساعت", DAY, "60"),
    ("1w", "هفته", 7 * DAY, "60"),
    ("1m", "ماه", 30 * DAY, "60"),
    ("3m", "۳ ماه", 90 * DAY, "1D"),
    ("1y", "سال", 365 * DAY, "1D"),
    ("5y", "۵ سال", 5 * 365 * DAY, "1D"),
]
DAILY_RANGES = [(rid, label, span, "1D") for rid, label, span, _ in TGJU_RANGES if rid != "1d"]
# Items charted from another series than the one their live price comes from.
ALIASES = {("nobitex", "USDTIRT"): ("tgju", "crypto-tether-irr", DAILY_RANGES)}

_cache: dict[tuple, tuple[float, list]] = {}


def ranges_for(source: str, key: str) -> list[tuple]:
    """The chart ranges a row offers; none for a derived row, which has no history."""
    if source not in ("nobitex", "tgju"):
        return []
    if (source, key) in ALIASES:
        return ALIASES[(source, key)][2]
    return NOBITEX_RANGES if source == "nobitex" else TGJU_RANGES


def parse_udf(body: dict, divisor: float) -> list[list[float]]:
    """A TradingView UDF answer as [[unix time, close], ...], oldest first."""
    times, closes = body.get("t"), body.get("c")
    if not isinstance(times, list) or not isinstance(closes, list):
        return []
    points = []
    for t, c in zip(times, closes):
        if isinstance(t, (int, float)) and isinstance(c, (int, float)) and c > 0:
            points.append([int(t), c / divisor])
    points.sort(key=lambda p: p[0])
    return points


def window(points: list, span: float, now: float) -> list:
    """The points of the last `span` seconds, thinned to at most MAX_POINTS (last one kept)."""
    recent = [p for p in points if p[0] >= now - span]
    if len(recent) <= MAX_POINTS:
        return recent
    step = len(recent) / MAX_POINTS
    picked = [recent[int(i * step)] for i in range(MAX_POINTS)]
    if picked[-1] is not recent[-1]:
        picked.append(recent[-1])
    return picked


def _cached(cache_key: tuple, ttl: float, load) -> list:
    hit = _cache.get(cache_key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    points = load()
    _cache[cache_key] = (time.time(), points)
    return points


def _tgju_series(key: str, resolution: str) -> list:
    divisor = 1 if key in TGJU_USD_ITEMS else 10
    query = urllib.parse.urlencode({"symbol": key, "resolution": resolution})
    return _cached(("tgju", key, resolution), 300 if resolution == "60" else 3600,
                   lambda: parse_udf(_get(f"{TGJU_HISTORY}?{query}", timeout=30), divisor))


def _nobitex_series(key: str, resolution: str, span: float) -> list:
    now = int(time.time())
    query = urllib.parse.urlencode({"symbol": key, "resolution": resolution,
                                    "from": int(now - span), "to": now})
    return _cached(("nobitex", key, resolution, span), 60 if span <= DAY else 600,
                   lambda: parse_udf(_get(f"{NOBITEX_HISTORY}?{query}"), 1))


def fetch(source: str, key: str, range_id: str, live: float | None = None) -> list:
    """History for one row and one range; `live` is the current price, added as the last point.

    Raises SourceError when the source cannot be reached or the range is unknown; returns
    fewer than two points when the source simply has nothing for that range.
    """
    span_res = {rid: (span, res) for rid, _, span, res in ranges_for(source, key)}
    if range_id not in span_res:
        raise SourceError(f"unknown range {range_id!r}")
    span, resolution = span_res[range_id]
    now = time.time()
    if (source, key) in ALIASES:
        source, key = ALIASES[(source, key)][:2]
    if source == "nobitex":
        points = window(_nobitex_series(key, resolution, span), span, now)
    else:
        series = _tgju_series(key, resolution)
        if resolution == "60" and (not series or now - series[-1][0] > 3 * DAY):
            series = _tgju_series(key, "1D")  # the hourly series has stopped updating
        points = window(series, span, now)
    if live and points and now - points[-1][0] > 60:
        points = points + [[int(now), live]]
    return points
