"""SL แสดงผลเมื่อราคาหลุด SL แล้ว (sl_pct ติดลบ): เดิม f"(-{sl_pct}%)" พิมพ์ "(--9.03%)" — 4 จุดใน formatter
(candidate ผลสแกน · lookup · ติดตาม · แผน) ใช้ helper _sl_pct_text เดียวกัน (แบบ HK 82efe6f)"""
from bot.formatter import _sl_pct_text, format_plan, format_scan, format_watch_detail
from bot.plan import build_plan
from tests.test_formatter import make_candidate


def test_sl_pct_text_helper():
    assert _sl_pct_text(9.8) == "(-9.8%)"
    assert _sl_pct_text(-9.03) == "(⛔ ต่ำกว่า SL 9.03%)"
    assert _sl_pct_text(-4.066, digits=1) == "(⛔ ต่ำกว่า SL 4.1%)"
    assert _sl_pct_text(None) == ""


def _scan(c):
    return {"from_date": "2026-08-27", "to_date": "2026-08-28", "universe_size": 500, "reported_symbols": ["AAPL"],
            "candidates": [c], "skipped_counts": {"C": 0, "D": 0, "down": 0}, "pending": [], "api_stats": {}}


def test_scan_candidate_sl_line_below_sl():
    c = make_candidate()
    c["levels"] = {**c["levels"], "sl": 200.0, "sl_pct": -9.03}
    text = "\n".join(format_scan(_scan(c)))
    assert "🛑 SL (low วันงบ): 200.00  (⛔ ต่ำกว่า SL 9.03%)" in text and "--" not in text


def _watch_snap(sl_pct):
    return {"symbol": "CRM", "name": "Salesforce", "grade": "B", "price": 233.0, "day_change_pct": 1.2,
            "low": 230.4, "vol_ratio": 1.1, "dr_symbols": "CRM19", "new_breaks": [], "gap_pullback": False,
            "sl_break": False, "low_break": False, "last_earnings": "2026-08-26", "days_since_earnings": 2,
            "next_earnings": None, "days_to_earnings": None, "score": 75.0, "pending_reaction": False,
            "levels": {"high_5d": 213.17, "high_3m": 260.0, "sl": 240.0, "sl_pct": sl_pct,
                       "d0_high": 240.0, "d0_open": 231.0, "pct_vs_d0_high": -2.9,
                       "pct_vs_high_5d": 9.3, "pct_vs_high_3m": -10.4, "low_5d": 200.0,
                       "pct_vs_low_5d": 16.5, "broke_prev_week_high": None,
                       "new_high_count_10d": 3, "prev_week_high": None, "reaction_pct": 3.0, "vol_ratio": 1.1}}


def test_watch_detail_sl_below_sl():
    text = format_watch_detail([("CRM", _watch_snap(-3.0))])
    assert "SL 240.00 (⛔ ต่ำกว่า SL 3.0%)" in text and "--" not in text
    assert "SL 240.00 (-2.9%)" in format_watch_detail([("CRM", _watch_snap(2.9))])


def test_plan_header_sl_below_sl():
    snap = {"symbol": "CRM", "name": "Salesforce", "grade": None, "score": None, "price": 229.0,
            "last_earnings": "2026-08-26", "timing": "amc", "dr_symbols": "", "pending_reaction": False,
            "levels": {"sl": 230.05, "sl_pct": -0.46, "d0_high": 240.0, "d0_open": 231.0,
                       "pct_vs_d0_high": -4.6, "reaction_pct": 3.0}}
    msg = format_plan(build_plan(snap, risk_amount=None, drs=[]), snap)
    assert "🛑 SL = D0 Low 230.05 (⛔ ต่ำกว่า SL 0.46%)" in msg and "--" not in msg
