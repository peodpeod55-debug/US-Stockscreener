from datetime import date

from bot.formatter import format_weekly
from bot.weekly import build_weekly_items, evaluate_signal

TODAY = date(2026, 8, 20)


# ── evaluate_signal ──────────────────────────────────────────────

def _sig(**over):
    s = {"symbol": "NVDA", "name": "NVDA Corp", "grade": "A", "score": 88.0,
         "earnings_date": "2026-08-01", "flag_date": "2026-08-05",
         "flag_price": 100.0, "sl": 95.0, "dr_symbols": ""}
    s.update(over)
    return s


def _bar(d, close, low=None):
    return {"date": d, "open": close, "high": close + 1,
            "low": low if low is not None else close - 1,
            "close": close, "volume": 1_000_000}


def test_evaluate_pct_and_days():
    prices = [_bar("2026-08-19", 110.0), _bar("2026-08-18", 108.0),
              _bar("2026-08-05", 100.0)]
    ev = evaluate_signal(_sig(), prices)
    assert ev["price_now"] == 110.0
    assert round(ev["pct"], 2) == 10.0
    assert ev["days"] == 14          # 2026-08-05 → 2026-08-19
    assert ev["sl_hit"] is None


def test_evaluate_sl_hit_reports_first_date():
    prices = [_bar("2026-08-19", 110.0),
              _bar("2026-08-12", 96.0, low=94.0),   # หลุดอีกวัน (ทีหลัง)
              _bar("2026-08-08", 97.0, low=94.5),   # หลุดครั้งแรก
              _bar("2026-08-05", 100.0, low=99.0)]  # วันแจ้ง — ไม่นับ
    ev = evaluate_signal(_sig(sl=95.0), prices)
    assert ev["sl_hit"] == "2026-08-08"


def test_evaluate_no_prices_returns_none():
    assert evaluate_signal(_sig(), None) is None
    assert evaluate_signal(_sig(), []) is None


# ── build_weekly_items ───────────────────────────────────────────

def test_build_weekly_items_end_to_end():
    # รับ list สัญญาณตรงๆ (จาก signals_since) — ตัวที่ดึงราคาพัง/ไม่มีข้อมูล ข้าม
    signals = [_sig(), _sig(symbol="BAD"), _sig(symbol="NODATA")]
    prices = {"NVDA": [_bar("2026-08-19", 110.0), _bar("2026-08-05", 100.0)]}

    def get_prices(sym):
        if sym == "BAD":
            raise RuntimeError("boom")
        return prices.get(sym)

    items = build_weekly_items(signals, get_prices)
    assert len(items) == 1
    assert items[0]["symbol"] == "NVDA"
    assert round(items[0]["pct"], 2) == 10.0


# ── format_weekly ────────────────────────────────────────────────

def _item(**over):
    it = {**_sig(), "price_now": 110.0, "pct": 10.0, "days": 14, "sl_hit": None}
    it.update(over)
    return it


def test_format_weekly_message():
    msg = format_weekly([
        _item(),
        _item(symbol="WMT", grade="B", flag_price=50.0, price_now=49.0, pct=-2.0),
    ])
    assert "สรุปผล" in msg
    assert "NVDA" in msg and "+10.0%" in msg and "110.00" in msg
    assert "WMT" in msg and "-2.0%" in msg
    assert "เฉลี่ย +4.0%" in msg      # (10 - 2) / 2
    assert "บวก 1/2" in msg


def test_format_weekly_sl_marker():
    msg = format_weekly([_item(sl_hit="2026-08-08", sl=95.0)])
    assert "🛑" in msg and "2026-08-08" in msg


def test_format_weekly_empty_returns_none():
    assert format_weekly([]) is None
