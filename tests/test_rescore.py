"""bot/rescore.py — เกณฑ์ไทยมีชีวิต 14 วัน: จำ D0 ของตัวที่ติดสแกน คิดคะแนนซ้ำรายวัน
แจ้งเฉพาะตัวที่เพิ่งข้ามเกณฑ์ (SET_QUALIFY_MIN) ครั้งแรก + เขียนแถวใหม่ลง scan_log.csv เดิม"""
import csv
import inspect
from datetime import date, timedelta

from bot.rescore import (due, first_crossings, format_crossed, load_state,
                         rescore_entries, run, track)

D0 = date(2026, 8, 3)                                   # จันทร์ (ISO week 32)
D0_ISO = D0.isoformat()


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


def _bar(d, high, low, close, volume=1_000_000):
    return {"date": d.isoformat(), "open": close, "high": high,
            "low": low, "close": close, "volume": volume}


def _bars(post_closes, d0_close=101.5, d0_vol=1_600_000):
    """bars most-recent-first: 70 แท่งก่อนงบ (ไฮ 3 เดือน 105, ไฮ 5 วันท้าย 100, ปิดก่อนงบ 99)
    + D0 + แท่งหลังงบตาม post_closes — D0 ปิด +2.53% vol 1.6× = ด่าน SET ผ่านแต่คะแนนยังต่ำ"""
    pre_days = _weekdays_before(D0, 70)
    bars_asc = [_bar(d, 105.0, 103.0, 104.0) for d in pre_days[:-5]]
    bars_asc += [_bar(d, 100.0, 98.0, 99.0) for d in pre_days[-5:]]
    bars_asc.append(_bar(D0, d0_close + 0.5, 99.0, d0_close, d0_vol))
    for d, c in zip(_weekdays_after(D0, len(post_closes)), post_closes):
        bars_asc.append(_bar(d, c + 1.0, c - 1.0, c))
    return bars_asc[::-1]


# ทำไฮใหม่ต่อเนื่อง 5 วัน ทะลุไฮ 3 เดือน → คะแนน ณ 11 ส.ค. ≥ 10 (ความต่อเนื่องสุกงอม)
STRONG_POST = [103.0, 105.0, 107.0, 109.0, 111.0]
# แผ่วหลังงบ ไม่ทำไฮใหม่ → คะแนนต่ำตลอด
WEAK_POST = [100.8, 100.5, 100.2, 100.0, 99.8]


def _picked_row(symbol="AAA", earn=D0_ISO, d0=D0_ISO, grade="D", pts=5):
    return {"symbol": symbol, "earnings_date": earn, "d0": d0, "grade": grade,
            "set_hit": True, "set_pts": pts, "ret_d0_pct": 2.53,
            "vol_ratio": 1.6, "skip_reason": grade}


# ── track: จำตัวที่ติดสแกน + ตัดตัวพ้นกรอบ ───────────────────────

def test_track_registers_picked_row():
    state = track({}, [_picked_row()], today=date(2026, 8, 4), days=14)
    assert state == {"AAA": {"earn_date": D0_ISO, "d0": D0_ISO,
                             "grade": "D", "qualified": None}}


def test_track_prunes_entries_outside_window():
    old = {"OLD": {"earn_date": "2026-07-01", "d0": "2026-07-01",
                   "grade": "B", "qualified": None}}
    state = track(old, [], today=date(2026, 8, 4), days=14)
    assert state == {}


def test_track_keeps_qualified_for_same_quarter():
    prev = {"AAA": {"earn_date": D0_ISO, "d0": D0_ISO, "grade": "D",
                    "qualified": "2026-08-05"}}
    state = track(prev, [_picked_row()], today=date(2026, 8, 6), days=14)
    assert state["AAA"]["qualified"] == "2026-08-05"


def test_track_resets_qualified_on_new_earnings_date():
    prev = {"AAA": {"earn_date": "2026-08-01", "d0": "2026-08-01",
                    "grade": "B", "qualified": "2026-08-02"}}
    state = track(prev, [_picked_row(earn=D0_ISO, d0=D0_ISO)],
                  today=date(2026, 8, 4), days=14)
    assert state["AAA"] == {"earn_date": D0_ISO, "d0": D0_ISO,
                            "grade": "D", "qualified": None}


# ── due: ตัวที่ต้องคิดคะแนนซ้ำวันนี้ ─────────────────────────────

def test_due_within_window_excluding_todays_rows():
    state = {
        "AAA": {"earn_date": D0_ISO, "d0": D0_ISO, "grade": "D", "qualified": None},
        "OLD": {"earn_date": "2026-07-20", "d0": "2026-07-20", "grade": "B", "qualified": None},
        "NEW": {"earn_date": "2026-08-10", "d0": "2026-08-11", "grade": "A", "qualified": None},
    }
    syms = due(state, today=date(2026, 8, 11), days=14, exclude={"NEW"})
    assert syms == ["AAA"]


# ── rescore_entries: คิดคะแนนสดจาก bars ปัจจุบัน ─────────────────

def test_rescore_entries_scores_with_current_bars():
    state = {"AAA": {"earn_date": D0_ISO, "d0": D0_ISO, "grade": "D",
                     "qualified": None}}
    bars = _bars(STRONG_POST)
    entries, pts_map = rescore_entries(state, ["AAA"], lambda s: bars)
    assert pts_map["AAA"] >= 10
    (row, scored), = entries
    assert row["symbol"] == "AAA"
    assert row["earnings_date"] == D0_ISO
    assert row["grade"] == "D"                  # เกรด composite ของ D0 เดิม ติดไปกับแถว
    assert scored["pts"] == pts_map["AAA"]


def test_rescore_entries_skips_symbol_without_bars():
    state = {"AAA": {"earn_date": D0_ISO, "d0": D0_ISO, "grade": "D",
                     "qualified": None}}
    entries, pts_map = rescore_entries(state, ["AAA"], lambda s: None)
    assert entries == [] and pts_map == {}


# ── first_crossings: แจ้งครั้งแรกครั้งเดียว ──────────────────────

def test_first_crossing_marks_and_reports_once():
    state = {"AAA": {"earn_date": D0_ISO, "d0": D0_ISO, "grade": "D",
                     "qualified": None}}
    today = date(2026, 8, 11)
    state, crossed = first_crossings(state, {"AAA": 11}, today, min_pts=10)
    assert crossed == [{"symbol": "AAA", "pts": 11, "days_after": 8, "grade": "D"}]
    assert state["AAA"]["qualified"] == today.isoformat()
    state, again = first_crossings(state, {"AAA": 12}, today, min_pts=10)
    assert again == []


def test_below_min_or_none_does_not_cross():
    state = {"AAA": {"earn_date": D0_ISO, "d0": D0_ISO, "grade": "D", "qualified": None},
             "BBB": {"earn_date": D0_ISO, "d0": D0_ISO, "grade": "C", "qualified": None}}
    state, crossed = first_crossings(state, {"AAA": 9, "BBB": None},
                                     date(2026, 8, 11), min_pts=10)
    assert crossed == []
    assert state["AAA"]["qualified"] is None


# ── format_crossed: ข้อความแจ้ง ──────────────────────────────────

def test_format_crossed_lists_symbol_score_and_day():
    text = format_crossed([{"symbol": "AAA", "pts": 11, "days_after": 8,
                            "grade": "D"}], min_pts=10)
    assert "AAA" in text and "11/15" in text and "8" in text and "D" in text
    assert "10" in text                          # บอกเกณฑ์ที่ใช้


def test_format_crossed_empty_is_blank():
    assert format_crossed([], min_pts=10) == ""


# ── run: ครบวงจร เขียน CSV + state ───────────────────────────────

def test_run_rescore_writes_csv_row_and_reports_crossing(tmp_path):
    csv_path = tmp_path / "scan_log.csv"
    state_path = tmp_path / "rescore_state.json"
    # วันแรก (4 ส.ค.): สแกนเจอ AAA คะแนน 5 — ยังไม่ถึงเกณฑ์
    crossed = run([_picked_row()], {}, lambda s: None, today=date(2026, 8, 4),
                  min_pts=10, days=14, csv_path=csv_path, state_path=state_path)
    assert crossed == []
    # วันที่ 11 ส.ค.: ไม่มีตัวใหม่ แต่ AAA ทำไฮต่อเนื่อง → ข้ามเกณฑ์ครั้งแรก
    bars = _bars(STRONG_POST)
    crossed = run([], {}, lambda s: bars, today=date(2026, 8, 11),
                  min_pts=10, days=14, csv_path=csv_path, state_path=state_path)
    assert [c["symbol"] for c in crossed] == ["AAA"]
    assert crossed[0]["pts"] >= 10
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    head, body = rows[0], rows[1:]
    added = [r for r in body if r[0] == "2026-08-11" and r[1] == "AAA"]
    assert len(added) == 1
    assert int(added[0][head.index("score")]) >= 10
    assert added[0][head.index("grade")] == "D"
    assert load_state(state_path)["AAA"]["qualified"] == "2026-08-11"


def test_run_does_not_report_same_crossing_twice(tmp_path):
    csv_path = tmp_path / "scan_log.csv"
    state_path = tmp_path / "rescore_state.json"
    run([_picked_row()], {}, lambda s: None, today=date(2026, 8, 4),
        min_pts=10, days=14, csv_path=csv_path, state_path=state_path)
    bars = _bars(STRONG_POST)
    for _ in range(2):
        crossed = run([], {}, lambda s: bars, today=date(2026, 8, 11),
                      min_pts=10, days=14, csv_path=csv_path,
                      state_path=state_path)
    assert crossed == []


def test_run_weak_stock_never_crosses(tmp_path):
    csv_path = tmp_path / "scan_log.csv"
    state_path = tmp_path / "rescore_state.json"
    run([_picked_row()], {}, lambda s: None, today=date(2026, 8, 4),
        min_pts=10, days=14, csv_path=csv_path, state_path=state_path)
    crossed = run([], {}, lambda s: _bars(WEAK_POST), today=date(2026, 8, 11),
                  min_pts=10, days=14, csv_path=csv_path, state_path=state_path)
    assert crossed == []


def test_run_tracks_only_picked_rows(tmp_path):
    """แถวที่ไม่ผ่านทั้งสองด่าน (down + ไม่ set_hit) ต้องไม่ถูกตาม"""
    csv_path = tmp_path / "scan_log.csv"
    state_path = tmp_path / "rescore_state.json"
    down = {"symbol": "DDD", "earnings_date": D0_ISO, "d0": D0_ISO,
            "grade": "D", "set_hit": False, "set_pts": 0, "ret_d0_pct": -3.0,
            "vol_ratio": 1.0, "skip_reason": "down"}
    run([_picked_row(), down], {}, lambda s: None, today=date(2026, 8, 4),
        min_pts=10, days=14, csv_path=csv_path, state_path=state_path)
    state = load_state(state_path)
    assert "AAA" in state and "DDD" not in state


def test_run_d0_crossing_reported_same_day(tmp_path):
    """ตัวที่คะแนนถึงตั้งแต่วันสแกนแรก → แจ้งวันนั้นเลย (ใช้คะแนนสดที่สแกนคิดแล้ว)"""
    csv_path = tmp_path / "scan_log.csv"
    state_path = tmp_path / "rescore_state.json"
    row = _picked_row(symbol="HOT", pts=11)
    crossed = run([row], {"HOT": {"pts": 11}}, lambda s: None,
                  today=date(2026, 8, 4), min_pts=10, days=14,
                  csv_path=csv_path, state_path=state_path)
    assert [c["symbol"] for c in crossed] == ["HOT"]
    assert crossed[0]["days_after"] == 1


# ── wiring: สแกนรายวันต้องต่อ rescore + daily_job ขยาย lookback ──

def test_scan_flow_wires_rescore():
    from bot import main
    src = inspect.getsource(main._do_scan_and_send)
    assert "rescore.run" in src                  # ผ่าน to_thread → ส่งเป็น callable
    assert "format_crossed(" in src


def test_daily_job_widens_lookback_after_downtime():
    from bot import main
    assert "widen_lookback(" in inspect.getsource(main.daily_job)
