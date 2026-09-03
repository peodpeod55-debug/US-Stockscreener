"""กันรัน job เช้าซ้ำ + catch-up job ที่พลาด (เครื่องปิด/บอทเพิ่ง restart)

state file: job_state.json = {job_name: วันที่รันล่าสุด ISO} — gitignored
job "claim" วันของตัวเองก่อนทำงาน → restart กี่รอบก็ไม่ส่งซ้ำ
"""
import json
from datetime import date, time

from bot.config import PROJECT_ROOT
from bot.fileio import write_json_atomic

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

# ขอบบนของหน้าต่าง catch-up — ตลาด US เปิดเร็วสุด 20:30 ไทย (ช่วง DST) แล้วแท่ง [0]
# จาก Yahoo กลายเป็นแท่ง intraday ยังไม่ปิด: breakout/scan จะอ่านค่าเพี้ยนแล้วเขียน
# state ถาวร (record_breakouts / auto_remove) — เปิดเครื่องดึกให้รอรันรุ่งเช้าตามปกติแทน
CATCHUP_UNTIL = time(20, 0)

# คีย์ใน job_state.json (ไฟล์เดียวกับ claim) สำหรับวันที่แท่งล่าสุดที่ breakout_job
# ประมวลผลไปแล้ว — ไม่ใช่ชื่อ job จึงไม่ชนกับ claim/release/already_ran ที่ใช้ชื่อ job ตรงๆ
# due_catchup/job_states (bot/status.py) วนตาม SCHEDULE ไม่ใช่คีย์ทั้งหมดของไฟล์ ไม่มีวันเห็นคีย์นี้
BREAKOUT_BAR_KEY = "breakout_bar"


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
    write_json_atomic(path, data)
    return True


def release(job, path=JOB_STATE_PATH, today=None):
    """คืนสิทธิ์ที่ claim วันนี้ (job ล้มก่อนสำเร็จ) — catch-up รอบถัดไปได้รันใหม่

    ลบเฉพาะเมื่อค่าเป็นวันนี้ — claim ของวันอื่นไม่ใช่ของเรา ห้ามแตะ
    """
    today = today or date.today()
    data = _load(path)
    if data.get(job) != today.isoformat():
        return False
    del data[job]
    write_json_atomic(path, data)
    return True


def last_run(job, path=None):
    """วันล่าสุดที่ job นี้ claim ไป (date) — ไม่เคย/ไฟล์เสีย/ค่าเพี้ยน → None

    ต้องอ่าน *ก่อน* claim ของวันนี้ (claim ทับค่าเดิม) — daily_job ใช้คำนวณช่วงที่เครื่องหายไป
    path อ่านจากโมดูล ณ เวลาเรียก (ไม่ผูกตอน def) — conftest redirect ในเทสคุมถึง
    """
    raw = _load(JOB_STATE_PATH if path is None else path).get(job)
    try:
        return date.fromisoformat(raw) if raw else None
    except ValueError:
        return None


def last_breakout_bar(path=None):
    """วันที่ (ISO) ของแท่งล่าสุดที่ breakout_job แจ้งเตือนจบไปแล้ว — None = ยังไม่เคย/ไฟล์เสีย

    เก็บคีย์ BREAKOUT_BAR_KEY ปนในไฟล์เดียวกับ claim ของ job (ดูคอมเมนต์บนค่าคงที่)
    path อ่านจากโมดูล ณ เวลาเรียก (แบบเดียวกับ last_run) — conftest redirect คุมถึง
    """
    return _load(JOB_STATE_PATH if path is None else path).get(BREAKOUT_BAR_KEY)


def set_breakout_bar(bar_date, path=None):
    """บันทึกวันที่แท่งล่าสุดที่ breakout_job เพิ่งแจ้งเตือนสำเร็จ — เรียกท้าย work() เท่านั้น

    (ต้องเกิดหลังส่งข้อความ/บันทึก breakouts.json ผ่านหมดแล้ว ไม่งั้น retry รอบถัดไปจะเข้าใจผิด
    ว่าแจ้งไปแล้วทั้งที่ยังไม่สำเร็จ)
    """
    resolved = JOB_STATE_PATH if path is None else path
    data = _load(resolved)
    data[BREAKOUT_BAR_KEY] = bar_date
    write_json_atomic(resolved, data)


def widen_lookback(base, last, today, cap=14):
    """หน้าต่างสแกนย้อนหลัง — เครื่องปิดหลายวันให้ย้อนครอบวันที่หายไป (สูงสุด cap)

    last = วันสแกนสำเร็จล่าสุด (None = ไม่เคย → ใช้ base ตามปกติ ไม่เหมาย้อนยาว)
    แถวซ้ำกับที่เคยสแกนไม่เป็นไร — scan_log.csv upsert ต่อ (scan_date, ticker) อยู่แล้ว
    """
    if last is None:
        return base
    return max(base, min((today - last).days, cap))


def due_catchup(now):
    """job ที่ถึงเวลาแล้ววันนี้ (ตามวัน+เวลาใน SCHEDULE) — ตัวกรองซ้ำอยู่ที่ claim

    เลย CATCHUP_UNTIL แล้วคืนว่างเสมอ (ดูคอมเมนต์บนค่าคงที่)"""
    if now.time() >= CATCHUP_UNTIL:
        return []
    return [name for name, t, days in SCHEDULE
            if now.weekday() in days and now.time() >= t]
