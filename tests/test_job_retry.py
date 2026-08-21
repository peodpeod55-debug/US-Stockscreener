"""Retry ของ job เช้า (_run_claimed ใน bot/main.py)

บั๊กเดิม: claim ก่อนทำงานแล้วไม่คืนเมื่อล้ม — เน็ตสะดุดตอน 08:20-08:30 =
job หายทั้งวันเงียบๆ (catch-up เห็น already_ran แล้วข้าม) และ breakout/
reminder/weekly ล้มโดยไม่แจ้งผู้ใช้เลย

พฤติกรรมใหม่: ล้ม → คืน claim + แจ้งผู้ใช้ → catch-up (วนทุก 30 นาที) ลองใหม่
ล้มครบ JOB_MAX_TRIES ครั้ง → เก็บ claim ไว้ (เลิกลองวันนี้) กันสแปม/เผางบ API
"""
import asyncio
from types import SimpleNamespace

import pytest
from apscheduler.triggers.interval import IntervalTrigger

from bot import jobstate
from bot import main
from bot.config import Config

DUMMY_CONFIG = Config(telegram_token="123:ABC", chat_id="1", fmp_api_key="k")


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id=None, text=None, **kwargs):
        self.sent.append(text)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """ชี้ claim/release ไปที่ state file ชั่วคราว + config หลอก + ล้างตัวนับล้ม"""
    state = tmp_path / "job_state.json"
    monkeypatch.setattr(main, "claim",
                        lambda name: jobstate.claim(name, path=state))
    monkeypatch.setattr(main, "release",
                        lambda name: jobstate.release(name, path=state))
    monkeypatch.setattr(main, "CONFIG", DUMMY_CONFIG)
    main._fail_counts.clear()
    bot = FakeBot()
    return SimpleNamespace(state=state, bot=bot, ctx=SimpleNamespace(bot=bot))


def _run(env, name, work):
    return asyncio.run(main._run_claimed(env.ctx, name, work))


def test_success_claims_and_stays_quiet(env):
    ran = []

    async def work():
        ran.append(1)

    _run(env, "scan", work)
    assert ran == [1]
    assert jobstate.already_ran("scan", path=env.state) is True
    assert env.bot.sent == []


def test_already_claimed_skips_work(env):
    ran = []

    async def work():
        ran.append(1)

    _run(env, "scan", work)
    _run(env, "scan", work)
    assert ran == [1]


def test_failure_releases_claim_and_notifies(env):
    async def work():
        raise RuntimeError("FMP down")

    _run(env, "scan", work)
    # claim ถูกคืน → catch-up รอบถัดไปรันใหม่ได้
    assert jobstate.already_ran("scan", path=env.state) is False
    assert len(env.bot.sent) == 1
    assert "ลองใหม่" in env.bot.sent[0]
    assert "FMP down" in env.bot.sent[0]


def test_gives_up_after_max_tries(env):
    async def work():
        raise RuntimeError("FMP down")

    for _ in range(main.JOB_MAX_TRIES):
        _run(env, "scan", work)
    # ครบเพดาน → เก็บ claim ไว้ (เลิกลองวันนี้) + ข้อความสุดท้ายบอกว่าหยุดแล้ว
    assert jobstate.already_ran("scan", path=env.state) is True
    assert len(env.bot.sent) == main.JOB_MAX_TRIES
    assert "หยุดลอง" in env.bot.sent[-1]
    # เรียกซ้ำอีกก็ไม่ทำงานแล้ว
    ran = []

    async def ok():
        ran.append(1)

    _run(env, "scan", ok)
    assert ran == []


def test_notify_failure_does_not_mask_release(env):
    """ส่งข้อความแจ้งเตือนล้มเหลว (เน็ตดับหมด) — claim ต้องถูกคืนไปแล้ว"""
    async def work():
        raise RuntimeError("boom")

    async def broken_send(chat_id=None, text=None, **kwargs):
        raise OSError("no network")

    env.bot.send_message = broken_send
    _run(env, "scan", work)
    assert jobstate.already_ran("scan", path=env.state) is False


def test_catchup_scheduled_repeating():
    """catch-up ต้องวนซ้ำ (เดิม run_once ตอน start) — เป็นกลไก retry ของ job ที่ล้ม"""
    app = main.build_app(DUMMY_CONFIG)
    jobs = [j for j in app.job_queue.jobs() if j.callback is main.catchup_job]
    assert jobs
    trigger = jobs[0].job.trigger
    assert isinstance(trigger, IntervalTrigger)
    assert trigger.interval.total_seconds() == main.CATCHUP_INTERVAL
