"""ปักเวลา job รายวันที่ลงทะเบียนจริงใน build_app — กันงาน 21:00/22:00 (openbell)
แอบกลับมาเงียบๆ หลังถอดออก และยืนยันว่างานหลักยังตั้งเวลาไม่ขยับ (แพ็ค B)"""
import asyncio
import json

from apscheduler.triggers.interval import IntervalTrigger

from bot import jobstate
from bot.config import Config, PROJECT_ROOT
from bot.main import alive_job, build_app

DUMMY_CONFIG = Config(telegram_token="123:ABC", chat_id="1", fmp_api_key="k")


def test_daily_jobs_scheduled_at_us_times():
    app = build_app(DUMMY_CONFIG)
    times = {}
    for j in app.job_queue.jobs():
        trig = j.job.trigger
        fields = {f.name: str(f) for f in getattr(trig, "fields", [])}
        if "hour" in fields:
            times.setdefault(j.callback.__name__, set()).add(
                (fields["hour"], fields["minute"]))
    assert times["daily_job"] == {("8", "30")}
    assert times["reminder_job"] == {("8", "25")}
    assert times["breakout_job"] == {("8", "20")}
    assert times["weekly_job"] == {("9", "0")}
    assert "openbell_job" not in times
    all_slots = {slot for slots in times.values() for slot in slots}
    assert ("21", "0") not in all_slots
    assert ("22", "0") not in all_slots


def test_alive_job_scheduled_every_5_minutes():
    """heartbeat ให้ watchdog นอก process (tools/bot_watchdog.py) — ต้องวนทุก 300 วิ (แพ็ค C)"""
    app = build_app(DUMMY_CONFIG)
    jobs = [j for j in app.job_queue.jobs() if j.callback is alive_job]
    assert jobs
    trigger = jobs[0].job.trigger
    assert isinstance(trigger, IntervalTrigger)
    assert trigger.interval.total_seconds() == 300


def test_alive_job_writes_heartbeat():
    """alive_job ต้องเขียน heartbeat จริง ไม่ใช่แค่ตั้งเวลาไว้เฉยๆ — ALIVE_PATH ถูก autouse
    fixture (_isolate_rescore ใน conftest.py) redirect ไป tmp_path แล้ว เช็คซ้ำกันเผลอ
    เขียนทับไฟล์จริงของเครื่อง (parent ต้องไม่ใช่ PROJECT_ROOT)"""
    assert jobstate.ALIVE_PATH.parent != PROJECT_ROOT
    asyncio.run(alive_job(None))
    assert json.loads(jobstate.ALIVE_PATH.read_text(encoding="utf-8"))["ts"].endswith("+07:00")
