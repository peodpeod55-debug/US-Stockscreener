"""bot/rescore.py — เกณฑ์ไทยมีชีวิต 14 วัน: จำ D0 ของตัวที่ติดสแกน คิดคะแนนซ้ำรายวัน
แจ้งเฉพาะตัวที่เพิ่งข้ามเกณฑ์ (SET_QUALIFY_MIN) ครั้งแรก + เขียนแถวใหม่ลง scan_log.csv เดิม"""
import asyncio
import csv
import inspect
import json
import logging
from datetime import date, datetime, time, timedelta

from bot.rescore import (due, first_crossings, format_crossed, load_state,
                         pop_stale_notices, rescore_entries, run, signal_candidates,
                         stale_entries, stale_notice, track)
from bot.set_score import set_score

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
    entries, pts_map, skipped = rescore_entries(state, ["AAA"], lambda s: bars)
    assert pts_map["AAA"] >= 10
    assert skipped == {}
    (row, scored), = entries
    assert row["symbol"] == "AAA"
    assert row["earnings_date"] == D0_ISO
    assert row["grade"] == "D"                  # เกรด composite ของ D0 เดิม ติดไปกับแถว
    assert scored["pts"] == pts_map["AAA"]


def test_rescore_entries_skips_symbol_without_bars():
    state = {"AAA": {"earn_date": D0_ISO, "d0": D0_ISO, "grade": "D",
                     "qualified": None}}
    entries, pts_map, skipped = rescore_entries(state, ["AAA"], lambda s: None)
    assert entries == [] and pts_map == {}
    assert skipped == {"AAA": "no_bars"}            # ข้ามได้ แต่ต้องบอกเหตุ ไม่หายเงียบ


# ── first_crossings: แจ้งครั้งแรกครั้งเดียว ──────────────────────

def test_first_crossing_marks_and_reports_once():
    state = {"AAA": {"earn_date": D0_ISO, "d0": D0_ISO, "grade": "D",
                     "qualified": None}}
    today = date(2026, 8, 11)
    state, crossed = first_crossings(state, {"AAA": 11}, today, min_pts=10)
    assert crossed == [{"symbol": "AAA", "pts": 11, "days_after": 8, "grade": "D"}]
    assert state["AAA"]["qualified"] == today.isoformat()
    # วันเดียวกัน (retry หลังส่งล้ม) ต้องได้ตัวเดิมกลับมา — ไม่งั้น ⭐/auto-watch หายถาวร
    state, again = first_crossings(state, {"AAA": 12}, today, min_pts=10)
    assert [c["symbol"] for c in again] == ["AAA"]
    assert state["AAA"]["qualified"] == today.isoformat()
    # ข้ามวันแล้วถึงหยุดแจ้ง
    state, next_day = first_crossings(state, {"AAA": 12},
                                      today + timedelta(days=1), min_pts=10)
    assert next_day == []


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
    # แถว rescore ลงวันที่ของแท่งล่าสุดจริง (จันทร์ 10 ส.ค.) ไม่ใช่วันที่รัน (11 ส.ค.)
    added = [r for r in body if r[0] == "2026-08-10" and r[1] == "AAA"]
    assert len(added) == 1
    assert not [r for r in body if r[0] == "2026-08-11"]
    assert int(added[0][head.index("score")]) >= 10
    assert added[0][head.index("grade")] == "D"
    assert load_state(state_path)["AAA"]["qualified"] == "2026-08-11"


def test_run_same_day_retry_reports_again_next_day_silent(tmp_path):
    """retry วันเดียวกัน (catch-up หลังส่งล้ม) ต้องได้ crossing เดิมซ้ำ · วันถัดไปถึงเงียบ"""
    csv_path = tmp_path / "scan_log.csv"
    state_path = tmp_path / "rescore_state.json"
    run([_picked_row()], {}, lambda s: None, today=date(2026, 8, 4),
        min_pts=10, days=14, csv_path=csv_path, state_path=state_path)
    bars = _bars(STRONG_POST)
    for _ in range(2):
        crossed = run([], {}, lambda s: bars, today=date(2026, 8, 11),
                      min_pts=10, days=14, csv_path=csv_path,
                      state_path=state_path)
        assert [c["symbol"] for c in crossed] == ["AAA"]
    crossed = run([], {}, lambda s: bars, today=date(2026, 8, 12),
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
    # rescore ต้องอยู่หลังส่งรายงานสแกน — ล้ม/ช้าไม่ฉุดรายงานหลัก + มี try/except ของตัวเอง
    assert src.index("rescore.run") > src.index("enumerate(messages)")
    assert "except Exception" in src[src.index("rescore.run"):]
    assert "_us_market_maybe_open" in src        # ตลาดเปิดอยู่ (แท่ง intraday) → เลื่อน ไม่ตัดสิน qualified
    assert "prefetch" in src                     # อุ่น cache ก่อนลูป serial


def test_daily_job_widens_lookback_after_downtime():
    from bot import main
    assert "widen_lookback(" in inspect.getsource(main.daily_job)


# ── hardening เวฟ 1 (31 ส.ค. 2026) — retry ไม่กินสัญญาณ · state เสียไม่ล้มสแกน ·
#    กรอบนับจาก D0 · scan_date/days_after ตามแท่งจริง · guard ตลาดเปิด · prefetch ──


def test_load_state_drops_broken_entries(tmp_path):
    """entry เสีย (ไม่มี d0 / d0 เพี้ยน / ไม่ใช่ dict) ถูกคัดทิ้ง — ไม่พังทั้งสแกน"""
    p = tmp_path / "rescore_state.json"
    p.write_text(json.dumps({
        "AAA": {"earn_date": D0_ISO, "d0": D0_ISO, "grade": "D", "qualified": None},
        "NOD0": {"earn_date": D0_ISO, "grade": "B", "qualified": None},
        "BADD0": {"earn_date": D0_ISO, "d0": "ไม่ใช่วันที่", "grade": "B", "qualified": None},
        "JUNK": "x",
    }, ensure_ascii=False), encoding="utf-8")
    assert set(load_state(p)) == {"AAA"}


def test_run_survives_broken_state_entry(tmp_path):
    """state มี entry เสีย 1 ตัว → ตัวดียังถูกคิด (เดิม: KeyError ล้มทั้งรายงานสแกน)"""
    csv_path = tmp_path / "scan_log.csv"
    state_path = tmp_path / "rescore_state.json"
    state_path.write_text(json.dumps({
        "AAA": {"earn_date": D0_ISO, "d0": D0_ISO, "grade": "D", "qualified": None},
        "BAD": {"earn_date": D0_ISO, "grade": "B", "qualified": None},
    }), encoding="utf-8")
    crossed = run([], {}, lambda s: _bars(STRONG_POST), today=date(2026, 8, 11),
                  min_pts=10, days=14, csv_path=csv_path, state_path=state_path)
    assert [c["symbol"] for c in crossed] == ["AAA"]


def test_track_and_due_window_from_d0_not_earn_date():
    """งบประกาศศุกร์เย็น D0 คือวันทำการถัดไป — กรอบ 14 วันต้องนับจาก D0 ไม่ใช่วันงบ"""
    ent = {"earn_date": "2026-07-20", "d0": "2026-07-28", "grade": "B", "qualified": None}
    state = track({"AAA": dict(ent)}, [], today=date(2026, 8, 8), days=14)
    assert "AAA" in state                        # ตัดด้วย earn_date จะพรุนทิ้งผิดตัว
    assert due(state, today=date(2026, 8, 8), days=14) == ["AAA"]


def test_set_score_reports_asof_and_trading_days_after():
    """set_score บอกวันแท่งล่าสุด (asof) + วันทำการหลัง D0 — ฐานของ scan_date/days_after"""
    ss = set_score(_bars(STRONG_POST), D0_ISO)
    assert ss["asof"] == "2026-08-10"
    assert ss["days_after"] == 5


def test_run_crossing_days_after_counts_trading_bars(tmp_path):
    """days_after ในข้อความ ⭐ = วันทำการหลัง D0 (5) ไม่ใช่วันปฏิทิน (8)"""
    csv_path = tmp_path / "scan_log.csv"
    state_path = tmp_path / "rescore_state.json"
    run([_picked_row()], {}, lambda s: None, today=date(2026, 8, 4),
        min_pts=10, days=14, csv_path=csv_path, state_path=state_path)
    crossed = run([], {}, lambda s: _bars(STRONG_POST), today=date(2026, 8, 11),
                  min_pts=10, days=14, csv_path=csv_path, state_path=state_path)
    assert crossed[0]["days_after"] == 5


def test_rescore_rows_on_holiday_reuse_bar_date_no_ghost_rows(tmp_path):
    """รันวันอาทิตย์ (คลาสแถวผี HK 30 ส.ค.): แถวลงวันแท่งจริง → ทับแถวเดิม ไม่เกิดแถวใหม่"""
    csv_path = tmp_path / "scan_log.csv"
    state_path = tmp_path / "rescore_state.json"
    run([_picked_row()], {}, lambda s: None, today=date(2026, 8, 4),
        min_pts=10, days=14, csv_path=csv_path, state_path=state_path)
    bars = _bars(STRONG_POST + [113.0, 115.0, 117.0, 119.0])    # ถึงศุกร์ 14 ส.ค.
    run([], {}, lambda s: bars, today=date(2026, 8, 14),
        min_pts=10, days=14, csv_path=csv_path, state_path=state_path)
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        before = list(csv.reader(f))
    run([], {}, lambda s: bars, today=date(2026, 8, 16),        # อาทิตย์ — แท่งยังเป็นของศุกร์
        min_pts=10, days=14, csv_path=csv_path, state_path=state_path)
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        after = list(csv.reader(f))
    assert after == before
    assert not [r for r in after if r[0] == "2026-08-16"]


def test_run_prefetches_due_symbols(tmp_path):
    """อุ่น cache ก่อนลูป serial — run ส่งรายชื่อ due ให้ prefetch"""
    csv_path = tmp_path / "scan_log.csv"
    state_path = tmp_path / "rescore_state.json"
    calls = []
    run([_picked_row()], {}, lambda s: None, today=date(2026, 8, 4), min_pts=10,
        days=14, csv_path=csv_path, state_path=state_path,
        prefetch=lambda syms: calls.append(list(syms)))
    assert calls == []                           # วันแรกไม่มีตัวเก่าให้คิดซ้ำ
    run([], {}, lambda s: _bars(STRONG_POST), today=date(2026, 8, 11), min_pts=10,
        days=14, csv_path=csv_path, state_path=state_path,
        prefetch=lambda syms: calls.append(list(syms)))
    assert calls == [["AAA"]]


# ── เวฟ 2 (31 ส.ค. 2026) — crossing → signals.json (set_cross) + ข้อความ ⭐ เต็ม ──


def test_run_crossed_carries_context_from_rescore(tmp_path):
    """crossed ต้องพก ราคา/%จากงบ/⛔ pre_low/วันงบ/D0 — ฐานของ record ลง signals.json + ข้อความ ⭐"""
    csv_path = tmp_path / "scan_log.csv"
    state_path = tmp_path / "rescore_state.json"
    run([_picked_row()], {}, lambda s: None, today=date(2026, 8, 4),
        min_pts=10, days=14, csv_path=csv_path, state_path=state_path)
    crossed = run([], {}, lambda s: _bars(STRONG_POST), today=date(2026, 8, 11),
                  min_pts=10, days=14, csv_path=csv_path, state_path=state_path)
    c, = crossed
    assert c["price"] == 111.0                   # ปิดล่าสุดจาก set_score
    assert c["pre_low"] == 98.0                  # ⛔ low 5 วันก่อนงบ
    assert c["since_pct"] == round((111.0 / 99.0 - 1) * 100, 2)
    assert c["earn_date"] == D0_ISO and c["d0"] == D0_ISO


def test_run_crossed_context_from_todays_scan(tmp_path):
    """ตัวที่ข้ามตั้งแต่วันสแกนแรก — บริบทมาจาก scored ของสแกนวันนี้ (ไม่ดึงราคาซ้ำ)"""
    csv_path = tmp_path / "scan_log.csv"
    state_path = tmp_path / "rescore_state.json"
    scored = {"HOT": {"pts": 11, "days_after": 1, "price": 105.0,
                      "since_pct": 6.06, "pre_low": 98.0}}
    crossed = run([_picked_row(symbol="HOT", pts=11)], scored, lambda s: None,
                  today=date(2026, 8, 4), min_pts=10, days=14,
                  csv_path=csv_path, state_path=state_path)
    c, = crossed
    assert c["price"] == 105.0 and c["pre_low"] == 98.0
    assert c["since_pct"] == 6.06 and c["earn_date"] == D0_ISO


def test_signal_candidates_maps_crossed_for_record():
    """crossed → รูป candidate ให้ record_signals: signal_type=set_cross, sl=⛔ pre_low"""
    from bot.rescore import signal_candidates
    cands = signal_candidates([{"symbol": "AAA", "pts": 11, "days_after": 5,
                                "grade": "D", "earn_date": D0_ISO, "d0": D0_ISO,
                                "price": 111.0, "since_pct": 12.12, "pre_low": 98.0}])
    c, = cands
    assert c["signal_type"] == "set_cross"
    assert c["symbol"] == "AAA" and c["earnings_date"] == D0_ISO
    assert c["levels"] == {"price": 111.0, "sl": 98.0}
    assert c["score"] == 11 and c["grade"] == "D"


def test_format_crossed_rich_context_and_auto_days():
    """ข้อความ ⭐ บอก ราคา + %จากงบ + ⛔ + จำนวนวัน auto-watch จาก AUTO_WATCH_DAYS (ไม่ hard-code 30)"""
    item = {"symbol": "AAA", "pts": 11, "days_after": 5, "grade": "D",
            "price": 111.0, "since_pct": 12.12, "pre_low": 98.0}
    text = format_crossed([item], min_pts=10, auto_days=45)
    assert "111" in text and "+12.1" in text
    assert "⛔" in text and "98" in text
    assert "45 วัน" in text and "30 วัน" not in text
    # ไฟล์ state เก่า/entry ไม่มีบริบท → บรรทัดเดิม ไม่ล้ม
    assert "BBB" in format_crossed([{"symbol": "BBB", "pts": 10, "days_after": 3,
                                     "grade": "?"}], min_pts=10)


def test_scan_flow_records_set_cross_and_charts():
    """สแกนต้องบันทึก crossing ลง signals.json (feedback loop ของเกณฑ์ SET≥10) + ส่งกราฟตัวข้าม"""
    import inspect as _i
    from bot import main
    src = _i.getsource(main._do_scan_and_send)
    assert "signal_candidates(" in src
    assert src.index("signal_candidates") > src.index("rescore.run")
    # กราฟ+ปุ่มของตัวข้ามเกณฑ์ ตามหลังข้อความ ⭐ (bars อยู่ใน cache แล้ว)
    assert src.rindex("_send_chart") > src.index("format_crossed")
    # ตัวหลุดเพดาน auto-watch ต้องถูกแจ้ง ไม่หายเงียบ (§2.3)
    assert "evicted" in src


def test_us_market_maybe_open_window():
    """20:00–05:00 ไทย แท่ง US วันนี้อาจยังไม่ปิด — rescore ต้องเลื่อน (เหตุผลเดียวกับ CATCHUP_UNTIL)"""
    from bot.main import _us_market_maybe_open
    assert _us_market_maybe_open(time(20, 0))
    assert _us_market_maybe_open(time(23, 30))
    assert _us_market_maybe_open(time(4, 59))
    assert not _us_market_maybe_open(time(5, 0))
    assert not _us_market_maybe_open(time(8, 30))
    assert not _us_market_maybe_open(time(19, 59))


# ── U1 (2 ก.ย. 2026) — บอกเหตุที่ข้าม + เตือนเมื่อข้ามติดกัน ─────
#    เคสจริง: Yahoo ลบแท่ง D0 ของ WDAY ทิ้ง → set_score คืน None → continue เงียบ
#    หลุดจากการตาม 14 วันโดยไม่มีใครรู้ (ทั้ง log/Telegram/status ไม่บอกอะไรเลย)


def _entry(d0=D0_ISO, **kw):
    return {"earn_date": D0_ISO, "d0": d0, "grade": "D", "qualified": None, **kw}


def _bars_without_d0():
    """Yahoo เขียนแท่ง D0 ทิ้ง — bars ยังมี แต่ไม่มีแท่งวัน D0 (เคส WDAY 28 ส.ค.)"""
    return [b for b in _bars(STRONG_POST) if b["date"] != D0_ISO]


def _bars_too_short():
    """มีแท่ง D0 แต่แท่งก่อนงบไม่ถึง 6 → set_score คืน None ด้วยเหตุอื่น (ไม่ใช่แท่ง D0 หาย)"""
    keep = _weekdays_before(D0, 3)[0].isoformat()
    return [b for b in _bars(STRONG_POST) if b["date"] >= keep]


def test_rescore_entries_reports_no_d0_bar_apart_from_score_none():
    """แท่ง D0 หาย ≠ คิดคะแนนไม่ได้ — คนละสาเหตุ คนละทางแก้ ต้องแยกให้ผู้ใช้เห็น"""
    state = {"AAA": _entry()}
    _, _, gone = rescore_entries(state, ["AAA"], lambda s: _bars_without_d0())
    assert gone == {"AAA": "no_d0_bar"}
    _, _, short = rescore_entries(state, ["AAA"], lambda s: _bars_too_short())
    assert short == {"AAA": "score_none"}


def test_rescore_entries_error_on_one_symbol_does_not_abort_the_rest():
    """ตัวเดียวโยน exception ต้องไม่ล้มทั้งลูป (เดิม: ทุกตัวหายจากการตามพร้อมกัน)"""
    def get_bars(sym):
        if sym == "BBB":
            raise RuntimeError("yahoo พัง")
        return _bars(STRONG_POST)

    state = {"AAA": _entry(), "BBB": _entry()}
    entries, pts_map, skipped = rescore_entries(state, ["AAA", "BBB"], get_bars)
    assert [row["symbol"] for row, _ in entries] == ["AAA"]
    assert pts_map["AAA"] >= 10
    assert skipped == {"BBB": "error:RuntimeError"}


def test_run_always_logs_summary_with_skip_reasons(tmp_path, caplog):
    """สรุปทุกรอบแม้ไม่มีตัวไหนคิดสำเร็จ — เดิม log อยู่ใน `if entries:` จึงเงียบสนิทตอนที่ควรดังที่สุด"""
    csv_path = tmp_path / "scan_log.csv"
    state_path = tmp_path / "rescore_state.json"
    run([_picked_row()], {}, lambda s: None, today=date(2026, 8, 4),
        min_pts=10, days=14, csv_path=csv_path, state_path=state_path)
    with caplog.at_level(logging.INFO, logger="bot.rescore"):
        run([], {}, lambda s: _bars_without_d0(), today=date(2026, 8, 11),
            min_pts=10, days=14, csv_path=csv_path, state_path=state_path)
    assert "rescore: คิดซ้ำ 0/1 ตัว → scan_log.csv 0 แถว" in caplog.text
    assert "(ข้าม 1: AAA=no_d0_bar)" in caplog.text
    assert not csv_path.exists()                 # ไม่มี entry = ไม่แตะ CSV เหมือนเดิม


def test_run_logs_when_nothing_is_due(tmp_path, caplog):
    with caplog.at_level(logging.INFO, logger="bot.rescore"):
        run([], {}, lambda s: None, today=date(2026, 8, 11), min_pts=10, days=14,
            csv_path=tmp_path / "scan_log.csv",
            state_path=tmp_path / "rescore_state.json")
    assert "rescore: ไม่มีตัว due วันนี้" in caplog.text


def test_run_logs_success_count_out_of_due(tmp_path, caplog):
    csv_path = tmp_path / "scan_log.csv"
    state_path = tmp_path / "rescore_state.json"
    run([_picked_row()], {}, lambda s: None, today=date(2026, 8, 4),
        min_pts=10, days=14, csv_path=csv_path, state_path=state_path)
    with caplog.at_level(logging.INFO, logger="bot.rescore"):
        run([], {}, lambda s: _bars(STRONG_POST), today=date(2026, 8, 11),
            min_pts=10, days=14, csv_path=csv_path, state_path=state_path)
    assert "rescore: คิดซ้ำ 1/1 ตัว → scan_log.csv 1 แถว" in caplog.text
    assert "ข้าม" not in caplog.text             # ไม่มีตัวข้าม = ไม่ต่อท้าย


def test_skip_streak_counts_up_survives_reload_and_resets(tmp_path):
    """สตรีคการข้ามต้องอยู่รอดข้ามรอบ (save/load) และรีเซ็ตเมื่อกลับมาคิดได้"""
    csv_path = tmp_path / "scan_log.csv"
    state_path = tmp_path / "rescore_state.json"
    run([_picked_row()], {}, lambda s: None, today=date(2026, 8, 4),
        min_pts=10, days=14, csv_path=csv_path, state_path=state_path)
    for streak, day in ((1, 11), (2, 12)):
        run([], {}, lambda s: _bars_without_d0(), today=date(2026, 8, day),
            min_pts=10, days=14, csv_path=csv_path, state_path=state_path)
        ent = load_state(state_path)["AAA"]
        assert ent["skip_streak"] == streak and ent["skip_reason"] == "no_d0_bar"
    run([], {}, lambda s: _bars(STRONG_POST), today=date(2026, 8, 13),
        min_pts=10, days=14, csv_path=csv_path, state_path=state_path)
    ent = load_state(state_path)["AAA"]
    assert ent["skip_streak"] == 0 and ent["skip_reason"] is None
    assert ent["skip_date"] is None


# ── fix รอบ 1 (review U1) — สตรีคต้องนับ "วัน" และต้องรีเซ็ตเมื่อกลับมาติดสแกน ──


def test_skip_streak_counts_days_not_runs(tmp_path):
    """/scan ซ้ำวันเดียวกันต้องไม่เพิ่มสตรีค — "ข้าม 2 วันติด" ต้องแปลว่า 2 วันจริง

    _do_scan_and_send ถูกเรียกทั้งจาก job เช้าและจาก /scan วันเดียวกันได้ — นับเป็นรอบจะกิน
    สิทธิ์ ⚠️ ครั้งเดียวไปตั้งแต่วันแรก แถมบอกวันผิด
    """
    csv_path = tmp_path / "scan_log.csv"
    state_path = tmp_path / "rescore_state.json"
    run([_picked_row()], {}, lambda s: None, today=date(2026, 8, 4),
        min_pts=10, days=14, csv_path=csv_path, state_path=state_path)
    for _ in range(2):                           # job เช้า แล้วผู้ใช้กด /scan ต่อในวันเดียวกัน
        run([], {}, lambda s: _bars_without_d0(), today=date(2026, 8, 11),
            min_pts=10, days=14, csv_path=csv_path, state_path=state_path)
        ent = load_state(state_path)["AAA"]
        assert (ent["skip_streak"], ent["skip_date"]) == (1, "2026-08-11")
    assert stale_entries(load_state(state_path)) == []       # ยังไม่ถึงเกณฑ์เตือน
    run([], {}, lambda s: _bars_without_d0(), today=date(2026, 8, 12),
        min_pts=10, days=14, csv_path=csv_path, state_path=state_path)
    ent = load_state(state_path)["AAA"]
    assert (ent["skip_streak"], ent["skip_date"]) == (2, "2026-08-12")
    assert stale_notice(stale_entries(load_state(state_path)))   # ⚠️ ออกวันที่สองพอดี


def test_skip_streak_resets_when_symbol_is_scanned_again_today(tmp_path):
    """ตัวที่กลับมาติดแถวสแกนวันนี้ = คิดคะแนนสดไปแล้ว ไม่ได้ข้าม → สตรีคต้องล้าง

    due() ตัดตัวที่สแกนรอบนี้คิดไปแล้วออก มันจึงไม่เดินผ่านลูปสตรีค — สตรีคค้างที่ 2 ทำให้
    ตัวกรอง == 2 ของ wiring ส่ง ⚠️ ซ้ำได้ทุกรอบถัดไป และ /status ค้างชื่อไว้ทั้งที่คิดได้แล้ว
    """
    csv_path = tmp_path / "scan_log.csv"
    state_path = tmp_path / "rescore_state.json"
    run([_picked_row()], {}, lambda s: None, today=date(2026, 8, 4),
        min_pts=10, days=14, csv_path=csv_path, state_path=state_path)
    for day in (11, 12):
        run([], {}, lambda s: _bars_without_d0(), today=date(2026, 8, day),
            min_pts=10, days=14, csv_path=csv_path, state_path=state_path)
    assert [s["skip_streak"] for s in stale_entries(load_state(state_path))] == [2]
    # 13 ส.ค. lookback กว้าง (/scan 7) หยิบ AAA กลับเข้าแถวสแกน — คิดสดแล้ว ไม่ใช่ตัวข้าม
    run([_picked_row(d0="2026-08-13")], {}, lambda s: None, today=date(2026, 8, 13),
        min_pts=10, days=14, csv_path=csv_path, state_path=state_path)
    ent = load_state(state_path)["AAA"]
    assert (ent["skip_streak"], ent["skip_reason"], ent["skip_date"]) == (0, None, None)
    assert not ent["stale_notice_due"]                           # ธง ⚠️ ที่ค้างต้องถูกล้างด้วย
    assert stale_entries(load_state(state_path)) == []           # /status ไม่ค้างชื่อไว้
    assert stale_notice(stale_entries(load_state(state_path))) is None    # ไม่ ⚠️ ซ้ำ


# ── fix รอบ 2 — ⚠️ เป็น "เหตุการณ์ 1→2" ที่ run() ปักธงไว้ ไม่ใช่ตัวกรองสภาพ ──


def test_stale_notice_is_armed_on_the_transition_and_popped_once(tmp_path):
    """run() ปักธงตอนสตรีคขึ้นเป็น 2 พอดี · pop_stale_notices คืนครั้งเดียวแล้วล้างธงลงไฟล์

    เดิม wiring กรอง skip_streak == 2 จาก state ใหม่ทุกรอบ — สแกนซ้ำวันเดียวกัน (job แล้ว /scan
    หรือ catch-up) จึงอ่านค่าที่ค้างอยู่แล้วยิง ⚠️ เดิมซ้ำได้ไม่จำกัด
    """
    csv_path = tmp_path / "scan_log.csv"
    state_path = tmp_path / "rescore_state.json"
    run([_picked_row()], {}, lambda s: None, today=date(2026, 8, 4),
        min_pts=10, days=14, csv_path=csv_path, state_path=state_path)
    run([], {}, lambda s: _bars_without_d0(), today=date(2026, 8, 11),
        min_pts=10, days=14, csv_path=csv_path, state_path=state_path)
    assert not load_state(state_path)["AAA"].get("stale_notice_due")     # สตรีค 1 ยังไม่ถึง
    assert pop_stale_notices(state_path) == []
    run([], {}, lambda s: _bars_without_d0(), today=date(2026, 8, 12),
        min_pts=10, days=14, csv_path=csv_path, state_path=state_path)
    assert load_state(state_path)["AAA"]["stale_notice_due"] is True
    assert pop_stale_notices(state_path) == [{"symbol": "AAA", "d0": D0_ISO,
                                              "skip_streak": 2, "skip_reason": "no_d0_bar"}]
    assert pop_stale_notices(state_path) == []                   # ตั๋วใบเดียว กินแล้วหมด
    run([], {}, lambda s: _bars_without_d0(), today=date(2026, 8, 12),
        min_pts=10, days=14, csv_path=csv_path, state_path=state_path)
    assert pop_stale_notices(state_path) == []                   # สแกนซ้ำวันเดิมไม่ปักธงใหม่
    run([], {}, lambda s: _bars_without_d0(), today=date(2026, 8, 13),
        min_pts=10, days=14, csv_path=csv_path, state_path=state_path)
    assert load_state(state_path)["AAA"]["skip_streak"] == 3
    assert pop_stale_notices(state_path) == []                   # ≥3 ไม่ปักอีก (ไปโผล่ที่ /status)


def test_success_clears_an_armed_stale_notice(tmp_path):
    """กลับมาคิดคะแนนได้ก่อนธงถูกกิน (รอบก่อนล้มก่อนส่ง) — ต้องไม่แจ้ง ⚠️ ย้อนหลังทีหลัง"""
    csv_path = tmp_path / "scan_log.csv"
    state_path = tmp_path / "rescore_state.json"
    run([_picked_row()], {}, lambda s: None, today=date(2026, 8, 4),
        min_pts=10, days=14, csv_path=csv_path, state_path=state_path)
    for day in (11, 12):
        run([], {}, lambda s: _bars_without_d0(), today=date(2026, 8, day),
            min_pts=10, days=14, csv_path=csv_path, state_path=state_path)
    assert load_state(state_path)["AAA"]["stale_notice_due"] is True
    run([], {}, lambda s: _bars(STRONG_POST), today=date(2026, 8, 13),
        min_pts=10, days=14, csv_path=csv_path, state_path=state_path)
    ent = load_state(state_path)["AAA"]
    assert ent["stale_notice_due"] is False and ent["skip_streak"] == 0
    assert pop_stale_notices(state_path) == []


def test_pop_stale_notices_tolerates_old_state_without_the_flag(tmp_path):
    """state รูปเก่า (ไม่มีคีย์ stale_notice_due) ต้องอ่านได้ ไม่คืนอะไร ไม่พัง"""
    p = tmp_path / "rescore_state.json"
    p.write_text(json.dumps({"AAA": {"earn_date": D0_ISO, "d0": D0_ISO,
                                     "grade": "D", "qualified": None}}), encoding="utf-8")
    assert pop_stale_notices(p) == []


def test_load_state_accepts_entries_without_skip_fields(tmp_path):
    """state รูปเก่า (ก่อนมี skip_streak/skip_reason) ต้องโหลดได้ตามปกติ ค่าปริยาย 0/None"""
    p = tmp_path / "rescore_state.json"
    p.write_text(json.dumps({"AAA": {"earn_date": D0_ISO, "d0": D0_ISO,
                                     "grade": "D", "qualified": None}}), encoding="utf-8")
    state = load_state(p)
    assert set(state) == {"AAA"}
    assert state["AAA"].get("skip_streak", 0) == 0
    assert state["AAA"].get("skip_reason") is None
    assert stale_entries(state) == []


def test_stale_entries_filters_by_streak_and_sorts_by_symbol():
    state = {"WDAY": _entry(d0="2026-08-28", skip_streak=3, skip_reason="no_d0_bar"),
             "AAA": _entry(skip_streak=2, skip_reason="no_bars"),
             "BBB": _entry(skip_streak=1, skip_reason="no_bars"),
             "CCC": _entry()}
    stale = stale_entries(state)
    assert [s["symbol"] for s in stale] == ["AAA", "WDAY"]
    assert stale[1] == {"symbol": "WDAY", "d0": "2026-08-28",
                        "skip_streak": 3, "skip_reason": "no_d0_bar"}
    assert [s["symbol"] for s in stale_entries(state, min_streak=3)] == ["WDAY"]


def test_stale_notice_says_symbol_streak_and_reason():
    assert stale_notice([]) is None
    assert stale_notice([{"symbol": "WDAY", "d0": "2026-08-28", "skip_streak": 2,
                          "skip_reason": "no_d0_bar"}]) == (
        "⚠️ เกณฑ์ไทย 14 วัน: ข้าม WDAY 2 วันติด — ไม่มีแท่ง D0 2026-08-28 ใน Yahoo")
    for reason, th in (("no_bars", "ดึงราคาไม่ได้"), ("score_none", "คิดคะแนนไม่ได้"),
                       ("error:ValueError", "error ValueError")):
        line = stale_notice([{"symbol": "WDAY", "d0": D0_ISO, "skip_streak": 4,
                              "skip_reason": reason}])
        assert line == f"⚠️ เกณฑ์ไทย 14 วัน: ข้าม WDAY 4 วันติด — {th}"
    both = stale_notice([{"symbol": "AAA", "d0": D0_ISO, "skip_streak": 2, "skip_reason": "no_bars"},
                         {"symbol": "WDAY", "d0": D0_ISO, "skip_streak": 2, "skip_reason": "no_bars"}])
    assert len(both.splitlines()) == 2           # บรรทัดละตัว


# ── wiring _do_scan_and_send (พฤติกรรมจริง เสริม inspect.getsource ด้านบน) ──

_WIRE_SCAN = {"from_date": "2026-08-31", "to_date": "2026-09-01", "universe_size": 500,
              "reported_symbols": ["WDAY"], "candidates": [], "pending": [], "rows": [],
              "skipped_counts": {"C": 0, "D": 0, "down": 0}}


class _FrozenDatetime(datetime):
    """08:30 ไทย 1 ก.ย. — นอกช่วง 20:00–05:00 ที่แท่ง US อาจยังไม่ปิด (guard _us_market_maybe_open ปิด)"""
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 9, 1, 8, 30)


def _drive_scan(monkeypatch, rescore_run=None, auto_add=lambda symbols: ([], []),
                scan=None, get_bars=lambda s, days=250: None):
    """เรียก _do_scan_and_send ของจริง — patch record_signals/auto_add/watchlist ทุกครั้ง (ไฟล์จริงของเครื่อง)

    rescore_run=None → ใช้ rescore.run ตัวจริง (state/CSV ชี้ tmp โดย conftest) ป้อนแท่งราคาจาก get_bars
    คืน (ข้อความที่ส่งตามลำดับ, ลำดับการเรียก, cands ที่ส่งเข้า record_signals)
    """
    from bot import main
    from bot.config import Config

    sent, order, sig_calls = [], [], []
    monkeypatch.setattr(main, "CONFIG", Config(telegram_token="123:ABC", chat_id="1",
                                               fmp_api_key="k"))
    monkeypatch.setattr(main, "datetime", _FrozenDatetime)
    monkeypatch.setattr(main, "run_scan",
                        lambda config, lookback, secondary_cal_fn=None: scan or _WIRE_SCAN)
    monkeypatch.setattr(main, "save_reports", lambda scan, messages: None)
    monkeypatch.setattr(main, "record_signals", lambda cands, flag_date: (
        sig_calls.append(cands), order.append("record_signals"), [])[-1])
    monkeypatch.setattr(main, "record_scan_csv", lambda entries, scan_date, path=None: 0)
    monkeypatch.setattr(main, "load_watchlist", lambda: [])
    monkeypatch.setattr(main, "auto_add", auto_add)
    monkeypatch.setattr(main, "_send_chart", _noop_chart)
    if rescore_run is None:
        monkeypatch.setattr(main, "get_prices", get_bars)
        monkeypatch.setattr(main, "prefetch", lambda symbols, *a, **k: None)
    else:
        monkeypatch.setattr(main.rescore, "run",
                            lambda *a, **k: (order.append("rescore.run"), rescore_run(*a, **k))[-1])

    class Bot:
        async def send_message(self, chat_id, text, **kw):
            sent.append(text)

    asyncio.run(main._do_scan_and_send(Bot(), "1", 2))
    return sent, order, sig_calls


async def _noop_chart(bot, chat_id, symbol, levels=None, caption=None, reply_markup=None):
    pass


def test_scan_records_set_cross_right_after_rescore_run(monkeypatch):
    """rescore.run ถูกเรียกจริง แล้ว record_signals(signal_candidates(crossed)) ตามหลัง (feedback loop SET≥10)"""
    crossed = [{"symbol": "AAA", "pts": 11, "days_after": 5, "grade": "D",
                "earn_date": D0_ISO, "d0": D0_ISO, "price": 111.0,
                "since_pct": 12.12, "pre_low": 98.0}]
    sent, order, sig_calls = _drive_scan(monkeypatch, lambda *a, **k: crossed)
    assert order == ["record_signals", "rescore.run", "record_signals"]
    assert sig_calls[1] == signal_candidates(crossed)
    assert any("⭐ ข้ามเกณฑ์ไทยครั้งแรก" in t and "AAA" in t for t in sent)


def test_scan_notifies_symbols_evicted_from_auto_watch(monkeypatch):
    """หลุดเพดาน auto-watch ต้องบอก ไม่งั้นผู้ใช้เชื่อว่ายังเฝ้าอยู่"""
    sent, _, _ = _drive_scan(monkeypatch, lambda *a, **k: [],
                             auto_add=lambda symbols: ([], ["OLD"]))
    evicted = [t for t in sent if t.startswith("➖ หลุดจากติดตามอัตโนมัติ")]
    assert len(evicted) == 1 and "OLD" in evicted[0]


def test_scan_report_is_sent_before_rescore_failure_is_reported(monkeypatch):
    """rescore ล้ม → รายงานสแกนต้องส่งไปแล้ว + แจ้งล้มต่อท้าย (ไม่ทำทั้งวันหาย)"""
    def boom(*a, **k):
        raise RuntimeError("state พัง")

    sent, _, _ = _drive_scan(monkeypatch, boom)
    assert len(sent) == 2
    assert "Earnings Screener" in sent[0]        # รายงานสแกนออกไปก่อน
    assert sent[1].startswith("⚠️ เกณฑ์ไทยมีชีวิต (rescore) ล้มวันนี้")


def _seed_stale_state(**over):
    """เขียน rescore_state.json (path ที่ conftest redirect) — WDAY ข้ามมาแล้ว 1 วัน (d0 อยู่ในกรอบ 14 วัน)"""
    from bot import rescore as rescore_mod
    ent = {"earn_date": "2026-08-24", "d0": "2026-08-25", "grade": "B", "qualified": None,
           "skip_streak": 1, "skip_reason": "no_d0_bar", "skip_date": "2026-08-31"}
    ent.update(over)
    rescore_mod.STATE_PATH.write_text(json.dumps({"WDAY": ent}), encoding="utf-8")


_STALE_WARN = "⚠️ เกณฑ์ไทย 14 วัน: ข้าม WDAY 2 วันติด — ไม่มีแท่ง D0 2026-08-25 ใน Yahoo"


def _warns(sent):
    return [t for t in sent if t.startswith("⚠️ เกณฑ์ไทย 14 วัน")]


def test_scan_sends_stale_notice_once_even_when_run_twice_the_same_day(monkeypatch):
    """job เช้า แล้วผู้ใช้กด /scan ต่อวันเดียวกัน — ⚠️ ต้องออกใบเดียว (rescore.run ตัวจริง)

    เดิม wiring กรอง skip_streak == 2 จาก state ใหม่ทุกรอบ ค่าที่ค้างอยู่จึงยิงข้อความเดิมซ้ำทุกครั้ง
    """
    _seed_stale_state()
    warns = []
    for _ in range(2):
        sent, _, _ = _drive_scan(monkeypatch, get_bars=lambda s, days=250: _bars_without_d0())
        warns += _warns(sent)
    assert warns == [_STALE_WARN]
    from bot import rescore as rescore_mod
    assert rescore_mod.load_state()["WDAY"]["skip_streak"] == 2       # สแกนซ้ำวันเดิมไม่เพิ่มสตรีค


def test_scan_does_not_warn_again_on_the_next_day(monkeypatch):
    """วันถัดไปสตรีค 3 — เงียบ ไปโผล่ที่ /status แทน"""
    _seed_stale_state()
    _drive_scan(monkeypatch, get_bars=lambda s, days=250: _bars_without_d0())
    sent, _, _ = _drive_scan(monkeypatch, scan={**_WIRE_SCAN, "to_date": "2026-09-02"},
                             get_bars=lambda s, days=250: _bars_without_d0())
    assert _warns(sent) == []
    from bot import rescore as rescore_mod
    assert rescore_mod.load_state()["WDAY"]["skip_streak"] == 3


def test_scan_pops_the_armed_flag_so_the_next_run_is_silent(monkeypatch):
    """ธงที่ run() ปักไว้ = ตั๋วใบเดียว — wiring กินแล้วรอบถัดไปเงียบ (rescore.run stub)"""
    _seed_stale_state(skip_streak=2, skip_date="2026-09-01", stale_notice_due=True)
    sent, _, _ = _drive_scan(monkeypatch, lambda *a, **k: [])
    assert _warns(sent) == [_STALE_WARN]
    sent, _, _ = _drive_scan(monkeypatch, lambda *a, **k: [])
    assert _warns(sent) == []


def test_scan_does_not_warn_for_stale_symbol_without_armed_flag(monkeypatch):
    """สตรีค ≥3 ที่ธงถูกกินไปแล้ว — /status ยังโชว์ แต่ไม่ยิงข้อความซ้ำ"""
    _seed_stale_state(skip_streak=3, skip_date="2026-09-01")
    sent, _, _ = _drive_scan(monkeypatch, lambda *a, **k: [])
    assert _warns(sent) == []
