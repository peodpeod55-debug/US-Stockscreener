"""แท่งวันศุกร์ต้องไม่หายเมื่อเสาร์ไม่เปิดเครื่อง + weekly ตามเก็บได้ทั้งสัปดาห์ + บูตรอเน็ต

เหตุ (รีวิว 12 พ.ย. 2026 — docs/review-2026-11-12.md ของ Stock-lab):
- breakout/scan รันเฉพาะ อ.–ส. → เสาร์ไม่เปิดเครื่อง = เตือนทะลุแนว/หลุด SL ของ session ศุกร์หายถาวร
  (detector เทียบ 1 แท่ง) — 19 ต.ค.–10 พ.ย. หาย 4/17 session รวมศุกร์ 6 พ.ย. กลางพีคงบ · รายงานงบ พฤ.-AMC/ศ.
  ไปออกวันอังคาร
- weekly รันได้เฉพาะวันอาทิตย์ → ไม่ได้ส่ง 8 สัปดาห์ติด (ล่าสุด 13 ก.ย.) ทั้งที่ cohort set_cross โตถึง 69
- PTB บูตตอนเน็ตยังไม่พร้อมแล้วยอมแพ้ทันที → process ตาย + ERROR เท็จใน /status
"""
import asyncio
from datetime import date, datetime, time
from types import SimpleNamespace

import pytest

from bot import jobstate, main, status
from bot.config import Config
from bot.jobstate import already_ran, claim, due_catchup, release

TZ = main.TZ
DUMMY_CONFIG = Config(telegram_token="123:ABC", chat_id="1", fmp_api_key="k")
FRI = date(2026, 11, 6)
SAT = date(2026, 11, 7)
SUN = date(2026, 11, 8)
MON = date(2026, 11, 9)
WED = date(2026, 11, 11)
NEXT_SUN = date(2026, 11, 15)
NEXT_MON = date(2026, 11, 16)


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id=None, text=None, **kwargs):
        self.sent.append(text)

    async def send_photo(self, **kwargs):
        pass


def _freeze(monkeypatch, when):
    class FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return when

    monkeypatch.setattr(main, "datetime", FakeDatetime)


def _snap(symbol, last_date):
    return {
        "symbol": symbol, "name": symbol, "price": 102.0, "low": 99.0,
        "day_change_pct": 2.0, "vol_ratio": 1.5, "dr_symbols": "", "grade": "A",
        "levels": {"high_5d": 100.0, "low_5d": 90.0, "sl": 90.0,
                   "d0_open": 95.0, "d0_high": 101.0, "price": 102.0},
        "new_breaks": ["high_5d"], "sl_break": False, "low_break": False,
        "gap_pullback": False, "last_date": last_date,
    }


@pytest.fixture
def env(tmp_path, monkeypatch):
    """เดินสาย job จริงโดยไม่แตะไฟล์/เครือข่ายจริง (แพทเทิร์นเดียวกับ test_breakout_bar_guard.py)"""
    state = tmp_path / "job_state.json"
    monkeypatch.setattr(main, "claim", lambda name: jobstate.claim(name, path=state))
    monkeypatch.setattr(main, "release", lambda name: jobstate.release(name, path=state))
    monkeypatch.setattr(main, "CONFIG", DUMMY_CONFIG)
    monkeypatch.setattr(main, "prefetch", lambda symbols, days, client: None)
    monkeypatch.setattr(main, "active_auto", lambda: {})
    main._fail_counts.clear()
    snaps = {}
    monkeypatch.setattr(main, "all_watched", lambda: list(snaps))
    monkeypatch.setattr(main, "lookup_symbol", lambda client, sym, universe: snaps.get(sym))
    recorded = []
    monkeypatch.setattr(main, "record_breakouts", lambda alerts: recorded.append(list(alerts)))
    monkeypatch.setattr(main, "auto_remove", lambda dead: [])
    bot = FakeBot()
    return SimpleNamespace(snaps=snaps, state=state, bot=bot, ctx=SimpleNamespace(bot=bot),
                           recorded=recorded)


# ── วันจันทร์: เก็บ session ศุกร์ที่รอบเสาร์พลาด ─────────────────────

def test_monday_morning_breakout_and_scan_are_due():
    assert due_catchup(datetime(2026, 11, 9, 8, 35)) == ["breakout", "reminder", "scan"]


def test_monday_breakout_alerts_friday_bar_when_saturday_was_missed(env, monkeypatch):
    _freeze(monkeypatch, datetime(2026, 11, 9, 8, 20, tzinfo=TZ))
    env.snaps["NVDA"] = _snap("NVDA", FRI.isoformat())          # แท่งล่าสุด = ศุกร์ ยังไม่เคยประมวลผล
    asyncio.run(main.breakout_job(env.ctx))
    assert any("NVDA" in m for m in env.bot.sent)
    assert env.recorded == [[env.snaps["NVDA"]]]
    assert jobstate.last_breakout_bar(path=env.state) == FRI.isoformat()


def test_monday_breakout_stays_quiet_when_saturday_already_processed_friday(env, monkeypatch):
    _freeze(monkeypatch, datetime(2026, 11, 9, 8, 20, tzinfo=TZ))
    env.snaps["NVDA"] = _snap("NVDA", FRI.isoformat())
    jobstate.set_breakout_bar(FRI.isoformat(), path=env.state)  # รอบเสาร์แจ้งแท่งนี้ไปแล้ว
    asyncio.run(main.breakout_job(env.ctx))
    assert env.bot.sent == []
    assert env.recorded == []
    # รอบจันทร์ "รันแล้วข้ามเอง" (guard แท่งซ้ำ) ไม่ใช่ "ไม่ได้รัน" — /status ต้องเห็นว่าทำแล้ว
    assert jobstate.last_run("breakout", path=env.state) is not None


def test_monday_scan_runs_and_widens_back_to_friday(env, monkeypatch):
    """เสาร์ไม่ได้สแกน (ล่าสุดศุกร์) → จันทร์สแกนย้อน 3 วันครอบงบวันศุกร์"""
    _freeze(monkeypatch, datetime(2026, 11, 9, 8, 30, tzinfo=TZ))
    monkeypatch.setattr(main, "last_run", lambda name: FRI)
    calls = []

    async def fake_scan(bot, chat_id, lookback):
        calls.append(lookback)

    monkeypatch.setattr(main, "_do_scan_and_send", fake_scan)
    asyncio.run(main.daily_job(env.ctx))
    assert calls == [3]


def test_sunday_still_has_no_breakout_or_scan_round(env, monkeypatch):
    """อาทิตย์ไม่เพิ่ม: แท่งเดียวกับเสาร์ และรอบจันทร์เก็บให้แล้ว (กันรายงานสแกนเปล่าวันหยุด)"""
    _freeze(monkeypatch, datetime(2026, 11, 8, 8, 30, tzinfo=TZ))
    env.snaps["NVDA"] = _snap("NVDA", FRI.isoformat())
    calls = []

    async def fake_scan(bot, chat_id, lookback):
        calls.append(lookback)

    monkeypatch.setattr(main, "_do_scan_and_send", fake_scan)
    asyncio.run(main.breakout_job(env.ctx))
    asyncio.run(main.daily_job(env.ctx))
    assert env.bot.sent == [] and calls == []


# ── weekly: ส่งครั้งแรกที่เครื่องเปิดในสัปดาห์นั้น (anchor = วันอาทิตย์ล่าสุด) ─────────

def test_weekly_is_due_on_any_day_after_nine():
    assert due_catchup(datetime(2026, 11, 9, 9, 30)) == ["breakout", "reminder", "scan", "weekly"]
    assert "weekly" in due_catchup(datetime(2026, 11, 11, 14, 0))       # พุธบ่าย
    assert "weekly" not in due_catchup(datetime(2026, 11, 9, 8, 59))    # ยังไม่ถึง 09:00


def test_weekly_claimed_on_sunday_blocks_rest_of_that_week(tmp_path):
    p = tmp_path / "job_state.json"
    assert claim("weekly", path=p, today=SUN) is True
    assert claim("weekly", path=p, today=MON) is False
    assert already_ran("weekly", path=p, today=WED) is True
    assert already_ran("weekly", path=p, today=SAT + (NEXT_SUN - SUN)) is True   # เสาร์ 14 พ.ย. ยังสัปดาห์เดิม


def test_weekly_missed_on_sunday_is_claimable_on_first_open_day(tmp_path):
    p = tmp_path / "job_state.json"
    claim("weekly", path=p, today=date(2026, 9, 13))                    # ล่าสุดจริงของเครื่อง: 13 ก.ย.
    assert already_ran("weekly", path=p, today=MON) is False
    assert claim("weekly", path=p, today=MON) is True
    assert already_ran("weekly", path=p, today=WED) is True             # ส่งจันทร์แล้ว พุธไม่ซ้ำ


def test_weekly_new_week_opens_on_next_sunday_even_if_last_sent_midweek(tmp_path):
    p = tmp_path / "job_state.json"
    claim("weekly", path=p, today=WED)
    assert already_ran("weekly", path=p, today=NEXT_SUN) is False
    assert claim("weekly", path=p, today=NEXT_MON) is True


def test_weekly_release_same_day_allows_retry(tmp_path):
    p = tmp_path / "job_state.json"
    claim("weekly", path=p, today=MON)
    assert release("weekly", path=p, today=MON) is True
    assert claim("weekly", path=p, today=MON) is True


def test_daily_jobs_still_claim_once_per_day(tmp_path):
    p = tmp_path / "job_state.json"
    assert claim("scan", path=p, today=SUN) is True
    assert claim("scan", path=p, today=MON) is True                     # รายวันไม่ติด anchor สัปดาห์


@pytest.fixture
def weekly_env(env, monkeypatch):
    monkeypatch.setattr(main, "refresh", lambda sources, d_from, d_to, today: None)
    monkeypatch.setattr(main, "default_sources", lambda client, key: [])
    sent = []

    async def fake_send_weekly(bot, chat_id):
        sent.append(chat_id)

    monkeypatch.setattr(main, "_send_weekly", fake_send_weekly)
    env.weekly_sent = sent
    return env


def _weekly_on(env, monkeypatch, day):
    """รัน weekly_job ราวกับวันนี้คือ day 09:00 (ทั้งนาฬิกาของ main และวันของ claim)"""
    _freeze(monkeypatch, datetime.combine(day, time(9, 0), tzinfo=TZ))
    monkeypatch.setattr(main, "claim",
                        lambda name: jobstate.claim(name, path=env.state, today=day))
    asyncio.run(main.weekly_job(env.ctx))


def test_weekly_job_sends_on_monday_when_sunday_was_missed(weekly_env, monkeypatch):
    jobstate.claim("weekly", path=weekly_env.state, today=date(2026, 9, 13))
    _weekly_on(weekly_env, monkeypatch, MON)
    assert weekly_env.weekly_sent == ["1"]


def test_weekly_job_sends_only_once_per_week(weekly_env, monkeypatch):
    _weekly_on(weekly_env, monkeypatch, SUN)
    _weekly_on(weekly_env, monkeypatch, MON)
    _weekly_on(weekly_env, monkeypatch, WED)
    assert weekly_env.weekly_sent == ["1"]
    _weekly_on(weekly_env, monkeypatch, NEXT_MON)                       # สัปดาห์ใหม่ (อาทิตย์ 15 ไม่เปิดเครื่อง)
    assert weekly_env.weekly_sent == ["1", "1"]


# ── /status: weekly นับเป็นรอบของสัปดาห์ ไม่ใช่ "ไม่มีรอบวันนี้" ─────────────

def _weekly_state(now, last):
    jobs = {j["name"]: j for j in status.job_states(now, {"weekly": last} if last else {})}
    return jobs["weekly"]["state"]


def test_status_weekly_done_when_sent_earlier_this_week():
    assert _weekly_state(datetime(2026, 11, 11, 14, 0, tzinfo=TZ), MON.isoformat()) == "done"
    assert _weekly_state(datetime(2026, 11, 11, 14, 0, tzinfo=TZ), SUN.isoformat()) == "done"


def test_status_weekly_due_when_not_sent_this_week():
    assert _weekly_state(datetime(2026, 11, 11, 14, 0, tzinfo=TZ), "2026-09-13") == "due"
    assert _weekly_state(datetime(2026, 11, 11, 14, 0, tzinfo=TZ), None) == "due"


def test_status_weekly_pending_before_nine():
    assert _weekly_state(datetime(2026, 11, 11, 8, 40, tzinfo=TZ), "2026-09-13") == "pending"


def test_status_line_shows_which_day_weekly_went_out():
    """✅ ของ weekly ในวันที่ไม่ได้ส่งวันนี้ ต้องบอกวันที่ส่ง — ไม่งั้นอ่านเป็น "ส่งวันนี้" """
    from bot.formatter import format_status
    st = {"now": datetime(2026, 11, 11, 14, 0, tzinfo=TZ), "pid": 1, "started_at": None,
          "started_commit": None, "head_commit": None,
          "jobs": [{"name": "weekly", "time": time(9, 0), "state": "done", "last": MON.isoformat()},
                   {"name": "scan", "time": time(8, 30), "state": "done", "last": WED.isoformat()}],
          "pending": [], "watch_manual": [], "watch_auto": [], "signals_total": 0,
          "last_signal": None,
          "log": {"fmp_402": [], "warnings": 0, "errors": 0, "last_error": None},
          "scan": None, "rescore": {"tracked": 0, "stale": []}}
    lines = format_status(st).split("\n")
    weekly_line = next(l for l in lines if "สรุปสัปดาห์" in l)
    scan_line = next(l for l in lines if "สแกน 08:30" in l)
    assert weekly_line.startswith("✅") and MON.isoformat() in weekly_line
    assert WED.isoformat() not in scan_line                              # รายวันส่งวันนี้ ไม่ต้องบอกวัน


# ── บูตตอนเน็ตยังไม่มา: ลองต่อจนติด ไม่ตายทิ้ง ERROR ───────────────────

def test_main_waits_for_network_at_boot(monkeypatch):
    polling = []
    app = SimpleNamespace(run_polling=lambda **k: polling.append(k))
    monkeypatch.setattr(main, "setup_logging", lambda: None)
    monkeypatch.setattr(main.instance_lock, "acquire", lambda port=None: object())
    monkeypatch.setattr(main, "load_config", lambda: DUMMY_CONFIG)
    monkeypatch.setattr(main, "build_app", lambda config: app)
    monkeypatch.setattr(main, "CONFIG", None)
    main.main()
    assert len(polling) == 1
    assert polling[0].get("bootstrap_retries", 0) < 0       # ค่าเริ่มต้น 0 = ล้มครั้งแรกแล้ว process ตาย
    assert "allowed_updates" in polling[0]                  # ของเดิมต้องอยู่ครบ


# ── weekly ยาวเกินเพดาน Telegram (ฤดูงบ: 94 สัญญาณใน 30 วัน ≈ 8,500 ตัวอักษร) ─────────
# เปิด weekly กลับมาโดยไม่แบ่งข้อความ = "Message is too long" → job ล้ม 3 ครั้งแล้วเลิก

def _weekly_items(n):
    return [{"symbol": f"SYM{i:03d}", "name": "X", "grade": "B", "score": 77.0,
             "signal_type": "set_cross" if i % 2 else "composite",
             "flag_date": "2026-11-04", "flag_price": 100.0 + i, "sl": 90.0,
             "price_now": 103.0 + i, "pct": float(i % 7) - 3.0, "days": 6, "sl_hit": None}
            for i in range(n)]


def test_send_weekly_splits_long_report_under_telegram_limit(env, monkeypatch):
    items = _weekly_items(94)
    monkeypatch.setattr(main, "signals_since", lambda days: items)
    monkeypatch.setattr(main, "build_weekly_items", lambda signals, get_prices: items)
    asyncio.run(main._send_weekly(env.bot, "1"))
    assert len(env.bot.sent) > 1
    assert all(len(m.encode("utf-16-le")) // 2 <= 4096 for m in env.bot.sent)   # Telegram นับ UTF-16 units
    whole = "\n".join(env.bot.sent)
    assert all(it["symbol"] in whole for it in items)                           # ไม่มีตัวไหนหล่น
    assert whole.count("รวม 94 ตัว") == 1                                        # บรรทัดสรุปมีครั้งเดียว
    # ไม่ผ่ากลางรายการ: บรรทัดหัว (ชื่อ) กับบรรทัด "ตอนนี้ …" ของตัวเดียวกันอยู่ฉบับเดียวกัน
    for m in env.bot.sent:
        assert m.count("แจ้ง 2026-11-04") == m.count("   ตอนนี้ ")


def test_send_weekly_short_report_stays_one_message(env, monkeypatch):
    items = _weekly_items(3)
    monkeypatch.setattr(main, "signals_since", lambda days: items)
    monkeypatch.setattr(main, "build_weekly_items", lambda signals, get_prices: items)
    asyncio.run(main._send_weekly(env.bot, "1"))
    assert len(env.bot.sent) == 1
