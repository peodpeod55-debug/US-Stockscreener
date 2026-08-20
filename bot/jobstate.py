"""กันรัน job เช้าซ้ำ + catch-up job ที่พลาด (เครื่องปิด/บอทเพิ่ง restart)

state file: job_state.json = {job_name: วันที่รันล่าสุด ISO} — gitignored
job "claim" วันของตัวเองก่อนทำงาน → restart กี่รอบก็ไม่ส่งซ้ำ
"""
import json
from datetime import date, time

from bot.config import PROJECT_ROOT

JOB_STATE_PATH = PROJECT_ROOT / "job_state.json"

PUSH_WEEKDAYS = {1, 2, 3, 4, 5}  # date.weekday(): จ=0 → อังคาร(1)–เสาร์(5)
_ALL_DAYS = set(range(7))

# job เช้าที่ catch-up ได้ (เรียงตามเวลา) — openbell ไม่อยู่เพราะผูกกับช่วงเปิดตลาด
SCHEDULE = [
    ("breakout", time(8, 20), PUSH_WEEKDAYS),
    ("reminder", time(8, 25), _ALL_DAYS),
    ("scan", time(8, 30), PUSH_WEEKDAYS),
    ("weekly", time(9, 0), {6}),
]


def _load(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def already_ran(job, path=JOB_STATE_PATH, today=None):
    today = today or date.today()
    return _load(path).get(job) == today.isoformat()


def claim(job, path=JOB_STATE_PATH, today=None):
    """จองสิทธิ์รัน job วันนี้ — False ถ้ามีคนรันไปแล้ว (ไม่ต้องรันซ้ำ)"""
    today = today or date.today()
    data = _load(path)
    if data.get(job) == today.isoformat():
        return False
    data[job] = today.isoformat()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return True


def due_catchup(now):
    """job ที่ถึงเวลาแล้ววันนี้ (ตามวัน+เวลาใน SCHEDULE) — ตัวกรองซ้ำอยู่ที่ claim"""
    return [name for name, t, days in SCHEDULE
            if now.weekday() in days and now.time() >= t]
