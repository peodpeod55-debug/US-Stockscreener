"""bot/set_score.py — เกณฑ์คะแนน 0-15 + ดาว port จาก Set screnner (stock_core.signal_score) ตัวต่อตัว (เทสชุดเดียวกับ HK Stock Screener)
บน bars most-recent-first โดยรู้ D0 จาก timing ปฏิทิน (ไม่ต้องเดา "วันไหน vol สูงกว่า" แบบ SET)"""
from datetime import date, timedelta

from bot.set_score import (SET_MIN_RET_PCT, SET_MIN_VOL_RATIO, SET_SCORE_MAX, is_set_hit, set_score, stars)

D0 = date(2026, 8, 3)                                   # จันทร์ (ISO week 32)


def _weekdays_before(d, n):
    out, cur = [], d
    while len(out) < n:
        cur -= timedelta(days=1)
        if cur.weekday() < 5:
            out.append(cur)
    return list(reversed(out))


def _weekdays_after(d, n):
    out, cur = [], d
    while len(out) < n:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            out.append(cur)
    return out


def _bar(d, high, low, close, volume=1_000_000, open_=None):
    return {"date": d.isoformat(), "open": open_ if open_ is not None else close, "high": high,
            "low": low, "close": close, "volume": volume}


def make_bars(pre=30, d0=(112.0, 99.0, 110.0, 4_000_000), post=(), pre_bar=(100.0, 95.0, 98.0)):
    """pre แท่งก่อน D0 (high/low/close คงที่ vol 1M) + แท่ง D0 + post แท่ง (high, low, close[, volume]) — คืน most-recent-first"""
    bars = [_bar(d, *pre_bar) for d in _weekdays_before(D0, pre)]
    bars.append(_bar(D0, *d0))
    for d, p in zip(_weekdays_after(D0, len(post)), post):
        bars.append(_bar(d, *p))
    return list(reversed(bars))


def _rising(n, start=113.0):
    return [(start + i, start + i - 1.5, start + i - 0.5) for i in range(n)]


def _flat(n, high=105.0):
    return [(high, high - 2, high - 1)] * n


# ── องค์ประกอบคะแนน (น้ำหนักเท่า SET เป๊ะ) ────────────────────────

def test_d0_only_scores_max_11_two_stars():
    """วันแรกหลังงบ: ปฏิกิริยา 4 + ทะลุ H5d 1 + H3m 3 + ไฮใหม่สด 2 + เหนือ low 1 = 11 (ความถี่/สตรีคยังพิสูจน์ไม่ได้)"""
    s = set_score(make_bars(), D0.isoformat())
    assert s["pts"] == 11 and s["stars"] == "⭐⭐"
    assert round(s["ret_d0_pct"], 2) == 12.24 and s["vol_ratio"] == 4.0
    assert s["broke_5d"] is True and s["broke_3m"] is True
    assert s["days_since_new_high"] == 0 and s["new_high_ratio"] is None and s["weekly_hh_streak"] == 0
    assert s["above_pre_low"] is True and s["price"] == 110.0


def test_sustained_new_highs_reach_15_three_stars():
    """ทำไฮใหม่ทุกวัน 14 วัน ข้าม 3 สัปดาห์ ISO: ถี่ 100% (+2) · ไฮสัปดาห์ยกขึ้น 2 สัปดาห์ (+2) · ไฮล่าสุดวันนี้ (+2)"""
    s = set_score(make_bars(post=_rising(14)), D0.isoformat())
    assert s["pts"] == SET_SCORE_MAX == 15 and s["stars"] == "⭐⭐⭐"
    assert s["new_high_ratio"] == 1.0 and s["weekly_hh_streak"] == 2 and s["days_since_new_high"] == 0


def test_stalled_after_d0_loses_continuity_points():
    """พุ่งวันเดียวแล้วนิ่ง 8 วัน: ไฮล่าสุด 8 วัน (0) · ถี่ 0% (0) · สัปดาห์ล่าสุดต่ำกว่า (0) → 4 + 4 + 1 = 9"""
    s = set_score(make_bars(post=_flat(8)), D0.isoformat())
    assert s["pts"] == 9 and s["stars"] == "⭐⭐"
    assert s["days_since_new_high"] == 8 and s["new_high_ratio"] == 0.0 and s["weekly_hh_streak"] == 0


def test_recent_high_within_5_days_gets_1_point_and_ratio_needs_5_post_days():
    s = set_score(make_bars(post=_flat(3)), D0.isoformat())
    assert s["days_since_new_high"] == 3 and s["new_high_ratio"] is None
    assert s["pts"] == 10                                    # 4 + 4 + 1 (ไฮ ≤5 วัน) + 0 + 0 + 1


def test_new_high_ratio_30_percent_gets_1_point():
    """3 ไฮใหม่ใน 10 วันหลัง D0 = 0.3 (+1) · ไฮล่าสุด 7 วัน (0) · สัปดาห์ถัดมาต่ำกว่า (0) → 4 + 4 + 1 + 1 = 10"""
    s = set_score(make_bars(post=_rising(3) + _flat(7)), D0.isoformat())
    assert s["new_high_ratio"] == 0.3 and s["days_since_new_high"] == 7 and s["weekly_hh_streak"] == 0
    assert s["pts"] == 10


def test_weak_reaction_and_no_3m_breakout_one_star():
    """ปิด +2.55% (1) · vol 2.2× (1) · ทะลุ H5d (1) แต่ไม่ถึงไฮ 3 เดือน 120 (0) · ไฮใหม่สด (2) · เหนือ low (1) = 6 ⭐"""
    bars = make_bars(d0=(101.0, 99.0, 100.5, 2_200_000))
    old = bars[-20]                                          # แท่งเก่าใน 63 วันก่อน D0 ทำไฮ 120
    bars[-20] = {**old, "high": 120.0}
    s = set_score(bars, D0.isoformat())
    assert s["pts"] == 6 and s["stars"] == "⭐"
    assert s["broke_5d"] is True and s["broke_3m"] is False


def test_close_below_pre_earnings_low_scores_nothing_for_support():
    """ปิด D0 -8% ใต้ low 5 วันก่อนงบ: ปิด 0 แต่ vol 4× ยังได้ 2 · ไม่ทะลุ · เหนือ low ✗ · "ไฮล่าสุด" นับวันแรกเป็นไฮของช่วงเสมอ (2) = 4 ไม่มีดาว"""
    s = set_score(make_bars(d0=(99.0, 88.0, 90.0, 4_000_000)), D0.isoformat())
    assert s["above_pre_low"] is False and s["broke_5d"] is False and s["pts"] == 2 + 2 and s["stars"] == ""


def test_returns_none_when_d0_missing_or_history_short():
    assert set_score(make_bars(), "2026-08-04") is None            # ไม่มีแท่งวันนั้น
    assert set_score(make_bars(pre=5), D0.isoformat()) is None       # SET ต้องมี ≥6 แท่งก่อนงบ
    assert set_score([], D0.isoformat()) is None


def test_stars_bands_match_set():
    assert stars(13) == "⭐⭐⭐" and stars(15) == "⭐⭐⭐"
    assert stars(9) == "⭐⭐" and stars(12) == "⭐⭐"
    assert stars(5) == "⭐" and stars(8) == "⭐"
    assert stars(4) == "" and stars(0) == "" and stars(None) == ""


# ── ด่านเข้า (scanner.MIN_CHANGE_PCT / MIN_VOL_RATIO ของ SET) + ด่านสภาพคล่องของ HK ──

def test_set_hit_thresholds():
    assert (SET_MIN_RET_PCT, SET_MIN_VOL_RATIO) == (2.0, 1.5)
    assert is_set_hit(2.0, 1.5) is True
    assert is_set_hit(1.99, 1.5) is False and is_set_hit(2.0, 1.49) is False
    assert is_set_hit(None, 3.0) is False and is_set_hit(5.0, None) is False


def test_set_hit_turnover_gate_applies_only_when_min_given():
    assert is_set_hit(5.0, 3.0, turnover=50e6, min_turnover=100e6) is False
    assert is_set_hit(5.0, 3.0, turnover=100e6, min_turnover=100e6) is True
    assert is_set_hit(5.0, 3.0, turnover=None, min_turnover=100e6) is False
    assert is_set_hit(5.0, 3.0, turnover=None) is True


def test_since_pct_is_price_vs_close_before_d0():
    """since_earn_pct ของไทย = ราคาล่าสุดเทียบปิดก่อนวันงบ — HK ใช้ปิดก่อน D0 (วันแรก = ret_d0_pct เท่ากัน)"""
    s = set_score(make_bars(), D0.isoformat())
    assert s["since_pct"] == s["ret_d0_pct"] == 12.24
    s = set_score(make_bars(post=_flat(3)), D0.isoformat())             # ปิดล่าสุด 104 เทียบ 98
    assert s["since_pct"] == 6.12 and s["price"] == 104.0
