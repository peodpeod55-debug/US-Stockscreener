from datetime import date, timedelta

from bot.dr import (
    BASELINE_MIN_PAIRS,
    compute_premium,
    pair_ratios,
    parse_dr_command,
    parse_dr_symbols,
)
from bot.formatter import format_dr


def _bars(pairs):
    """pairs = [(date, close), ...] เก่า→ใหม่ → bars most-recent-first"""
    return [{"date": d, "open": c, "high": c, "low": c, "close": c,
             "volume": 1_000} for d, c in reversed(pairs)]


def _weekdays(start, n):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


# ── parse_dr_command / parse_dr_symbols ──────────────────────────

def test_parse_dr_command():
    assert parse_dr_command("dr NVDA") == ["NVDA"]
    assert parse_dr_command("DR nvda tsla") == ["NVDA", "TSLA"]
    assert parse_dr_command("ดีอาร์ AAPL") == ["AAPL"]
    assert parse_dr_command("dr") == []


def test_parse_dr_command_not_a_dr_command():
    assert parse_dr_command("NVDA") is None          # lookup ปกติ
    assert parse_dr_command("drx NVDA") is None
    assert parse_dr_command("ติดตาม NVDA") is None
    assert parse_dr_command("") is None


def test_parse_dr_symbols_space_separated():
    assert parse_dr_symbols("AAPL01 AAPL03 AAPL80") == \
        ["AAPL01", "AAPL03", "AAPL80"]
    assert parse_dr_symbols("") == []
    assert parse_dr_symbols(None) == []


# ── pair_ratios ──────────────────────────────────────────────────

def test_pairing_uses_prior_us_close_and_same_day_fx():
    # DR วันไทย D คู่กับ US close ล่าสุดก่อน D (คืนก่อน) และ FX ล่าสุด ≤ D
    us = _bars([("2026-08-13", 100.0), ("2026-08-14", 200.0),
                ("2026-08-17", 400.0)])
    fx = _bars([("2026-08-14", 32.0), ("2026-08-17", 32.0),
                ("2026-08-18", 32.0)])
    dr = _bars([("2026-08-17", 3.2), ("2026-08-18", 6.4)])
    ratios = pair_ratios(dr, us, fx)
    # 08-17: US ก่อนหน้า = 14 ส.ค. (200) → 3.2/(200*32) = 0.0005
    # 08-18: US ก่อนหน้า = 17 ส.ค. (400) → 6.4/(400*32) = 0.0005
    assert [round(r, 7) for r in ratios] == [0.0005, 0.0005]


def test_pairing_skips_dr_days_without_us_or_fx():
    us = _bars([("2026-08-17", 100.0)])
    fx = _bars([("2026-08-18", 32.0)])
    dr = _bars([("2026-08-14", 3.2),    # ไม่มี US ก่อนหน้า → ข้าม
                ("2026-08-18", 3.2)])
    assert len(pair_ratios(dr, us, fx)) == 1


# ── compute_premium ──────────────────────────────────────────────

def _fixture(last_dr_close=3.2, n_pairs=None):
    n = (n_pairs or BASELINE_MIN_PAIRS + 3) + 1
    days = _weekdays(date(2026, 6, 1), n)
    us = _bars([(d, 100.0) for d in days[:-1]])       # US จบก่อน DR หนึ่งวัน
    fx = _bars([(d, 32.0) for d in days])
    dr_closes = [3.2] * (n - 2) + [last_dr_close]
    dr = _bars(list(zip(days[1:], dr_closes)))
    return dr, us, fx


def test_premium_two_percent_rich():
    dr, us, fx = _fixture(last_dr_close=3.2 * 1.02)
    p = compute_premium(dr, us, fx)
    assert round(p["premium_pct"], 2) == 2.0
    assert round(p["dr_price"], 6) == 3.264
    assert p["us_price"] == 100.0
    assert p["fx"] == 32.0
    assert round(p["fair"], 2) == 3.2                 # us*fx*baseline
    assert p["dr_date"] > p["us_date"]


def test_premium_zero_when_ratio_unchanged():
    dr, us, fx = _fixture()
    assert round(compute_premium(dr, us, fx)["premium_pct"], 4) == 0.0


def test_premium_none_when_not_enough_pairs():
    dr, us, fx = _fixture(n_pairs=BASELINE_MIN_PAIRS - 5)
    assert compute_premium(dr, us, fx) is None
    assert compute_premium(None, us, fx) is None
    assert compute_premium([], [], []) is None


# ── format_dr ────────────────────────────────────────────────────

def _prem(**over):
    p = {"dr_price": 35.75, "dr_date": "2026-08-20", "us_price": 176.2,
         "us_date": "2026-08-19", "fx": 32.83, "baseline": 0.00618,
         "fair": 35.05, "premium_pct": 2.0, "volume": 500_000}
    p.update(over)
    return p


def test_format_dr_message():
    msg = format_dr("NVDA", "NVIDIA Corp", [("NVDA80", _prem())])
    assert "NVDA" in msg and "NVIDIA" in msg
    assert "176.20" in msg and "32.83" in msg
    assert "NVDA80" in msg and "35.75" in msg
    assert "35.05" in msg                    # มูลค่าอิง ratio ปกติ
    assert "+2.0%" in msg and "แพงกว่าปกติ" in msg


def test_format_dr_discount_and_normal():
    cheap = format_dr("NVDA", "NVIDIA", [("NVDA80", _prem(premium_pct=-3.0))])
    assert "ถูกกว่าปกติ" in cheap
    normal = format_dr("NVDA", "NVIDIA", [("NVDA80", _prem(premium_pct=0.5))])
    assert "ใกล้เคียงปกติ" in normal


def test_format_dr_handles_missing_data():
    msg = format_dr("NVDA", "NVIDIA", [("NVDA80", None)])
    assert "NVDA80" in msg and "ข้อมูลไม่พอ" in msg


def test_format_dr_notes_hidden_symbols():
    msg = format_dr("NVDA", "NVIDIA", [("NVDA80", _prem())], hidden=2)
    assert "ไม่แสดงอีก 2" in msg
    assert "ไม่แสดงอีก" not in format_dr("NVDA", "NVIDIA",
                                          [("NVDA80", _prem())])
