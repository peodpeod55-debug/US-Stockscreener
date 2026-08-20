from datetime import date, timedelta

from bot.formatter import format_sl_breaks
from bot.levels import detect_sl_break
from bot.lookup import build_snapshot

TODAY = date(2026, 8, 20)


# ── detect_sl_break (pure) ───────────────────────────────────────

def _bars(low_last, low_prev):
    return [{"low": low_last}, {"low": low_prev}]


def test_newly_broken_detected():
    assert detect_sl_break(_bars(98.0, 100.0), {"sl": 99.0}) is True


def test_already_below_not_repeated():
    # เมื่อวานหลุดไปแล้ว → วันนี้ไม่นับเป็น "เพิ่งหลุด" (กันเตือนซ้ำทุกวัน)
    assert detect_sl_break(_bars(97.0, 98.0), {"sl": 99.0}) is False


def test_still_above_no_break():
    assert detect_sl_break(_bars(100.0, 101.0), {"sl": 99.0}) is False


def test_low_equal_sl_not_a_break():
    # ต้องต่ำกว่า SL จริงๆ (นิยามเดียวกับ sl_hit ใน weekly: low < sl)
    assert detect_sl_break(_bars(99.0, 100.0), {"sl": 99.0}) is False
    # วันก่อน low เท่า SL พอดี = ยังไม่เคยหลุด → วันนี้หลุดนับ
    assert detect_sl_break(_bars(98.0, 99.0), {"sl": 99.0}) is True


def test_no_levels_or_no_sl_or_short_prices():
    assert detect_sl_break(_bars(98.0, 100.0), None) is False
    assert detect_sl_break(_bars(98.0, 100.0), {"sl": None}) is False
    assert detect_sl_break([{"low": 98.0}], {"sl": 99.0}) is False


# ── build_snapshot ใส่ sl_break ──────────────────────────────────

def flat_prices(n=120):
    bars = []
    d = date(2026, 8, 19)
    while len(bars) < n:
        if d.weekday() < 5:
            bars.append({
                "date": d.isoformat(),
                "open": 100.0, "high": 101.0, "low": 99.0,
                "close": 100.0, "volume": 1_000_000,
            })
        d -= timedelta(days=1)
    return bars  # most-recent-first


def test_snapshot_sl_break_on_cross():
    bars = flat_prices(120)
    # SL = low ของ D0 = 99.0 · เมื่อวาน low 99.0 (ยังไม่หลุด) วันนี้ low 98.0 → เพิ่งหลุด
    bars[0] = {**bars[0], "low": 98.0, "close": 98.5}
    earn_date = bars[5]["date"]
    s = build_snapshot("TEST", bars,
                       earnings=[{"date": earn_date, "time": "amc"}], today=TODAY)
    assert s["levels"] is not None
    assert s["sl_break"] is True
    assert s["low"] == 98.0


def test_snapshot_sl_break_false_when_above():
    bars = flat_prices(120)
    earn_date = bars[5]["date"]
    s = build_snapshot("TEST", bars,
                       earnings=[{"date": earn_date, "time": "amc"}], today=TODAY)
    assert s["levels"] is not None
    assert s["sl_break"] is False


def test_snapshot_sl_break_false_without_levels():
    s = build_snapshot("TEST", flat_prices(30), earnings=None, today=TODAY)
    assert s["levels"] is None
    assert s["sl_break"] is False


# ── format_sl_breaks ─────────────────────────────────────────────

def _snap(**over):
    base = {
        "symbol": "NVDA", "name": "NVIDIA Corp", "price": 98.5,
        "day_change_pct": -3.2, "low": 98.0, "sl_break": True,
        "dr_symbols": "NVDA80", "grade": "A",
        "levels": {"sl": 99.0, "high_5d": 101.0, "high_3m": 105.0},
    }
    base.update(over)
    return base


def test_format_sl_breaks_message():
    msg = format_sl_breaks([_snap()])
    assert "🛑" in msg
    assert "NVDA" in msg and "98.50" in msg
    assert "99.00" in msg          # ระดับ SL
    assert "98.00" in msg          # low ที่หลุด
    assert "NVDA80" in msg


def test_format_sl_breaks_empty_returns_none():
    assert format_sl_breaks([]) is None
