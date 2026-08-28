"""แนววันตอบรับงบ (D0 High / D0 Open) + เตือนทะลุ D0 High + เตือนย่อเข้าโซน gap

PEAD คลาสสิก: เข้าเมื่อทะลุ High ของวันตอบรับงบ หรือรอย่อกลับมาแตะ D0 Open (ขอบบนของ gap)
โดยยังไม่หลุด SL (= D0 Low) — เดิมบอทมีแนว H5d/H3m ก่อนงบ แต่ไม่มีแนวของวัน D0 เอง
"""
from datetime import date, timedelta

from bot.chart import _LEVEL_COLORS
from bot.formatter import (
    _hot_reason_text,
    format_breakouts,
    format_gap_pullbacks,
    format_lookup,
    format_watch_detail,
)
from bot.levels import compute_levels, detect_gap_pullback, detect_new_breaks
from bot.lookup import build_snapshot

TODAY = date(2026, 8, 20)


def make_prices(n=120, start_price=100.0):
    """ขาขึ้นวันละ 2 จบ 2026-08-19 (เหมือน test_levels)"""
    bars, d, price = [], date(2026, 8, 19), start_price
    while len(bars) < n:
        if d.weekday() < 5:
            bars.append({"date": d.isoformat(), "open": price, "high": price + 1.0,
                         "low": price - 1.0, "close": price, "volume": 1_000_000})
            price -= 2.0
        d -= timedelta(days=1)
    return bars


# ── compute_levels ───────────────────────────────────────────────

def test_compute_levels_exposes_d0_high_and_open():
    bars = make_prices()
    lv = compute_levels(bars, bars[3]["date"], "amc")     # D0 = index 2
    assert lv["d0_high"] == bars[2]["high"]
    assert lv["d0_open"] == bars[2]["open"]
    assert lv["pct_vs_d0_high"] == round((bars[0]["close"] - bars[2]["high"])
                                         / bars[2]["high"] * 100, 2)


def test_compute_levels_bmo_uses_earnings_day_bar():
    bars = make_prices()
    lv = compute_levels(bars, bars[2]["date"], "bmo")     # D0 = วันงบเอง
    assert lv["d0_high"] == bars[2]["high"] and lv["d0_open"] == bars[2]["open"]


# ── detect_new_breaks นับ d0_high ────────────────────────────────

def _bars(close_last, close_prev):
    return [{"close": close_last}, {"close": close_prev}]


def test_new_breaks_includes_d0_high_in_fixed_order():
    levels = {"high_5d": 105.0, "high_3m": 110.0, "d0_high": 104.0}
    assert detect_new_breaks(_bars(106.0, 100.0), levels) == ["high_5d", "d0_high"]
    assert detect_new_breaks(_bars(111.0, 100.0), levels) == \
        ["high_5d", "high_3m", "d0_high"]


def test_new_breaks_d0_high_not_repeated_when_already_above():
    levels = {"d0_high": 104.0}
    assert detect_new_breaks(_bars(106.0, 105.0), levels) == []


# ── detect_gap_pullback (edge, self-dedup) ───────────────────────

def _lows(low_last, low_prev, close_last=None):
    return [{"low": low_last, "close": close_last if close_last is not None else low_last + 1},
            {"low": low_prev, "close": low_prev + 1}]


def test_pullback_detected_when_low_first_touches_d0_open():
    levels = {"d0_open": 100.0, "sl": 95.0}
    assert detect_gap_pullback(_lows(99.5, 101.0, close_last=101.0), levels) is True


def test_pullback_not_repeated_when_yesterday_already_touched():
    levels = {"d0_open": 100.0, "sl": 95.0}
    assert detect_gap_pullback(_lows(99.0, 99.8), levels) is False


def test_pullback_ignored_when_sl_broken_same_day():
    """low หลุด SL = เตือนหลุด SL แทน ไม่ใช่โอกาสเข้า"""
    levels = {"d0_open": 100.0, "sl": 95.0}
    assert detect_gap_pullback(_lows(94.0, 101.0, close_last=96.0), levels) is False


def test_pullback_requires_close_at_or_above_sl():
    levels = {"d0_open": 100.0, "sl": 95.0}
    assert detect_gap_pullback(_lows(96.0, 101.0, close_last=94.5), levels) is False


def test_pullback_false_when_still_above_or_missing_data():
    levels = {"d0_open": 100.0, "sl": 95.0}
    assert detect_gap_pullback(_lows(100.5, 102.0), levels) is False
    assert detect_gap_pullback(_lows(99.0, 101.0), None) is False
    assert detect_gap_pullback(_lows(99.0, 101.0), {"d0_open": None, "sl": 95.0}) is False
    assert detect_gap_pullback(_lows(99.0, 101.0), {"d0_open": 100.0}) is False
    assert detect_gap_pullback([{"low": 99.0, "close": 100.0}], levels) is False


# ── build_snapshot ───────────────────────────────────────────────

def test_snapshot_flags_gap_pullback_and_d0_break():
    bars = make_prices()
    earn = bars[3]["date"]                                  # amc → D0 = index 2
    d0_open, d0_high = bars[2]["open"], bars[2]["high"]
    # วันล่าสุดย่อลงมาแตะ D0 Open แต่ปิดเหนือ SL — เมื่อวานยังไม่แตะ
    bars[0] = {**bars[0], "low": d0_open - 0.5, "close": d0_open + 0.5,
               "open": d0_open + 1.0, "high": d0_open + 1.5}
    s = build_snapshot("T", bars, earnings=[{"date": earn, "time": "amc"}], today=TODAY)
    assert s["gap_pullback"] is True
    assert "d0_high" not in s["new_breaks"]
    # อีกกรณี: ปิดวันล่าสุดข้าม D0 High เป็นครั้งแรก
    bars = make_prices()
    bars[1] = {**bars[1], "close": d0_high - 0.2}
    bars[0] = {**bars[0], "close": d0_high + 0.5, "low": d0_high, "high": d0_high + 1}
    s = build_snapshot("T", bars, earnings=[{"date": earn, "time": "amc"}], today=TODAY)
    assert "d0_high" in s["new_breaks"]
    assert s["gap_pullback"] is False


def test_snapshot_defaults_without_levels():
    s = build_snapshot("T", make_prices(30), earnings=None, today=TODAY)
    assert s["gap_pullback"] is False


# ── formatter ────────────────────────────────────────────────────

def _snap(**over):
    s = {"symbol": "CRM", "name": "Salesforce", "grade": "B", "price": 233.0,
         "day_change_pct": 1.2, "low": 230.4, "vol_ratio": 1.1, "dr_symbols": "CRM19",
         "levels": {"high_5d": 213.17, "high_3m": 260.0, "sl": 230.05, "sl_pct": 1.3,
                    "d0_high": 240.0, "d0_open": 231.0, "pct_vs_d0_high": -2.9,
                    "pct_vs_high_5d": 9.3, "pct_vs_high_3m": -10.4, "low_5d": 200.0,
                    "pct_vs_low_5d": 16.5, "broke_prev_week_high": None,
                    "new_high_count_10d": 3, "prev_week_high": None,
                    "reaction_pct": 3.0, "vol_ratio": 1.1},
         "new_breaks": [], "gap_pullback": False}
    s.update(over)
    return s


def test_format_breakouts_labels_d0_high():
    msg = format_breakouts([_snap(new_breaks=["d0_high"])])
    assert "High วันงบ (240.00)" in msg


def test_format_gap_pullbacks_message():
    msg = format_gap_pullbacks([_snap(gap_pullback=True)])
    assert msg.startswith("🔽 ย่อเข้าโซน gap")
    assert "CRM" in msg and "D0 Open 231.00" in msg and "SL 230.05" in msg
    assert "low 230.40" in msg
    assert format_gap_pullbacks([]) is None


def test_hot_reason_break_knows_d0_high():
    assert "High วันงบ" in _hot_reason_text(("break", ["d0_high"]))


def test_watch_detail_and_lookup_show_d0_levels():
    s = _snap()
    s.update({"last_date": "2026-08-27", "gap_pct": 0.5, "intraday_pct": 0.7,
              "chg_5d_pct": 2.0, "chg_1m_pct": 5.0, "volume": 1_000_000,
              "hi_5d": 240.0, "lo_5d": 220.0, "hi_3m": 260.0, "lo_3m": 200.0,
              "hi_52w": None, "lo_52w": None, "last_earnings": "2026-08-26",
              "next_earnings": None, "days_since_earnings": 1, "days_to_earnings": None,
              "since_earnings_pct": 1.5, "reaction_pct": 3.0, "timing": "amc",
              "score": 75.0, "pending_reaction": False, "sl_break": False,
              "low_break": False})
    detail = format_watch_detail([("CRM", s)])
    assert "D0H 240.00" in detail and "D0O 231.00" in detail
    look = format_lookup(s)
    assert "High วันงบ" in look and "240.00" in look and "231.00" in look


def test_chart_draws_d0_high_line():
    assert "d0_high" in dict(_LEVEL_COLORS)
