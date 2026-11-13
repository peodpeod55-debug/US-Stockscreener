"""แท่งที่พลาด — breakout_job ต้องตามเก็บทุกแท่งที่ใหม่กว่า "แท่งล่าสุดที่เคยแจ้ง"

บั๊กเดิม: detect_new_breaks/sl_break/low_break/gap_pullback เทียบแค่ prices[0] กับ prices[1]
วันไหนบอทไม่ได้รัน (เครื่องปิดกลางสัปดาห์/วันหยุดไทย) รอบถัดไปเห็นแท่งใหม่กว่า 1 แท่ง
→ edge ของแท่งที่ข้ามไปหายถาวร (ต.ค. 2026 หาย 5/12 session · 19 ต.ค.–12 พ.ย. หาย 4/17)
แก้: คิด snapshot "ณ แท่งนั้น" ย้อนให้ทุกแท่งที่อยู่ระหว่าง breakout_bar กับแท่งล่าสุด
"""
from datetime import date, timedelta

import pytest

from bot import fetch_cache
from bot.formatter import (format_breakouts, format_gap_pullbacks,
                           format_low_breaks, format_sl_breaks)
from bot.lookup import MAX_MISSED_BARS, build_snapshot, missed_snapshots

TODAY = date(2026, 8, 20)


def make_prices(n=120, start_price=100.0):
    """ซีรีส์ขาขึ้นวันละ 2.0 จบ 2026-08-19 (แบบเดียวกับ test_lookup)"""
    bars = []
    d = date(2026, 8, 19)
    price = start_price
    while len(bars) < n:
        if d.weekday() < 5:
            bars.append({"date": d.isoformat(), "open": price, "high": price + 1.0,
                         "low": price - 1.0, "close": price, "volume": 1_000_000})
            price -= 2.0
        d -= timedelta(days=1)
    return bars  # most-recent-first


def _setup(n=120):
    """งบ AMC ที่ bars[3] → D0 = bars[2] (ทะลุ H5d/H3m) · bars[1] ทะลุ D0 High · bars[0] ไม่มี edge"""
    bars = make_prices(n)
    earnings = [{"date": bars[3]["date"], "time": "amc"}]
    fetch_cache.put(("prices", "T", 250), bars)
    return bars, earnings


def _missed(since, earnings, **kw):
    return missed_snapshots("T", {}, since, today=TODAY,
                            known_earnings_fn=lambda s: earnings, **kw)


# ── missed_snapshots: snapshot "ณ แท่งนั้น" ของแท่งที่ข้ามไป ─────────

def test_series_has_edges_only_on_skipped_bars():
    """ยืนยันโจทย์: แท่งล่าสุดไม่มี edge แต่สองแท่งก่อนหน้ามี — ของเดิมจึงมองไม่เห็น"""
    bars, earnings = _setup()
    assert build_snapshot("T", bars, earnings=earnings, today=TODAY)["new_breaks"] == []
    assert build_snapshot("T", bars[1:], earnings=earnings, today=TODAY)["new_breaks"]
    assert build_snapshot("T", bars[2:], earnings=earnings, today=TODAY)["new_breaks"]


def test_missed_snapshots_replays_each_skipped_bar_oldest_first():
    bars, earnings = _setup()
    out = _missed(bars[3]["date"], earnings)       # รอบก่อนประมวลผลถึง bars[3]
    assert [s["last_date"] for s in out] == [bars[2]["date"], bars[1]["date"]]
    assert set(out[0]["new_breaks"]) == {"high_5d", "high_3m"}
    assert out[1]["new_breaks"] == ["d0_high"]
    # ตัวเลขของแท่งนั้นจริง ไม่ใช่ของแท่งล่าสุด
    assert out[1]["price"] == bars[1]["close"]
    assert out[1]["day_change_pct"] == build_snapshot(
        "T", bars[1:], earnings=earnings, today=TODAY)["day_change_pct"]


def test_missed_snapshots_marks_late_with_latest_close():
    bars, earnings = _setup()
    out = _missed(bars[3]["date"], earnings)
    assert len(out) == 2
    assert all(s["late"] is True for s in out)
    assert all(s["now_price"] == bars[0]["close"] for s in out)


def test_missed_snapshots_excludes_latest_bar():
    """แท่งล่าสุดเป็นหน้าที่ของ lookup_symbol เดิม — ห้ามซ้ำ"""
    bars, earnings = _setup()
    out = _missed(bars[1]["date"], earnings)       # ไม่มีแท่งคั่นกลาง
    assert out == []


@pytest.mark.parametrize("since", [None, ""])
def test_missed_snapshots_without_previous_bar_returns_nothing(since):
    """รอบแรกสุด (ยังไม่เคยมี breakout_bar) — ไม่ย้อนเหมา"""
    _bars, earnings = _setup()
    assert _missed(since, earnings) == []


def test_missed_snapshots_same_or_newer_since_returns_nothing():
    bars, earnings = _setup()
    assert _missed(bars[0]["date"], earnings) == []
    assert _missed("2099-01-01", earnings) == []


def test_missed_snapshots_capped():
    """เครื่องหายไปนาน — ตามเก็บแค่ MAX_MISSED_BARS แท่งล่าสุด (เก่ากว่านั้นเลยจุดที่ใช้ได้)"""
    bars, earnings = _setup()
    out = _missed(bars[30]["date"], earnings)
    assert [s["last_date"] for s in out] == [
        b["date"] for b in reversed(bars[1:MAX_MISSED_BARS + 1])]


def test_missed_snapshots_no_cached_prices_returns_nothing():
    """อ่านจาก cache ที่ lookup_symbol เพิ่งเติมเท่านั้น — ไม่ยิงเครือข่ายเอง"""
    assert _missed("2026-08-10", [{"date": "2026-08-14", "time": "amc"}]) == []


# ── ข้อความ: ต้องบอกว่าเป็นแท่งย้อนหลัง + ราคาปิดล่าสุด ───────────────

def _snap(**over):
    base = {
        "symbol": "NVDA", "name": "NVIDIA", "price": 102.0, "low": 99.0,
        "day_change_pct": 2.0, "vol_ratio": 1.5, "dr_symbols": "", "grade": "A",
        "levels": {"high_5d": 100.0, "low_5d": 90.0, "sl": 90.0,
                   "d0_open": 95.0, "d0_high": 101.0, "price": 102.0},
        "new_breaks": ["high_5d"], "last_date": "2026-09-04",
    }
    base.update(over)
    return base


LATE_LINE = "⏪ แจ้งย้อนหลัง — แท่ง 2026-09-04 · ปิดล่าสุด 105.50"


@pytest.mark.parametrize("fmt", [format_breakouts, format_sl_breaks,
                                 format_gap_pullbacks, format_low_breaks])
def test_late_snapshot_is_labelled_with_bar_date_and_latest_close(fmt):
    msg = fmt([_snap(late=True, now_price=105.5)])
    assert LATE_LINE in msg.splitlines()


@pytest.mark.parametrize("fmt", [format_breakouts, format_sl_breaks,
                                 format_gap_pullbacks, format_low_breaks])
def test_latest_bar_snapshot_has_no_late_label(fmt):
    assert "ย้อนหลัง" not in fmt([_snap()])
