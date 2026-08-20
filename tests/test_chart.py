from datetime import date, timedelta

from bot.chart import CHART_BARS, build_chart_png

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def make_prices(n=150):
    """ขาขึ้นเรียบๆ จบ 2026-08-19 — most-recent-first ตาม convention repo"""
    bars, d, p = [], date(2026, 8, 19), 200.0
    while len(bars) < n:
        if d.weekday() < 5:
            bars.append({"date": d.isoformat(), "open": p, "high": p + 2,
                         "low": p - 2, "close": p + 1, "volume": 1_000_000})
            p -= 1.0
        d -= timedelta(days=1)
    return bars


def _levels(prices):
    return {"high_5d": 195.0, "high_3m": 199.0, "sl": 180.0,
            "reaction_date": prices[5]["date"]}


def test_returns_png_bytes():
    png = build_chart_png("NVDA", make_prices())
    assert png is not None
    assert png.startswith(PNG_MAGIC)
    assert len(png) > 10_000        # ภาพจริง ไม่ใช่ไฟล์เปล่า


def test_with_levels_and_reaction_date():
    prices = make_prices()
    png = build_chart_png("NVDA", prices, levels=_levels(prices))
    assert png is not None and png.startswith(PNG_MAGIC)


def test_levels_with_missing_values_do_not_crash():
    prices = make_prices()
    png = build_chart_png("NVDA", prices,
                          levels={"high_5d": None, "sl": None})
    assert png is not None and png.startswith(PNG_MAGIC)


def test_reaction_date_outside_window_ignored():
    # งบเก่ากว่าช่วงที่พล็อต (CHART_BARS แท่ง) — เส้นวันงบต้องถูกข้าม ไม่พัง
    prices = make_prices(CHART_BARS + 30)
    levels = {"sl": 180.0, "reaction_date": prices[-1]["date"]}
    png = build_chart_png("NVDA", prices, levels=levels)
    assert png is not None and png.startswith(PNG_MAGIC)


def test_too_few_bars_returns_none():
    assert build_chart_png("NVDA", []) is None
    assert build_chart_png("NVDA", make_prices(1)) is None
