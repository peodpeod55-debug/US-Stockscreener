"""ปักเวลา job รายวันที่ลงทะเบียนจริงใน build_app — กันงาน 21:00/22:00 (openbell)
แอบกลับมาเงียบๆ หลังถอดออก และยืนยันว่างานหลักยังตั้งเวลาไม่ขยับ (แพ็ค B)"""
from bot.config import Config
from bot.main import build_app

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
