from datetime import date, timedelta

from bot.formatter import format_low_breaks
from bot.levels import below_low_5d, compute_levels, detect_low_break
from bot.lookup import build_snapshot

TODAY = date(2026, 8, 20)


def make_prices(n=120, start_price=100.0):
    """daily bars ย้อนหลัง n วันทำการ (จบ 2026-08-19) ราคาขึ้นวันละ 2.0 — สไตล์ test_levels"""
    bars = []
    d = date(2026, 8, 19)
    price = start_price
    while len(bars) < n:
        if d.weekday() < 5:
            bars.append({
                "date": d.isoformat(),
                "open": price, "high": price + 1.0, "low": price - 1.0,
                "close": price, "volume": 1_000_000,
            })
            price -= 2.0
        d -= timedelta(days=1)
    return bars  # most-recent-first


# ── compute_levels ใส่ low_5d (low 5 วันก่อนงบ) ──────────────────

def test_compute_levels_low_5d():
    bars = make_prices()
    # งบ AMC วันที่ index 3 → D0 = index 2, pre = bars[3:]
    lv = compute_levels(bars, bars[3]["date"], "amc")
    assert lv["low_5d"] == min(b["low"] for b in bars[3:8])
    assert lv["pct_vs_low_5d"] > 0    # ราคาขึ้นตลอด → ปิดเหนือ low ก่อนงบ


# ── detect_low_break (pure, self-dedup แบบ detect_sl_break) ──────

def _bars(low_last, low_prev):
    return [{"low": low_last}, {"low": low_prev}]


def test_newly_broken_detected():
    assert detect_low_break(_bars(98.0, 100.0), {"low_5d": 99.0}) is True


def test_already_below_not_repeated():
    # เมื่อวานหลุดไปแล้ว → วันนี้ไม่นับ "เพิ่งหลุด" (กันเตือนซ้ำทุกวัน)
    assert detect_low_break(_bars(97.0, 98.0), {"low_5d": 99.0}) is False


def test_still_above_no_break():
    assert detect_low_break(_bars(100.0, 101.0), {"low_5d": 99.0}) is False


def test_low_equal_level_not_a_break():
    assert detect_low_break(_bars(99.0, 100.0), {"low_5d": 99.0}) is False
    assert detect_low_break(_bars(98.0, 99.0), {"low_5d": 99.0}) is True


def test_no_levels_or_no_low_or_short_prices():
    assert detect_low_break(_bars(98.0, 100.0), None) is False
    assert detect_low_break(_bars(98.0, 100.0), {"low_5d": None}) is False
    assert detect_low_break([{"low": 98.0}], {"low_5d": 99.0}) is False


# ── below_low_5d (สถานะ "ตอนนี้อยู่ใต้แนว" — ใช้ตัดสิน auto-remove) ──

def test_below_when_close_under_level():
    assert below_low_5d({"price": 98.5, "low_5d": 99.0}) is True


def test_not_below_when_close_above_or_equal():
    assert below_low_5d({"price": 99.0, "low_5d": 99.0}) is False
    assert below_low_5d({"price": 100.0, "low_5d": 99.0}) is False


def test_below_handles_missing_data():
    assert below_low_5d(None) is False
    assert below_low_5d({"price": 98.0, "low_5d": None}) is False


# ── build_snapshot ใส่ low_break ─────────────────────────────────

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


def test_snapshot_low_break_on_cross():
    bars = flat_prices(120)
    # low 5 วันก่อนงบ = 99.0 · เมื่อวาน low 99.0 (ยังไม่หลุด) วันนี้ low 98.0 → เพิ่งหลุด
    bars[0] = {**bars[0], "low": 98.0, "close": 98.5}
    earn_date = bars[5]["date"]
    s = build_snapshot("TEST", bars,
                       earnings=[{"date": earn_date, "time": "amc"}], today=TODAY)
    assert s["levels"] is not None
    assert s["low_break"] is True


def test_snapshot_low_break_false_when_above():
    bars = flat_prices(120)
    earn_date = bars[5]["date"]
    s = build_snapshot("TEST", bars,
                       earnings=[{"date": earn_date, "time": "amc"}], today=TODAY)
    assert s["low_break"] is False


def test_snapshot_low_break_false_without_levels():
    s = build_snapshot("TEST", flat_prices(30), earnings=None, today=TODAY)
    assert s["levels"] is None
    assert s["low_break"] is False


# ── format_low_breaks ────────────────────────────────────────────

def _snap(**over):
    base = {
        "symbol": "NVDA", "name": "NVIDIA Corp", "price": 96.5,
        "day_change_pct": -4.1, "low": 96.0, "low_break": True,
        "dr_symbols": "NVDA80", "grade": "A",
        "levels": {"low_5d": 97.0, "sl": 99.0,
                   "high_5d": 101.0, "high_3m": 105.0},
    }
    base.update(over)
    return base


def test_format_low_breaks_message():
    msg = format_low_breaks([_snap()])
    assert "⛔" in msg
    assert "NVDA" in msg and "96.50" in msg
    assert "97.00" in msg          # ระดับ low 5 วันก่อนงบ
    assert "NVDA80" in msg


def test_format_low_breaks_removed_footer():
    msg = format_low_breaks([_snap()], removed=["NVDA"])
    assert "เลิกติดตามอัตโนมัติ" in msg and "NVDA" in msg


def test_format_low_breaks_removed_only_still_messages():
    # ตัวที่หลุดค้างมาหลายวัน (ไม่มี edge วันนี้) แต่ถูกเก็บกวาดออก — ต้องไม่หายเงียบ
    msg = format_low_breaks([], removed=["ABEO"])
    assert msg is not None and "ABEO" in msg


def test_format_low_breaks_empty_returns_none():
    assert format_low_breaks([]) is None
