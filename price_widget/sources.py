"""Price sources for the widget. Every price leaves here in TOMAN (the ounce in USD).

Nobitex  GET https://apiv2.nobitex.ir/market/stats  (official public API, documented at
         apidocs.nobitex.ir; one call returns all requested markets; prices in RIAL).
tgju     GET https://call2.tgju.org/ajax.json  (UNOFFICIAL: the JSON tgju.org's own pages
         load; no key, cached by tgju for 5 minutes, may change without notice). Prices in
         RIAL except the ounce (USD). Free-market dollar, gold and coin only move during
         Iranian market hours; outside them the value is the day's close.

Both need a direct (non-VPN) connection from an Iranian IP, so the system proxy is bypassed.
"""

from __future__ import annotations

import datetime as dt
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass

USER_AGENT = "VernaPriceWidget/1.0"
NOBITEX_STATS = "https://apiv2.nobitex.ir/market/stats"
TGJU_FEED = "https://call2.tgju.org/ajax.json"
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class SourceError(RuntimeError):
    pass


@dataclass
class Quote:
    key: str
    price: float | None  # toman, or USD for the ounce
    change_pct: float | None  # 24h / daily change, signed
    source_time: str  # as the source labels it (tgju: "۰۱:۴۲:۵۳" today, "۷ مهر" for a close)
    ok: bool = True
    error: str = ""
    stale: bool = False  # the market is not moving it now (closed, or no trade for an hour)

    def to_dict(self) -> dict:
        return asdict(self)


def _get(url: str, timeout: float = 15) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as exc:
        raise SourceError(str(exc)[:200]) from exc


def number(text: str | float | int | None) -> float | None:
    """'2,537,000' -> 2537000.0; empty or junk -> None."""
    if text is None:
        return None
    try:
        return float(str(text).replace(",", ""))
    except ValueError:
        return None


def parse_nobitex(body: dict, markets: list[str]) -> list[Quote]:
    if body.get("status") != "ok":
        raise SourceError(f"nobitex status {body.get('status')!r}")
    stats = body.get("stats") or {}
    now = time.strftime("%H:%M:%S")
    out = []
    for m in markets:
        s = stats.get(m.removesuffix("IRT").lower() + "-rls")
        latest = number((s or {}).get("latest"))
        if not s or not latest or s.get("isClosed"):
            out.append(Quote(m, None, None, "", ok=False, error="market closed or missing"))
            continue
        out.append(Quote(m, latest / 10, number(s.get("dayChange")), now))
    return out


def fetch_nobitex(markets: list[str]) -> list[Quote]:
    srcs = ",".join(m.removesuffix("IRT").lower() for m in markets)
    query = urllib.parse.urlencode({"srcCurrency": srcs, "dstCurrency": "rls"})
    return parse_nobitex(_get(f"{NOBITEX_STATS}?{query}"), markets)


# tgju keys the widget knows how to show, and their unit handling.
TGJU_USD_ITEMS = {"ons", "silver", "oil_brent"}  # quoted in dollars, not rial
TEHRAN = dt.timezone(dt.timedelta(hours=3, minutes=30))  # no daylight saving since 2022
LIVE_FOR = dt.timedelta(hours=1)
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def tgju_stale(label: str, now: dt.datetime | None = None) -> bool:
    """True unless tgju's time label says the price changed within the last hour.

    tgju labels a price with the time of its last change today ("۱۶:۵۹:۵۶") or, once the
    market has closed, with a date ("۹ مهر"). Outside market hours the dollar, gold and
    coin just keep the last time of the day, which is how a closed market shows up.
    """
    if ":" not in label:
        return True
    try:
        hour, minute, *rest = (int(part) for part in label.translate(_DIGITS).split(":"))
        second = rest[0] if rest else 0
    except ValueError:
        return True
    now = now or dt.datetime.now(TEHRAN)
    changed = now.replace(hour=hour, minute=minute, second=second, microsecond=0)
    return not dt.timedelta(0) <= now - changed <= LIVE_FOR


def parse_tgju(body: dict, keys: list[str], now: dt.datetime | None = None) -> list[Quote]:
    current = body.get("current")
    if not isinstance(current, dict):
        raise SourceError("tgju feed has no 'current' block")
    out = []
    for k in keys:
        item = current.get(k)
        price = number((item or {}).get("p"))
        if not item or price is None:
            out.append(Quote(k, None, None, "", ok=False, error="missing from feed"))
            continue
        pct = number(item.get("dp")) or 0.0
        if item.get("dt") == "low":  # tgju gives the size of the move and its direction apart
            pct = -abs(pct)
        label = item.get("t", "")
        out.append(Quote(k, price if k in TGJU_USD_ITEMS else price / 10, pct, label,
                         stale=tgju_stale(label, now)))
    return out


def fetch_tgju(keys: list[str]) -> list[Quote]:
    return parse_tgju(_get(TGJU_FEED), keys)
