import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

from bot.jobstate import (already_ran, claim, due_catchup, last_run, release,
                          widen_lookback, write_alive)

TUE = date(2026, 8, 18)
WED = date(2026, 8, 19)
TZ = ZoneInfo("Asia/Bangkok")


# ── claim / already_ran (state file) ─────────────────────────────

def test_first_claim_succeeds(tmp_path):
    p = tmp_path / "job_state.json"
    assert claim("scan", path=p, today=TUE) is True


def test_second_claim_same_day_fails(tmp_path):
    p = tmp_path / "job_state.json"
    claim("scan", path=p, today=TUE)
    assert claim("scan", path=p, today=TUE) is False
    assert already_ran("scan", path=p, today=TUE) is True


def test_claim_next_day_succeeds_again(tmp_path):
    p = tmp_path / "job_state.json"
    claim("scan", path=p, today=TUE)
    assert claim("scan", path=p, today=WED) is True


def test_jobs_claim_independently(tmp_path):
    p = tmp_path / "job_state.json"
    claim("scan", path=p, today=TUE)
    assert already_ran("breakout", path=p, today=TUE) is False
    assert claim("breakout", path=p, today=TUE) is True


def test_missing_or_corrupt_file_treated_as_never_ran(tmp_path):
    p = tmp_path / "job_state.json"
    assert already_ran("scan", path=p, today=TUE) is False
    p.write_text("not json", encoding="utf-8")
    assert already_ran("scan", path=p, today=TUE) is False
    assert claim("scan", path=p, today=TUE) is True


# ── release (job ล้ม → คืน claim ให้ลองใหม่ได้) ──────────────────

def test_release_allows_reclaim_same_day(tmp_path):
    p = tmp_path / "job_state.json"
    claim("scan", path=p, today=TUE)
    assert release("scan", path=p, today=TUE) is True
    assert already_ran("scan", path=p, today=TUE) is False
    assert claim("scan", path=p, today=TUE) is True


def test_release_other_day_claim_untouched(tmp_path):
    # claim ของเมื่อวานไม่ใช่ของเรา — ห้ามลบ (release เจาะจงวันนี้เท่านั้น)
    p = tmp_path / "job_state.json"
    claim("scan", path=p, today=TUE)
    assert release("scan", path=p, today=WED) is False
    assert already_ran("scan", path=p, today=TUE) is True


def test_release_without_claim_is_noop(tmp_path):
    p = tmp_path / "job_state.json"
    assert release("scan", path=p, today=TUE) is False


# ── due_catchup (pure — job ไหนถึงเวลาแล้ววันนี้) ────────────────

def test_before_first_job_nothing_due():
    assert due_catchup(datetime(2026, 8, 18, 8, 0)) == []       # อังคาร 08:00


def test_mid_morning_partial():
    assert due_catchup(datetime(2026, 8, 18, 8, 22)) == ["breakout"]


def test_after_all_morning_jobs_on_push_day():
    # อังคาร 09:30 — breakout/reminder/scan ผ่านหมด, weekly ไม่ใช่วันอาทิตย์
    assert due_catchup(datetime(2026, 8, 18, 9, 30)) == [
        "breakout", "reminder", "scan"]


def test_sunday_has_reminder_and_weekly_only():
    assert due_catchup(datetime(2026, 8, 23, 9, 30)) == ["reminder", "weekly"]


def test_monday_reminder_only():
    # จันทร์ไม่ใช่วัน push (ตลาด US หยุดเสาร์-อาทิตย์) แต่เตือนวันงบรันทุกวัน
    assert due_catchup(datetime(2026, 8, 24, 9, 30)) == ["reminder"]


def test_evening_us_session_nothing_due():
    # อังคาร 21:00 — ตลาด US เปิดอยู่ แท่ง [0] จาก Yahoo ยังไม่ปิด
    # ห้าม catch-up job เช้า (breakout/scan จะเขียน state ถาวรจากแท่งครึ่งวัน)
    assert due_catchup(datetime(2026, 8, 18, 21, 0)) == []


def test_catchup_window_upper_bound():
    # 19:59 ยังเก็บตกได้ · 20:00 ปิดหน้าต่าง (ตลาด US เปิดเร็วสุด 20:30 ไทยช่วง DST)
    assert due_catchup(datetime(2026, 8, 18, 19, 59)) == [
        "breakout", "reminder", "scan"]
    assert due_catchup(datetime(2026, 8, 18, 20, 0)) == []


# ── last_run / widen_lookback (เครื่องปิดหลายวัน → สแกนย้อนให้ครอบ) ──

def test_last_run_reads_claimed_date(tmp_path):
    p = tmp_path / "job_state.json"
    assert last_run("scan", path=p) is None
    claim("scan", path=p, today=TUE)
    assert last_run("scan", path=p) == TUE


def test_last_run_ignores_corrupt_value(tmp_path):
    p = tmp_path / "job_state.json"
    p.write_text('{"scan": "not-a-date"}', encoding="utf-8")
    assert last_run("scan", path=p) is None


def test_widen_lookback_covers_downtime_gap():
    today = date(2026, 8, 18)
    assert widen_lookback(2, None, today) == 2              # ไม่เคยรัน → ค่าปกติ
    assert widen_lookback(2, date(2026, 8, 17), today) == 2  # เมื่อวานรัน → ค่าปกติ
    assert widen_lookback(2, date(2026, 8, 13), today) == 5  # หาย 5 วัน → ย้อน 5
    assert widen_lookback(2, date(2026, 7, 1), today) == 14  # หายนาน → เพดาน 14
    assert widen_lookback(2, date(2026, 7, 1), today, cap=7) == 7


# ── write_alive (heartbeat ให้ tools/bot_watchdog.py ดู mtime) ───

def test_write_alive_writes_ts_isoformat(tmp_path):
    p = tmp_path / "a.json"
    write_alive(datetime(2026, 8, 25, 9, 0, tzinfo=TZ), p)
    assert json.loads(p.read_text(encoding="utf-8")) == {
        "ts": "2026-08-25T09:00:00+07:00"}


def test_write_alive_unwritable_path_logs_warning_not_raises(tmp_path, caplog):
    # เขียนทับ path ที่เป็นโฟลเดอร์ (ไม่ใช่ไฟล์) — OSError แต่ต้องไม่ raise ออกมา
    bad = tmp_path / "a_dir"
    bad.mkdir()
    with caplog.at_level("WARNING"):
        write_alive(datetime(2026, 8, 25, 9, 0, tzinfo=TZ), bad)
    # เจาะจง logger "bot.jobstate" + ข้อความมี "last_alive.json" — กัน WARNING ของ lib อื่นสอบผ่านมั่ว
    warnings = [r for r in caplog.records
                if r.levelname == "WARNING" and r.name == "bot.jobstate"]
    assert warnings
    assert "last_alive.json" in warnings[0].getMessage()
