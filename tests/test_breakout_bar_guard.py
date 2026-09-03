"""breakout_job: ข้ามแจ้งซ้ำถ้าแท่งล่าสุด (prices[0]) เหมือนรอบก่อนเป๊ะ

บั๊กเดิม: หลังวันหยุด US (เช่น Labor Day จันทร์) รอบอังคาร 08:20 ดึงแท่งชุดเดิมกับรอบเสาร์
ที่ผ่านมา (Yahoo ยังไม่มีแท่งใหม่) → new_breaks/sl_break/gap_pullback ชุดเดิมถูกคำนวณซ้ำ
record_breakouts dedup เฉพาะที่ breakouts.json แต่ข้อความ Telegram มาจาก alerts ตรงๆ จึง
ส่งซ้ำทุกครั้ง — HK มี bar_state กันเรื่องนี้อยู่แล้ว (HK Stock Screener/bot/jobs.py) US ไม่มี
งานนี้เติม last_bar guard ผ่าน job_state.json (bot/jobstate.last_breakout_bar/set_breakout_bar)
"""
import asyncio
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from bot import jobstate, main, status
from bot.config import Config

TZ = main.TZ
DUMMY_CONFIG = Config(telegram_token="123:ABC", chat_id="1", fmp_api_key="k")
# วันอังคารหลัง Labor Day (จันทร์ 2026-09-07) — เคสจริงที่ทำให้เจอบั๊ก
NOW = datetime(2026, 9, 8, 8, 20, tzinfo=TZ)


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id=None, text=None, **kwargs):
        self.sent.append(text)

    async def send_photo(self, **kwargs):
        pass  # _send_chart หา prices ใน fetch_cache ไม่เจอ (เทสไม่ได้ใส่) จะไม่ถูกเรียกจริง


class FakeDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


def _snap(symbol, last_date, **over):
    """snapshot ขั้นต่ำที่ format_breakouts/format_low_breaks/below_low_5d ต้องการครบ

    ค่าเริ่มต้น: ทะลุ high_5d (new_breaks ไม่ว่าง) และ "ไม่" หลุด low_5d
    (levels["price"] > levels["low_5d"]) — override เฉพาะเคสที่ต้องการให้หลุด
    """
    base = {
        "symbol": symbol, "name": symbol, "price": 102.0, "low": 99.0,
        "day_change_pct": 2.0, "vol_ratio": 1.5, "dr_symbols": "", "grade": "A",
        "levels": {"high_5d": 100.0, "low_5d": 90.0, "sl": 90.0,
                  "d0_open": 95.0, "d0_high": 101.0, "price": 102.0},
        "new_breaks": ["high_5d"], "sl_break": False, "low_break": False,
        "gap_pullback": False, "last_date": last_date,
    }
    base.update(over)
    return base


@pytest.fixture
def env(tmp_path, monkeypatch):
    """เดินสาย breakout_job ให้ครบโดยไม่แตะไฟล์จริง/เครือข่ายจริง

    แพทเทิร์นเดียวกับ test_job_retry.py (claim/release → state ชั่วคราว) +
    test_earnings_refresh_jobs.py (all_watched/FakeDatetime) — all_watched/lookup_symbol/
    prefetch/active_auto/auto_remove/record_breakouts ปลอมทั้งหมด กัน Yahoo/FMP จริงตาม
    ข้อกำหนดงาน (conftest บล็อก Yahoo อยู่แล้ว แต่ FMPClient จริงยังยิงเน็ตได้ถ้าไม่ปลอม
    lookup_symbol/prefetch)
    """
    state = tmp_path / "job_state.json"
    monkeypatch.setattr(main, "claim", lambda name: jobstate.claim(name, path=state))
    monkeypatch.setattr(main, "release", lambda name: jobstate.release(name, path=state))
    monkeypatch.setattr(main, "CONFIG", DUMMY_CONFIG)
    monkeypatch.setattr(main, "datetime", FakeDatetime)
    monkeypatch.setattr(main, "prefetch", lambda symbols, days, client: None)
    monkeypatch.setattr(main, "active_auto", lambda: {})
    main._fail_counts.clear()

    snaps = {}
    monkeypatch.setattr(main, "all_watched", lambda: list(snaps))
    monkeypatch.setattr(main, "lookup_symbol",
                        lambda client, sym, universe: snaps.get(sym))
    record_calls = []
    monkeypatch.setattr(main, "record_breakouts",
                        lambda alerts: record_calls.append(list(alerts)))
    remove_calls = []
    monkeypatch.setattr(main, "auto_remove",
                        lambda dead: remove_calls.append(list(dead)) or [])
    bot = FakeBot()
    return SimpleNamespace(snaps=snaps, state=state, bot=bot,
                           ctx=SimpleNamespace(bot=bot),
                           record_calls=record_calls, remove_calls=remove_calls)


def _run(env):
    asyncio.run(main.breakout_job(env.ctx))


# ── a. รอบแรก (ยังไม่มี last_bar เก็บไว้) ────────────────────────

def test_first_run_no_stored_bar_sends_and_stores_date(env):
    env.snaps["NVDA"] = _snap("NVDA", "2026-09-08")
    _run(env)
    assert any("NVDA" in m for m in env.bot.sent)
    assert env.record_calls == [[env.snaps["NVDA"]]]
    assert jobstate.last_breakout_bar(path=env.state) == "2026-09-08"


# ── b. แท่งเหมือนรอบก่อนเป๊ะ (วันหยุด/ยังไม่มีแท่งใหม่) ─────────────

def test_duplicate_bar_skips_send_and_state_writes(env, monkeypatch):
    # NVDA อยู่ใน auto-watch และปิดต่ำกว่า low_5d จงใจ — ถ้า guard ไม่ทำงานจริง
    # dead จะไม่ว่าง (auto_remove ถูกเรียก) และ alerts ก็ไม่ว่าง (record_breakouts/ส่งข้อความ)
    # การที่ทั้งสามอย่างไม่เกิดขึ้นเลยจึงพิสูจน์ว่า guard ตัดตั้งแต่ก่อนถึงจุดเหล่านั้นจริง
    monkeypatch.setattr(main, "active_auto", lambda: {"NVDA": "2026-08-01"})
    env.snaps["NVDA"] = _snap(
        "NVDA", "2026-09-08",
        levels={"high_5d": 100.0, "low_5d": 200.0, "sl": 90.0,
               "d0_open": 95.0, "d0_high": 101.0, "price": 102.0})
    jobstate.set_breakout_bar("2026-09-08", path=env.state)  # รอบก่อนประมวลผลแท่งนี้ไปแล้ว

    _run(env)

    assert env.bot.sent == []
    assert env.record_calls == []
    assert env.remove_calls == []
    assert jobstate.last_breakout_bar(path=env.state) == "2026-09-08"


# ── c. แท่งใหม่กว่ารอบก่อน ────────────────────────────────────────

def test_newer_bar_sends_and_updates_stored_date(env):
    jobstate.set_breakout_bar("2026-09-04", path=env.state)  # แท่งศุกร์ก่อนวันหยุด
    env.snaps["NVDA"] = _snap("NVDA", "2026-09-08")           # แท่งอังคารใหม่จริง

    _run(env)

    assert any("NVDA" in m for m in env.bot.sent)
    assert env.record_calls == [[env.snaps["NVDA"]]]
    assert jobstate.last_breakout_bar(path=env.state) == "2026-09-08"


# ── d. ดึงราคาไม่ได้เลยสักตัว (Yahoo/FMP ล่ม) ─────────────────────

def test_all_fetches_empty_no_crash_bar_unchanged(env):
    jobstate.set_breakout_bar("2026-09-04", path=env.state)
    env.snaps["NVDA"] = None  # ติดตามอยู่ แต่ดึงราคาไม่ได้จากทุกแหล่ง

    _run(env)  # ต้องไม่ throw

    assert env.bot.sent == []
    assert env.record_calls == [[]]     # ยังเรียกเหมือนพฤติกรรมเดิม (ด้วยลิสต์ว่าง)
    assert env.remove_calls == []
    assert jobstate.last_breakout_bar(path=env.state) == "2026-09-04"  # ไม่ถูกแตะ


# ── e. คีย์ breakout_bar ต้องไม่ทำให้ due_catchup/claim/status งง ──

def test_breakout_bar_key_ignored_by_catchup_claim_and_status(tmp_path):
    path = tmp_path / "job_state.json"
    jobstate.set_breakout_bar("2026-09-08", path=path)

    # claim/already_ran ของชื่อ job จริงยังทำงานปกติ แม้มีคีย์ breakout_bar ปนอยู่ในไฟล์เดียวกัน
    assert jobstate.claim("scan", path=path, today=date(2026, 9, 8)) is True
    assert jobstate.already_ran("scan", path=path, today=date(2026, 9, 8)) is True

    # due_catchup ขับเคลื่อนด้วย SCHEDULE ไม่ใช่คีย์ในไฟล์ — breakout_bar ไม่มีวันหลุดออกมา
    assert "breakout_bar" not in jobstate.due_catchup(NOW)

    # status.job_states อ่านทีละชื่อจาก SCHEDULE เหมือนกัน — ไม่หยิบ breakout_bar มาโชว์เป็น job
    states = status.job_states(NOW, jobstate._load(path))
    assert {s["name"] for s in states} == {"breakout", "reminder", "scan", "weekly"}
