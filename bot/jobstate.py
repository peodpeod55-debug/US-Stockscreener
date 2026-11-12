"""กันรัน job เช้าซ้ำ + catch-up job ที่พลาด (เครื่องปิด/บอทเพิ่ง restart)

state file: job_state.json = {job_name: วันที่รันล่าสุด ISO} — gitignored
job "claim" วันของตัวเองก่อนทำงาน → restart กี่รอบก็ไม่ส่งซ้ำ
"""
import json
import logging
from datetime import date, time, timedelta

from bot.config import PROJECT_ROOT
from bot.fileio import write_json_atomic

JOB_STATE_PATH = PROJECT_ROOT / "job_state.json"
# heartbeat ให้ watchdog นอก process (tools/bot_watchdog.py) ดู mtime — บอทไม่อ่านไฟล์นี้เอง
ALIVE_PATH = PROJECT_ROOT / "last_alive.json"
ALIVE_INTERVAL = 300            # วินาที — เท่าบอทไทย (alive_job)

# date.weekday(): จ=0 → จันทร์(0)–เสาร์(5) · session US ของวัน X ได้แท่ง EOD เช้าวัน X+1 (ไทย)
# จันทร์อยู่ด้วยเพื่อเก็บ session ศุกร์ที่รอบเสาร์พลาด (เครื่องไม่เปิดเสาร์ = เตือนทะลุแนว/หลุด SL
# ของแท่งศุกร์เคยหายถาวร เพราะ detector เทียบแค่ 1 แท่ง) — เสาร์รันไปแล้วก็ไม่ซ้ำ: breakout
# ข้ามเองด้วย guard breakout_bar · scan ใช้หน้าต่าง widen_lookback จาก last_run
PUSH_WEEKDAYS = {0, 1, 2, 3, 4, 5}
_ALL_DAYS = set(range(7))

# job เช้าที่ catch-up ได้ (เรียงตามเวลา)
SCHEDULE = [
    ("breakout", time(8, 20), PUSH_WEEKDAYS),
    ("reminder", time(8, 25), _ALL_DAYS),
    ("scan", time(8, 30), PUSH_WEEKDAYS),
    ("weekly", time(9, 0), _ALL_DAYS),
]

# job รายสัปดาห์: "ทำแล้ว" = ทำตั้งแต่วันอาทิตย์ล่าสุดเป็นต้นมา (ไม่ใช่ "ทำวันนี้") — ลงตารางทุกวัน
# แล้วให้ anchor กันซ้ำ → ส่งครั้งแรกที่เครื่องเปิดหลัง 09:00 ในสัปดาห์นั้น (แบบเดียวกับปฏิทินงบ
# ของบอทไทย) · เดิมรันได้เฉพาะเช้าวันอาทิตย์ = ไม่เปิดเครื่องวันอาทิตย์แล้วสัปดาห์นั้นหายทั้งรอบ
WEEKLY_JOBS = {"weekly"}

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


def week_anchor(today):
    """วันอาทิตย์ล่าสุด (วันนี้เองถ้าเป็นวันอาทิตย์) — จุดเริ่มรอบของ job รายสัปดาห์"""
    return today - timedelta(days=(today.weekday() + 1) % 7)


def done_for(job, last_iso, today):
    """ค่าที่จดไว้ (วัน ISO ที่รันล่าสุด) นับว่า "รอบปัจจุบันทำแล้ว" ไหม

    รายวัน: ต้องเป็นวันนี้ · รายสัปดาห์ (WEEKLY_JOBS): ตั้งแต่วันอาทิตย์ล่าสุดเป็นต้นมา
    ค่าว่าง/เพี้ยน = ยังไม่ทำ
    """
    if job not in WEEKLY_JOBS:
        return last_iso == today.isoformat()
    try:
        return date.fromisoformat(last_iso) >= week_anchor(today)
    except (TypeError, ValueError):
        return False


def already_ran(job, path=JOB_STATE_PATH, today=None):
    today = today or date.today()
    return done_for(job, _load(path).get(job), today)


def claim(job, path=JOB_STATE_PATH, today=None):
    """จองสิทธิ์รัน job รอบนี้ (รายวัน = วันนี้ · รายสัปดาห์ = สัปดาห์นี้) — False ถ้ารันไปแล้ว"""
    today = today or date.today()
    data = _load(path)
    if done_for(job, data.get(job), today):
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


def write_alive(now, path=None):
    """จดเวลาว่ายังทำงาน — {"ts": ISO} เขียนแบบ atomic · ล้มแค่ log ไม่ให้ job queue พัง"""
    try:
        write_json_atomic(path or ALIVE_PATH, {"ts": now.isoformat()})
    except OSError:
        logging.getLogger(__name__).warning("เขียน last_alive.json ไม่สำเร็จ", exc_info=True)
