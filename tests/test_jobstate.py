from datetime import date, datetime

from bot.jobstate import already_ran, claim, due_catchup, release

TUE = date(2026, 8, 18)
WED = date(2026, 8, 19)


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
