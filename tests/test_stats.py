from datetime import date, timedelta

from bot.formatter import format_stats
from bot.stats import HORIZONS, build_stats, evaluate_stat, summarize

FLAG = "2026-05-01"             # ศุกร์ — post bars เริ่มจันทร์ 4 พ.ค.


def _sig(**over):
    s = {"symbol": "NVDA", "grade": "A", "flag_date": FLAG,
         "flag_price": 100.0, "sl": 95.0}
    s.update(over)
    return s


def _bar(d, close, low=None):
    return {"date": d.isoformat(), "open": close, "high": close + 1,
            "low": low if low is not None else close - 1,
            "close": close, "volume": 1_000_000}


def _prices(post_closes=(), post_lows=None, pre_n=6):
    """แท่งก่อนแจ้ง pre_n แท่ง (ปิด 100 รวมแท่งวันแจ้งเอง) + post ตาม closes

    คืน most-recent-first ตาม convention repo
    """
    bars = []
    d = date(2026, 5, 1)
    for _ in range(pre_n):
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        bars.append(_bar(d, 100.0))
        d -= timedelta(days=1)
    bars.reverse()              # เก่า → ใหม่
    d = date(2026, 5, 4)
    for i, c in enumerate(post_closes):
        while d.weekday() >= 5:
            d += timedelta(days=1)
        low = post_lows[i] if post_lows else None
        bars.append(_bar(d, c, low=low))
        d += timedelta(days=1)
    return list(reversed(bars))  # most-recent-first


# ── evaluate_stat ────────────────────────────────────────────────

def test_drift_at_each_horizon():
    closes = [101.0] * 4 + [110.0] + [105.0] * 14 + [120.0]  # 20 post bars
    ev = evaluate_stat(_sig(), _prices(closes))
    assert round(ev["drifts"][5], 2) == 10.0     # post แท่งที่ 5 ปิด 110
    assert round(ev["drifts"][20], 2) == 20.0    # post แท่งที่ 20 ปิด 120
    assert ev["drifts"][60] is None              # ยังถือไม่ถึง 60 วัน


def test_flag_day_bar_excluded_from_post():
    # แท่งวันแจ้งเอง (ปิด 100) ไม่ใช่ post — drift 5 ต้องมาจากแท่งหลังวันแจ้งล้วน
    ev = evaluate_stat(_sig(), _prices([102.0] * 5))
    assert round(ev["drifts"][5], 2) == 2.0


def test_sl_hit_true_false_and_none():
    hit = evaluate_stat(_sig(), _prices([100.0] * 3, post_lows=[99, 94, 99]))
    assert hit["sl_hit"] is True
    ok = evaluate_stat(_sig(), _prices([100.0] * 3, post_lows=[99, 96, 99]))
    assert ok["sl_hit"] is False
    no_sl = evaluate_stat(_sig(sl=None), _prices([100.0] * 3))
    assert no_sl["sl_hit"] is None


def test_data_not_reaching_flag_date_returns_none():
    # แท่งเก่าสุดใหม่กว่าวันแจ้ง = หน้าต่างราคา 250 วันย้อนไม่ถึง → ประเมินไม่ได้
    prices = _prices([101.0] * 5, pre_n=0)
    assert evaluate_stat(_sig(), prices) is None
    assert evaluate_stat(_sig(), []) is None


# ── summarize ────────────────────────────────────────────────────

def _ev(grade, d5, sl_hit=False):
    return {"grade": grade,
            "drifts": {5: d5, 20: None, 60: None}, "sl_hit": sl_hit}


def test_summarize_groups_by_grade_plus_all():
    groups = summarize([_ev("A", 10.0), _ev("A", -5.0, sl_hit=True),
                        _ev("B", 3.0)])
    a = groups["A"]
    assert a["n"] == 2
    assert a["horizons"][5]["n"] == 2
    assert round(a["horizons"][5]["avg"], 2) == 2.5
    assert a["horizons"][5]["wins"] == 1
    assert a["horizons"][20]["n"] == 0
    assert a["sl_n"] == 2 and a["sl_hits"] == 1
    assert groups["B"]["n"] == 1
    assert groups["all"]["n"] == 3
    assert groups["all"]["horizons"][5]["wins"] == 2


def test_summarize_sl_none_not_counted():
    groups = summarize([_ev("A", 1.0, sl_hit=None)])
    assert groups["A"]["sl_n"] == 0


# ── build_stats ──────────────────────────────────────────────────

def test_build_stats_skips_fetch_errors():
    prices = {"NVDA": _prices([102.0] * 5)}

    def get_prices(sym):
        if sym == "BAD":
            raise RuntimeError("boom")
        return prices.get(sym)

    evs = build_stats([_sig(), _sig(symbol="BAD"), _sig(symbol="NODATA")],
                      get_prices)
    assert len(evs) == 1


# ── format_stats ─────────────────────────────────────────────────

def test_format_stats_message():
    groups = summarize([_ev("A", 10.0), _ev("A", -5.0, sl_hit=True),
                        _ev("B", 3.0)])
    msg = format_stats(groups, total=4)
    assert "สถิติ" in msg
    assert "ทั้งหมด 4 สัญญาณ" in msg and "ประเมินได้ 3" in msg
    assert "เกรด A — 2 ตัว" in msg
    assert "+5 วัน: เฉลี่ย +2.5% · ชนะ 1/2" in msg
    assert "หลุด SL: 1/2" in msg
    assert "เกรด B — 1 ตัว" in msg
    assert "รวมทุกเกรด — 3 ตัว" in msg
    assert "+20 วัน: ยังไม่มีตัวที่ถือถึง" in msg


def test_format_stats_empty_returns_none():
    assert format_stats({}, total=0) is None
    assert format_stats(summarize([]), total=0) is None
