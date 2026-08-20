from datetime import date, timedelta

from bot.formatter import format_breakouts
from bot.levels import detect_new_breaks
from bot.lookup import build_snapshot

TODAY = date(2026, 8, 20)


# ── detect_new_breaks (pure) ─────────────────────────────────────

def _bars(close_last, close_prev):
    return [{"close": close_last}, {"close": close_prev}]


def test_newly_crossed_detected():
    levels = {"high_5d": 105.0, "high_3m": 110.0}
    assert detect_new_breaks(_bars(106.0, 100.0), levels) == ["high_5d"]


def test_both_levels_crossed():
    levels = {"high_5d": 105.0, "high_3m": 105.5}
    assert detect_new_breaks(_bars(106.0, 100.0), levels) == ["high_5d", "high_3m"]


def test_already_above_not_repeated():
    # ปิดเมื่อวานข้ามไปแล้ว → วันนี้ไม่นับเป็น "เพิ่งทะลุ" (กันเตือนซ้ำทุกวัน)
    levels = {"high_5d": 105.0, "high_3m": 110.0}
    assert detect_new_breaks(_bars(107.0, 106.0), levels) == []


def test_still_below_no_break():
    levels = {"high_5d": 105.0, "high_3m": 110.0}
    assert detect_new_breaks(_bars(104.0, 100.0), levels) == []


def test_close_equal_level_not_a_break():
    # ต้องปิด "เหนือ" แนวจริงๆ · ปิดก่อนหน้าเท่าแนวพอดี = ยังไม่เคยข้าม
    levels = {"high_5d": 105.0}
    assert detect_new_breaks(_bars(105.0, 100.0), levels) == []
    assert detect_new_breaks(_bars(106.0, 105.0), levels) == ["high_5d"]


def test_no_levels_or_short_prices():
    assert detect_new_breaks(_bars(106.0, 100.0), None) == []
    assert detect_new_breaks([{"close": 106.0}], {"high_5d": 105.0}) == []
    assert detect_new_breaks(_bars(106.0, 100.0), {"high_5d": None}) == []


# ── build_snapshot ใส่ new_breaks ────────────────────────────────

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


def test_snapshot_new_breaks_on_cross():
    bars = flat_prices(120)
    # แนว high_5d/high_3m ก่อนงบ = 101 · เมื่อวานปิด 100 วันนี้ปิด 102 → เพิ่งทะลุ
    bars[0] = {**bars[0], "open": 100.5, "high": 102.5, "close": 102.0}
    earn_date = bars[5]["date"]
    s = build_snapshot("TEST", bars,
                       earnings=[{"date": earn_date, "time": "amc"}], today=TODAY)
    assert s["levels"] is not None
    assert s["new_breaks"] == ["high_5d", "high_3m"]


def test_snapshot_new_breaks_empty_without_levels():
    s = build_snapshot("TEST", flat_prices(30), earnings=None, today=TODAY)
    assert s["levels"] is None
    assert s["new_breaks"] == []


# ── format_breakouts ─────────────────────────────────────────────

def _snap(**over):
    base = {
        "symbol": "NVDA", "name": "NVIDIA Corp", "price": 102.0,
        "day_change_pct": 2.0, "new_breaks": ["high_5d"], "vol_ratio": 2.3,
        "dr_symbols": "NVDA80", "grade": "A",
        "levels": {"high_5d": 101.0, "high_3m": 105.0},
    }
    base.update(over)
    return base


def test_format_breakouts_message():
    msg = format_breakouts([_snap()])
    assert "🚀" in msg
    assert "NVDA" in msg and "102.00" in msg
    assert "High 5 วันก่อนงบ" in msg and "101.00" in msg
    assert "2.3x" in msg
    assert "NVDA80" in msg


def test_format_breakouts_lists_both_levels():
    msg = format_breakouts([_snap(new_breaks=["high_5d", "high_3m"])])
    assert "High 5 วันก่อนงบ" in msg and "High 3 เดือนก่อนงบ" in msg


def test_format_breakouts_empty_returns_none():
    assert format_breakouts([]) is None
