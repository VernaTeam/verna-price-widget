"""Rows worked out from other rows' live prices instead of fetched. Results in TOMAN.

coin_bubble  Emami coin minus the gold in it. The coin is 8.133 g at 900/1000 and an 18k gram
             is 750/1000, so the coin holds as much gold as 8.133 * 0.9 / 0.75 = 9.76 grams of
             18k gold, priced from tgju's 18k gram.
usdt_spread  Tether on Nobitex minus the free-market dollar on tgju.
"""

from __future__ import annotations

COIN_IN_18K_GRAMS = 8.133 * 0.900 / 0.750

# The live rows each one is worked out from, as (source, key). They are fetched even when
# they are not on the widget themselves.
DEPENDS = {
    "coin_bubble": [("tgju", "sekee"), ("tgju", "geram18")],
    "usdt_spread": [("nobitex", "USDTIRT"), ("tgju", "price_dollar_rl")],
}


def _pct(value: float) -> str:
    persian = f"{abs(value):.1f}".replace(".", "٫").translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
    return f"⁦{persian}٪⁩"


def compute(key: str, quotes: dict[str, dict]) -> dict | None:
    """A quote for the derived row `key`, in the shape sources.Quote.to_dict() gives, or None
    while an input has not arrived yet. `quotes` is keyed "source:key"."""
    inputs = [quotes.get(f"{src}:{k}") for src, k in DEPENDS.get(key, [])]
    if not inputs:
        return None
    if any(q is None for q in inputs):
        return None
    if not all(q.get("ok") and q.get("price") for q in inputs):
        return {"key": key, "price": None, "change_pct": None, "source_time": "", "ok": False,
                "error": "an input is missing", "stale": False}
    stale = any(q.get("stale") for q in inputs)
    if key == "coin_bubble":
        coin, gram = inputs[0]["price"], inputs[1]["price"]
        gold = gram * COIN_IN_18K_GRAMS
        bubble = coin - gold
        pct = bubble / gold * 100
        note = f"{_pct(pct)} {'بالای' if bubble >= 0 else 'زیر'} ارزش طلا"
        when = "از سکه و طلای ۱۸"
    else:
        tether, dollar = inputs[0]["price"], inputs[1]["price"]
        bubble = tether - dollar
        pct = bubble / dollar * 100
        note = f"{_pct(pct)} {'گران‌تر' if bubble >= 0 else 'ارزان‌تر'}"
        when = "از تتر و دلار آزاد"
    return {"key": key, "price": round(bubble), "change_pct": round(pct, 2), "source_time": "",
            "ok": True, "error": "", "stale": stale, "note": note, "when": when}
