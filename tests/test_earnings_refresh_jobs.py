"""reminder_job / weekly_job ต้องวิ่งผ่าน refresh คลังวันงบได้จริง (regression)

บั๊กเดิม (เข้ามาใน 8c99939): main.py ใช้ timedelta ใน reminder_job/weekly_job
แต่บรรทัด import มีแค่ date, datetime, time → NameError ทุกเช้า 08:25 (เตือนวันงบตาย)
และทุกอาทิตย์ 09:00 (สรุปรายสัปดาห์ + ดึงปฏิทิน 35 วันตาย) — เห็นใน bot.log 2026-08-29
test เดิมไม่มีตัวไหนวิ่งเข้า work() ของสอง job นี้ เลยไม่มีใครจับได้
"""
import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from bot import jobstate, main
from bot.config import Config

DUMMY_CONFIG = Config(telegram_token="123:ABC", chat_id="1", fmp_api_key="k")


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id=None, text=None, **kwargs):
        self.sent.append(text)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """claim/release ไป state ชั่วคราว + config หลอก + refresh คลังวันงบเป็นตัวจับ argument"""
    state = tmp_path / "job_state.json"
    monkeypatch.setattr(main, "claim", lambda name: jobstate.claim(name, path=state))
    monkeypatch.setattr(main, "release", lambda name: jobstate.release(name, path=state))
    monkeypatch.setattr(main, "CONFIG", DUMMY_CONFIG)
    main._fail_counts.clear()
    calls = []
    monkeypatch.setattr(main, "refresh",
                        lambda sources, d_from, d_to, today: calls.append((d_from, d_to, today)))
    monkeypatch.setattr(main, "default_sources", lambda client, key: [])
    bot = FakeBot()
    return SimpleNamespace(state=state, bot=bot, ctx=SimpleNamespace(bot=bot), calls=calls)


def test_reminder_job_refreshes_store_ahead(env, monkeypatch):
    monkeypatch.setattr(main, "all_watched", lambda: [])   # ไม่มีหุ้นติดตาม → จบหลัง refresh
    asyncio.run(main.reminder_job(env.ctx))
    today = datetime.now(main.TZ).date()
    assert env.calls == [(today.isoformat(),
                          (today + timedelta(days=main.REFRESH_AHEAD_DAYS)).isoformat(),
                          today)]
    assert env.bot.sent == []          # ไม่มีข้อความ "ลองใหม่" = work() ไม่ล้ม
    assert jobstate.already_ran("reminder", path=env.state) is True


def test_weekly_job_refreshes_store_to_35_days(env, monkeypatch):
    sunday = datetime(2026, 8, 30, 9, 0, tzinfo=main.TZ)   # วันอาทิตย์ — job นี้รันเฉพาะอาทิตย์

    class FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return sunday

    monkeypatch.setattr(main, "datetime", FakeDatetime)
    sent = []

    async def fake_send_weekly(bot, chat_id):
        sent.append(chat_id)

    monkeypatch.setattr(main, "_send_weekly", fake_send_weekly)
    asyncio.run(main.weekly_job(env.ctx))
    today = sunday.date()
    assert env.calls == [((today + timedelta(days=main.REFRESH_AHEAD_DAYS + 1)).isoformat(),
                          (today + timedelta(days=main.REFRESH_WEEKLY_DAYS)).isoformat(),
                          today)]
    assert sent == ["1"]
    assert env.bot.sent == []
