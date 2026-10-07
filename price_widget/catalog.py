"""What the widget can show, and the rules for the user's own row list.

Rows are picked from this catalog rather than typed in: Nobitex answers 400 to the whole
request when a single symbol is unknown (seen with `ton` and `shib` on 2026-10-01), which
would blank every Nobitex row at once. Every entry below answered on that date.
"""

from __future__ import annotations

FIAT, CRYPTO, DERIVED = "ارز، طلا و سکه", "رمزارز", "حساب‌شده"
TOMAN, USD = "تومان", "دلار"

# (source, key, label, unit, group). Order is the order of the "add" list.
CATALOG = [
    ("tgju", "price_dollar_rl", "دلار آزاد", TOMAN, FIAT),
    ("tgju", "price_eur", "یورو", TOMAN, FIAT),
    ("tgju", "price_gbp", "پوند", TOMAN, FIAT),
    ("tgju", "price_aed", "درهم امارات", TOMAN, FIAT),
    ("tgju", "price_try", "لیر ترکیه", TOMAN, FIAT),
    ("tgju", "geram18", "طلای ۱۸ عیار (گرم)", TOMAN, FIAT),
    ("tgju", "geram24", "طلای ۲۴ عیار (گرم)", TOMAN, FIAT),
    ("tgju", "mesghal", "مثقال طلا", TOMAN, FIAT),
    ("tgju", "sekee", "سکه امامی", TOMAN, FIAT),
    ("tgju", "sekeb", "سکه بهار آزادی", TOMAN, FIAT),
    ("tgju", "nim", "نیم سکه", TOMAN, FIAT),
    ("tgju", "rob", "ربع سکه", TOMAN, FIAT),
    ("tgju", "gerami", "سکه گرمی", TOMAN, FIAT),
    ("tgju", "ons", "انس جهانی طلا", USD, FIAT),
    ("tgju", "silver", "انس نقره", USD, FIAT),
    ("tgju", "oil_brent", "نفت برنت", USD, FIAT),
    ("nobitex", "USDTIRT", "تتر", TOMAN, CRYPTO),
    ("nobitex", "BTCIRT", "بیت‌کوین", TOMAN, CRYPTO),
    ("nobitex", "ETHIRT", "اتریوم", TOMAN, CRYPTO),
    ("nobitex", "SOLIRT", "سولانا", TOMAN, CRYPTO),
    ("nobitex", "XRPIRT", "ریپل", TOMAN, CRYPTO),
    ("nobitex", "BNBIRT", "بایننس‌کوین", TOMAN, CRYPTO),
    ("nobitex", "DOGEIRT", "دوج‌کوین", TOMAN, CRYPTO),
    ("nobitex", "TRXIRT", "ترون", TOMAN, CRYPTO),
    ("nobitex", "ADAIRT", "کاردانو", TOMAN, CRYPTO),
    ("nobitex", "NOTIRT", "نات‌کوین", TOMAN, CRYPTO),
    ("nobitex", "LTCIRT", "لایت‌کوین", TOMAN, CRYPTO),
    ("nobitex", "BCHIRT", "بیت‌کوین کش", TOMAN, CRYPTO),
    ("nobitex", "DOTIRT", "پولکادات", TOMAN, CRYPTO),
    ("nobitex", "AVAXIRT", "آوالانچ", TOMAN, CRYPTO),
    ("nobitex", "LINKIRT", "چین‌لینک", TOMAN, CRYPTO),
    ("nobitex", "POLIRT", "پالیگان", TOMAN, CRYPTO),
    ("nobitex", "XAUTIRT", "تتر گلد", TOMAN, CRYPTO),
    ("nobitex", "PAXGIRT", "پکس گلد", TOMAN, CRYPTO),
    ("calc", "coin_bubble", "حباب سکه امامی", TOMAN, DERIVED),
    ("calc", "usdt_spread", "فاصله تتر و دلار", TOMAN, DERIVED),
]
SOURCES = ("nobitex", "tgju", "calc")
BY_ID = {(src, key): (label, unit) for src, key, label, unit, _ in CATALOG}

# (source, key, label, unit). Order is display order.
DEFAULT_ITEMS = [
    ["nobitex", "USDTIRT", "تتر", TOMAN],
    ["tgju", "price_dollar_rl", "دلار آزاد", TOMAN],
    ["tgju", "geram18", "طلای ۱۸ عیار (گرم)", TOMAN],
    ["tgju", "sekee", "سکه امامی", TOMAN],
    ["tgju", "ons", "انس جهانی طلا", USD],
    ["nobitex", "BTCIRT", "بیت‌کوین", TOMAN],
    ["nobitex", "ETHIRT", "اتریوم", TOMAN],
]
MAX_ITEMS = 10  # 10 rows are 660 px at 100%; more would not fit a 768 px screen
SCALE = (0.8, 1.5, 1.0)  # min, max, default
OPACITY = (0.3, 1.0, 1.0)


def clamp(value, low: float, high: float, default: float) -> float:
    """A number inside [low, high]; anything that is not a number becomes the default."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return round(min(high, max(low, float(value))), 2)


def clean_items(raw) -> list[list[str]]:
    """The stored row list made safe to fetch: known shape, no duplicates, at most MAX_ITEMS.

    A hand-edited settings.json may keep its own labels and may name tgju keys that are not
    in the catalog (a missing tgju key only blanks its own row). Unknown Nobitex markets are
    dropped, because one of them fails the request for all the others, and so are unknown
    derived rows, which have nothing to be worked out from.
    """
    if not isinstance(raw, list):
        return [list(item) for item in DEFAULT_ITEMS]
    out, seen = [], set()
    for item in raw:
        if not (isinstance(item, (list, tuple)) and len(item) == 4
                and all(isinstance(part, str) for part in item)):
            continue
        src, key = item[0], item[1]
        if src not in SOURCES or not key or (src, key) in seen:
            continue
        if src in ("nobitex", "calc") and (src, key) not in BY_ID:
            continue
        seen.add((src, key))
        out.append(list(item))
    return out[:MAX_ITEMS]


def add_item(items: list[list[str]], source: str, key: str) -> list[list[str]]:
    """A new list with the catalog entry appended; unchanged if it cannot be added."""
    known = BY_ID.get((source, key))
    if not known or len(items) >= MAX_ITEMS or any(i[0] == source and i[1] == key for i in items):
        return items
    return items + [[source, key, known[0], known[1]]]


def remove_item(items: list[list[str]], index: int) -> list[list[str]]:
    if not 0 <= index < len(items):
        return items
    return items[:index] + items[index + 1:]


def move_item(items: list[list[str]], index: int, target: int) -> list[list[str]]:
    """A new list with row `index` taken out and put back at position `target`."""
    if not (0 <= index < len(items) and 0 <= target < len(items)) or index == target:
        return items
    out = list(items)
    out.insert(target, out.pop(index))
    return out
