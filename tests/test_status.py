"""คำสั่ง /status (พิมพ์ "สถานะ" ก็ได้): สุขภาพบอทดูจากมือถือ — ไม่ต้องเปิด bot.log

ตอบคำถาม ops ที่ถามบ่อยสุด: บอทรันอยู่ไหม/โค้ดที่รันตรง HEAD ไหม (ต้อง restart?),
job เช้าวันนี้รันครบหรือยัง, รอตอบรับกี่ตัว, FMP 402 วันนี้กี่ตัว, มี error ไหม
"""
import asyncio
import json
import os
from datetime import date, datetime, time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from telegram.ext import CommandHandler

import bot.main as m
import bot.status as status
from bot.config import Config
from bot.formatter import MAX_LEN, format_status
from bot.status import (
    build_status,
    job_states,
    latest_scan,
    read_head_commit,
    scan_log_today,
)

TZ = ZoneInfo("Asia/Bangkok")
THU = date(2026, 8, 27)         # พฤหัส — วันที่มี job เช้าครบทุกตัวยกเว้น weekly
SUN = date(2026, 8, 30)
DUMMY_CONFIG = Config(telegram_token="123:ABC", chat_id="1", fmp_api_key="k")


def _at(d, h, mi=0):
    return datetime.combine(d, time(h, mi), tzinfo=TZ)


# ── job_states: สถานะ job เช้าเทียบ job_state.json + เวลาตอนนี้ ──────────


def _by_name(items):
    return {j["name"]: j for j in items}


def test_all_morning_jobs_done_on_weekday_afternoon():
    today = THU.isoformat()
    st = {"breakout": today, "reminder": today, "scan": today, "weekly": "2026-08-23"}
    jobs = _by_name(job_states(_at(THU, 14), st))
    assert jobs["breakout"]["state"] == "done"
    assert jobs["reminder"]["state"] == "done"
    assert jobs["scan"]["state"] == "done"
    assert jobs["weekly"]["state"] == "done"         # ส่งแล้วเมื่ออาทิตย์ 23 ส.ค. = รอบสัปดาห์นี้
    assert jobs["weekly"]["last"] == "2026-08-23"


def test_job_not_yet_due_is_pending():
    st = {"breakout": THU.isoformat()}
    jobs = _by_name(job_states(_at(THU, 8, 22), st))
    assert jobs["breakout"]["state"] == "done"
    assert jobs["reminder"]["state"] == "pending"    # 08:25 ยังไม่ถึง
    assert jobs["scan"]["state"] == "pending"


def test_job_past_time_but_not_run_is_due():
    jobs = _by_name(job_states(_at(THU, 9), {}))
    assert jobs["breakout"]["state"] == "due"
    assert jobs["reminder"]["state"] == "due"
    assert jobs["scan"]["state"] == "due"
    assert jobs["breakout"]["last"] is None


def test_yesterdays_run_does_not_count_as_today():
    jobs = _by_name(job_states(_at(THU, 9), {"scan": "2026-08-26"}))
    assert jobs["scan"]["state"] == "due"
    assert jobs["scan"]["last"] == "2026-08-26"


def test_sunday_only_reminder_and_weekly_have_rounds():
    jobs = _by_name(job_states(_at(SUN, 9, 30), {}))
    assert jobs["breakout"]["state"] == "off"
    assert jobs["scan"]["state"] == "off"
    assert jobs["reminder"]["state"] == "due"
    assert jobs["weekly"]["state"] == "due"


def test_job_states_keep_schedule_order_and_time():
    jobs = job_states(_at(THU, 9), {})
    assert [j["name"] for j in jobs] == ["breakout", "reminder", "scan", "weekly"]
    assert jobs[2]["time"] == time(8, 30)


# ── scan_log_today: นับ 402 / warning / error เฉพาะวันนี้จาก bot.log ────

LOG = [
    "2026-08-26 09:14:38,607 WARNING bot network hiccup (PTB retry เอง): Bad Gateway",
    "2026-08-27 08:30:01,000 INFO bot.fmp FMP 402 not in plan: https://financialmodelingprep.com/stable/historical-price-eod/full {'symbol': 'HD', 'from': '2025-09-01'}",
    "2026-08-27 08:30:02,000 INFO bot.fmp FMP 402 not in plan: https://financialmodelingprep.com/stable/earnings {'symbol': 'HD'}",
    "2026-08-27 08:30:03,000 INFO bot.fmp FMP 402 not in plan: https://financialmodelingprep.com/api/v3/historical-price-full/BRK.B {'from': '2025-09-01'}",
    "2026-08-27 08:30:04,000 WARNING bot.fmp FMP timeout: https://financialmodelingprep.com/stable/quote {'symbol': 'NVDA'}",
    "2026-08-27 08:31:00,000 ERROR bot scan job failed",
    "Traceback (most recent call last):",
    "  File x, line 1",
    "2026-08-27 08:45:00,000 ERROR bot unhandled error (update=None)",
]


def test_402_symbols_unique_from_params_and_path():
    out = scan_log_today(LOG, "2026-08-27")
    assert out["fmp_402"] == ["HD", "BRK.B"]      # HD โดน 2 endpoint นับตัวเดียว


def test_counts_only_todays_warnings_and_errors():
    out = scan_log_today(LOG, "2026-08-27")
    assert out["warnings"] == 1                   # ของ 26 ส.ค. ไม่นับ
    assert out["errors"] == 2                     # บรรทัด traceback ไม่ใช่ error ใหม่


def test_last_error_text_is_message_without_timestamp():
    out = scan_log_today(LOG, "2026-08-27")
    assert out["last_error"] == "unhandled error (update=None)"


def test_quiet_day_has_zero_counts_and_no_error():
    out = scan_log_today(LOG, "2026-08-28")
    assert out == {"fmp_402": [], "warnings": 0, "errors": 0, "last_error": None}


# ── read_head_commit: commit ที่ HEAD ชี้ (ไม่ใช้ git CLI — เครื่องที่รันไม่มีก็ได้) ──


def _git(tmp_path, head, refs=None, packed=None):
    g = tmp_path / ".git"
    g.mkdir()
    (g / "HEAD").write_text(head, encoding="utf-8")
    for ref, sha in (refs or {}).items():
        p = g / ref
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(sha + "\n", encoding="utf-8")
    if packed:
        (g / "packed-refs").write_text(packed, encoding="utf-8")
    return tmp_path


def test_head_via_branch_ref_file(tmp_path):
    root = _git(tmp_path, "ref: refs/heads/master\n",
                refs={"refs/heads/master": "9a0896fdec0b2e2cf124720759cfdef59dab415b"})
    assert read_head_commit(root) == "9a0896f"


def test_head_via_packed_refs_when_loose_ref_missing(tmp_path):
    packed = ("# pack-refs with: peeled fully-peeled sorted\n"
              "1111111aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa refs/heads/other\n"
              "2222222bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb refs/heads/master\n")
    root = _git(tmp_path, "ref: refs/heads/master\n", packed=packed)
    assert read_head_commit(root) == "2222222"


def test_detached_head_is_the_hash_itself(tmp_path):
    root = _git(tmp_path, "abcdef0123456789abcdef0123456789abcdef01\n")
    assert read_head_commit(root) == "abcdef0"


def test_no_git_dir_returns_none(tmp_path):
    assert read_head_commit(tmp_path) is None


def test_real_repo_head_matches_git_layout():
    # โปรเจคนี้เป็น git repo จริง — ต้องอ่านได้ 7 ตัวอักษร hex
    sha = read_head_commit()
    assert sha is not None and len(sha) == 7
    int(sha, 16)


# ── latest_scan: สรุปไฟล์ reports/scan_*.json ล่าสุด ───────────────────


def _scan_file(d, stamp, candidates=(), skipped=None, pending=0, calls=22):
    data = {"from_date": "2026-08-25", "to_date": "2026-08-27", "universe_size": 566,
            "reported_symbols": [], "candidates": list(candidates),
            "skipped_counts": skipped or {}, "pending": [{}] * pending,
            "api_stats": {"api_calls_made": calls, "max_api_calls": 200}}
    (d / f"scan_{stamp}.json").write_text(json.dumps(data), encoding="utf-8")


def test_latest_scan_picks_newest_stamp(tmp_path):
    _scan_file(tmp_path, "2026-08-26_091007", candidates=[{"symbol": "EL", "grade": "B"}])
    _scan_file(tmp_path, "2026-08-27_083021", skipped={"C": 2, "D": 1}, pending=18)
    s = latest_scan(tmp_path)
    assert s["at"] == datetime(2026, 8, 27, 8, 30, 21)
    assert s["candidates"] == []
    assert s["skipped"] == {"C": 2, "D": 1}
    assert s["pending"] == 18
    assert s["api_calls"] == (22, 200)


def test_latest_scan_lists_candidates_symbol_and_grade(tmp_path):
    _scan_file(tmp_path, "2026-08-21_153741",
               candidates=[{"symbol": "EL", "grade": "B", "score": 79.5},
                           {"symbol": "TGT", "grade": "B", "score": 72.8}])
    assert latest_scan(tmp_path)["candidates"] == [("EL", "B"), ("TGT", "B")]


def test_latest_scan_none_when_no_reports(tmp_path):
    assert latest_scan(tmp_path) is None
    assert latest_scan(tmp_path / "missing") is None


def test_latest_scan_corrupt_file_returns_none(tmp_path):
    (tmp_path / "scan_2026-08-27_083021.json").write_text("{", encoding="utf-8")
    assert latest_scan(tmp_path) is None


# ── build_status: ประกอบทุกแหล่งเป็น dict เดียว (path ฉีดได้ทั้งหมด) ───────


def _state_files(tmp_path):
    (tmp_path / "job_state.json").write_text(json.dumps(
        {"breakout": "2026-08-27", "reminder": "2026-08-27", "scan": "2026-08-27",
         "weekly": "2026-08-23"}), encoding="utf-8")
    (tmp_path / "pending.json").write_text(json.dumps(
        [{"symbol": "NVDA", "date": "2026-08-26", "timing": "amc"},
         {"symbol": "CRWD", "date": "2026-08-26", "timing": "amc"}]), encoding="utf-8")
    (tmp_path / "watchlist.json").write_text(json.dumps(["AAPL"]), encoding="utf-8")
    (tmp_path / "auto_watch.json").write_text(json.dumps(
        {"EL": "2026-08-22", "TGT": "2026-08-22", "OLD": "2026-01-01"}), encoding="utf-8")
    (tmp_path / "signals.json").write_text(json.dumps(
        [{"symbol": "EL", "grade": "B", "flag_date": "2026-08-21"},
         {"symbol": "TGT", "grade": "B", "flag_date": "2026-08-21"}]), encoding="utf-8")
    (tmp_path / "bot.log").write_text("\n".join(LOG) + "\n", encoding="utf-8")
    reports = tmp_path / "reports"
    reports.mkdir()
    _scan_file(reports, "2026-08-27_083021", skipped={"C": 2, "D": 1}, pending=2)
    return dict(job_state_path=tmp_path / "job_state.json",
                pending_path=tmp_path / "pending.json",
                watchlist_path=tmp_path / "watchlist.json",
                auto_watch_path=tmp_path / "auto_watch.json",
                signals_path=tmp_path / "signals.json",
                log_path=tmp_path / "bot.log",
                reports_dir=reports)


def test_build_status_assembles_all_sources(tmp_path):
    now = _at(THU, 14, 5)
    started = _at(THU, 9, 3)
    st = build_status(now, started_at=started, started_commit="9a0896f",
                      head_commit="9a0896f", **_state_files(tmp_path))
    assert st["now"] == now
    assert st["pid"] == os.getpid()
    assert st["started_at"] == started
    assert st["started_commit"] == "9a0896f" and st["head_commit"] == "9a0896f"
    assert _by_name(st["jobs"])["scan"]["state"] == "done"
    assert st["pending"] == ["NVDA", "CRWD"]
    assert st["watch_manual"] == ["AAPL"]
    assert st["watch_auto"] == ["EL", "TGT"]           # OLD หมดอายุ 30 วันแล้ว
    assert st["signals_total"] == 2
    assert st["last_signal"] == {"symbol": "TGT", "grade": "B", "flag_date": "2026-08-21"}
    assert st["log"]["fmp_402"] == ["HD", "BRK.B"]
    assert st["log"]["errors"] == 2
    assert st["scan"]["pending"] == 2
    assert st["rescore"] == {"tracked": 0, "stale": []}     # rescore_state.json ว่าง (conftest redirect)


def test_build_status_survives_missing_files(tmp_path):
    st = build_status(_at(THU, 14), started_at=None, started_commit=None,
                      head_commit=None,
                      job_state_path=tmp_path / "j.json", pending_path=tmp_path / "p.json",
                      watchlist_path=tmp_path / "w.json", auto_watch_path=tmp_path / "a.json",
                      signals_path=tmp_path / "s.json", log_path=tmp_path / "bot.log",
                      reports_dir=tmp_path / "reports")
    assert st["pending"] == [] and st["watch_manual"] == [] and st["watch_auto"] == []
    assert st["signals_total"] == 0 and st["last_signal"] is None
    assert st["log"] == {"fmp_402": [], "warnings": 0, "errors": 0, "last_error": None}
    assert st["scan"] is None
    assert _by_name(st["jobs"])["scan"]["state"] == "due"


def test_build_status_defaults_to_process_start_info(tmp_path, monkeypatch):
    # ค่าเริ่มต้น = ตอน import โมดูล (≈ process start) — โค้ดที่โหลดตอนนั้นคือที่รันอยู่
    started = _at(THU, 9, 3)
    monkeypatch.setattr(status, "STARTED_AT", started)
    monkeypatch.setattr(status, "STARTED_COMMIT", "1234567")
    st = build_status(_at(THU, 14), **_state_files(tmp_path))
    assert st["started_at"] == started
    assert st["started_commit"] == "1234567"
    assert st["head_commit"] == read_head_commit()


def test_module_records_start_time_and_commit_at_import():
    assert isinstance(status.STARTED_AT, datetime)
    assert status.STARTED_AT.tzinfo is not None
    assert status.STARTED_COMMIT == read_head_commit()


# ── format_status ────────────────────────────────────────────────


def _status(**over):
    base = {
        "now": _at(THU, 14, 5), "pid": 13920,
        "started_at": _at(THU, 9, 3), "started_commit": "9a0896f", "head_commit": "9a0896f",
        "jobs": [
            {"name": "breakout", "time": time(8, 20), "state": "done", "last": "2026-08-27"},
            {"name": "reminder", "time": time(8, 25), "state": "done", "last": "2026-08-27"},
            {"name": "scan", "time": time(8, 30), "state": "done", "last": "2026-08-27"},
            {"name": "weekly", "time": time(9, 0), "state": "off", "last": "2026-08-23"},
        ],
        "pending": ["BILI", "NVDA", "CRWD", "CRM", "SNPS", "A", "VEEV", "TCOM",
                    "HPQ", "MRVL", "ADSK", "WDAY"],
        "watch_manual": [], "watch_auto": ["EL", "TGT"],
        "signals_total": 2,
        "last_signal": {"symbol": "TGT", "grade": "B", "flag_date": "2026-08-21"},
        "log": {"fmp_402": ["HD", "BRK.B"], "warnings": 1, "errors": 0, "last_error": None},
        "scan": {"at": datetime(2026, 8, 27, 8, 30, 21), "candidates": [],
                 "skipped": {"C": 2, "D": 1}, "pending": 18, "api_calls": (22, 200)},
        "rescore": {"tracked": 9, "stale": []},
    }
    base.update(over)
    return base


def test_format_status_header_pid_uptime_and_matching_commit():
    msg = format_status(_status())
    assert "2026-08-27 14:05" in msg
    assert "PID 13920" in msg
    assert "เริ่ม 09:03" in msg
    assert "5 ชม. 2 น." in msg
    assert "9a0896f" in msg and "✅" in msg.split("\n")[2]


def test_format_status_warns_when_head_is_newer_than_running_code():
    msg = format_status(_status(head_commit="abc1234"))
    assert "9a0896f" in msg and "abc1234" in msg
    assert "restart" in msg and "⚠️" in msg


def test_format_status_unknown_start_and_commit():
    msg = format_status(_status(started_at=None, started_commit=None, head_commit=None))
    assert "ไม่ทราบ" in msg
    assert "restart" not in msg


def test_format_status_job_icons_per_state():
    jobs = [
        {"name": "breakout", "time": time(8, 20), "state": "done", "last": "2026-08-27"},
        {"name": "reminder", "time": time(8, 25), "state": "due", "last": "2026-08-26"},
        {"name": "scan", "time": time(8, 30), "state": "pending", "last": None},
        {"name": "weekly", "time": time(9, 0), "state": "off", "last": "2026-08-23"},
    ]
    lines = format_status(_status(jobs=jobs)).split("\n")
    assert any(l.startswith("✅") and "ทะลุแนว 08:20" in l for l in lines)
    due = next(l for l in lines if l.startswith("❌"))
    assert "เตือนงบ 08:25" in due and "catch-up" in due and "2026-08-26" in due
    assert any(l.startswith("⏳") and "สแกน 08:30" in l for l in lines)
    off = next(l for l in lines if l.startswith("—"))
    assert "สรุปสัปดาห์ 09:00" in off and "2026-08-23" in off


def test_format_status_pending_truncated_after_ten():
    msg = format_status(_status())
    assert "รอตอบรับงบ 12" in msg
    assert "MRVL +2" in msg
    assert "ADSK" not in msg


def test_format_status_watch_signals_and_log_counts():
    msg = format_status(_status())
    assert "manual 0" in msg and "auto 2 (EL TGT)" in msg
    assert "สัญญาณสะสม 2" in msg and "TGT B (2026-08-21)" in msg
    assert "402 = 2 ตัว (HD BRK.B)" in msg
    assert "เตือน 1" in msg and "error 0" in msg


def test_format_status_shows_last_error_when_present():
    log = {"fmp_402": [], "warnings": 0, "errors": 3,
           "last_error": "scan job failed"}
    msg = format_status(_status(log=log))
    assert "error 3" in msg and "scan job failed" in msg


def test_format_status_latest_scan_line():
    msg = format_status(_status())
    assert "สแกนล่าสุด 2026-08-27 08:30" in msg
    assert "A/B 0" in msg and "C=2 D=1" in msg and "รอ 18" in msg and "API 22/200" in msg


def test_format_status_scan_candidates_and_no_scan():
    scan = _status()["scan"] | {"candidates": [("EL", "B"), ("TGT", "B")]}
    assert "A/B 2 (EL:B TGT:B)" in format_status(_status(scan=scan))
    assert "ยังไม่เคยสแกน" in format_status(_status(scan=None))


def test_format_status_thai_rule_line_without_stale():
    """เกณฑ์ไทย 14 วัน: บอกจำนวนที่ตามอยู่ · ไม่มีตัวข้ามค้าง = ไม่มีท่อนหลัง"""
    msg = format_status(_status())
    assert "เกณฑ์ไทย: ตาม 9 ตัว" in msg
    assert "ข้ามติดกัน" not in msg


def test_format_status_thai_rule_line_lists_stale_symbols():
    """ตัวที่ข้ามติดกัน ≥2 วัน ต้องโผล่ที่ /status (⚠️ แจ้งครั้งเดียวตอนสตรีค 2 แล้วเงียบ)"""
    stale = [{"symbol": "WDAY", "d0": "2026-08-28", "skip_streak": 3,
              "skip_reason": "no_d0_bar"}]
    msg = format_status(_status(rescore={"tracked": 9, "stale": stale}))
    assert "เกณฑ์ไทย: ตาม 9 ตัว · ข้ามติดกัน ≥2 วัน: WDAY (no_d0_bar ×3)" in msg


def test_build_status_reads_stale_symbols_from_rescore_state(tmp_path):
    """build_status อ่าน rescore_state.json ผ่าน path ที่ฉีดได้ (เหมือนทุกแหล่งอื่นในฟังก์ชันนี้)"""
    path = tmp_path / "rescore_state.json"
    path.write_text(json.dumps({
        "WDAY": {"earn_date": "2026-08-27", "d0": "2026-08-28", "grade": "B",
                 "qualified": None, "skip_streak": 3, "skip_reason": "no_d0_bar",
                 "skip_date": "2026-08-27"},
        "EL": {"earn_date": "2026-08-21", "d0": "2026-08-22", "grade": "B",
               "qualified": None},
    }), encoding="utf-8")
    st = build_status(_at(THU, 14, 5), rescore_state_path=path, **_state_files(tmp_path))
    assert st["rescore"]["tracked"] == 2
    assert st["rescore"]["stale"] == [{"symbol": "WDAY", "d0": "2026-08-28",
                                       "skip_streak": 3, "skip_reason": "no_d0_bar"}]


def test_format_status_uptime_in_days_and_fits_message_limit():
    msg = format_status(_status(started_at=_at(date(2026, 8, 25), 9, 3),
                                pending=[f"S{i}" for i in range(40)],
                                watch_manual=[f"M{i}" for i in range(20)]))
    assert "2 วัน 5 ชม." in msg
    assert len(msg) <= MAX_LEN


# ── wiring ใน main: /status + พิมพ์ "สถานะ"/"status" ──────────────────


def test_status_command_registered():
    app = m.build_app(DUMMY_CONFIG)
    cmds = {c for h in app.handlers[0] if isinstance(h, CommandHandler) for c in h.commands}
    assert "status" in cmds


def _fake_update(text):
    replies = []

    async def reply_text(t, **kw):
        replies.append(t)
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=1),
        message=SimpleNamespace(text=text, reply_text=reply_text)), replies


def _capture_send(monkeypatch):
    calls = []

    async def fake_send(bot, chat_id):
        calls.append(chat_id)
    monkeypatch.setattr(m, "CONFIG", DUMMY_CONFIG)
    monkeypatch.setattr(m, "_send_status", fake_send)
    return calls


def test_thai_and_english_text_aliases_route_to_status(monkeypatch):
    calls = _capture_send(monkeypatch)
    for text in ("สถานะ", " status ", "STATUS"):
        update, _ = _fake_update(text)
        asyncio.run(m.on_text(update, SimpleNamespace(bot=None)))
    assert calls == [1, 1, 1]


def test_cmd_status_sends_to_chat(monkeypatch):
    calls = _capture_send(monkeypatch)
    update, _ = _fake_update("/status")
    asyncio.run(m.cmd_status(update, SimpleNamespace(bot=None, args=[])))
    assert calls == [1]


def test_cmd_status_ignores_unauthorized_chat(monkeypatch):
    calls = _capture_send(monkeypatch)
    update, _ = _fake_update("/status")
    update.effective_chat.id = 999
    asyncio.run(m.cmd_status(update, SimpleNamespace(bot=None, args=[])))
    assert calls == []


def test_status_failure_reports_to_user_not_crash(monkeypatch):
    monkeypatch.setattr(m, "CONFIG", DUMMY_CONFIG)

    async def boom(bot, chat_id):
        raise RuntimeError("disk gone")
    monkeypatch.setattr(m, "_send_status", boom)
    update, replies = _fake_update("สถานะ")
    asyncio.run(m.on_text(update, SimpleNamespace(bot=None)))
    assert replies and "⚠️" in replies[0]


def test_help_mentions_status(monkeypatch):
    monkeypatch.setattr(m, "CONFIG", DUMMY_CONFIG)
    update, replies = _fake_update("/help")
    asyncio.run(m.cmd_help(update, SimpleNamespace(bot=None, args=[])))
    assert "/status" in replies[0]
