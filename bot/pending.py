"""รายการ "รอวันตอบรับงบ" ข้ามรอบสแกน — pending.json (gitignored, state ของเครื่อง)

สแกนดึงปฏิทินย้อน lookback วันปฏิทิน (ค่าเริ่มต้น 2) → งบ AMC วันศุกร์ (D0 = จันทร์
แท่งมาเช้าอังคาร) หรืองบก่อนวันหยุด US หลุดหน้าต่างปฏิทินไปก่อนจะได้เกรด — หายเงียบ
ทางแก้: entry ที่ยังรอ (waiting / no_data) จำไว้ แล้วรอบถัดไปเติมกลับเข้า reported
จนกว่าจะได้เกรดหรือเก่าเกิน PENDING_MAX_AGE_DAYS (no_data รวมตัวที่แหล่งราคาสะดุด/402)
"""
import json
from datetime import timedelta

from bot.config import PROJECT_ROOT
from bot.fileio import write_json_atomic

PENDING_PATH = PROJECT_ROOT / "pending.json"
PENDING_MAX_AGE_DAYS = 10       # งบเก่ากว่านี้ยังไม่ได้เกรด = ข้อมูลไม่มีจริง เลิกรอ
CARRY_REASONS = ("waiting", "no_data")


def load_pending(path=None):
    """entry ที่จำไว้ทั้งหมด (ไฟล์หาย/พัง → ลิสต์ว่าง)"""
    path = path or PENDING_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def save_pending(pending, path=None):
    """เก็บเฉพาะ entry ที่รอแล้วมีโอกาสได้ผล (CARRY_REASONS) — คืนสิ่งที่เขียน

    เขียนทับทั้งไฟล์ทุกสแกน: ตัวที่ได้เกรดแล้วหลุดออกเอง ไม่มี state ค้าง
    """
    path = path or PENDING_PATH
    items = [{"symbol": p["symbol"], "date": p["date"],
              "timing": p.get("timing") or "unknown"}
             for p in pending
             if p.get("reason") in CARRY_REASONS and p.get("symbol") and p.get("date")]
    write_json_atomic(path, items)
    return items


def carry_forward(reported, stored, today):
    """entry ที่จำไว้ซึ่งไม่อยู่ในปฏิทินรอบนี้ (เทียบ symbol) และยังไม่เก่าเกิน

    ปฏิทินรอบนี้ชนะเสมอ (สดกว่า) · timing "bmo*" (อนุมานจากแท่ง) ล้างเป็น unknown
    ให้รอบใหม่อนุมานเองจากข้อมูลล่าสุด · คืน list รูปเดียวกับ reported
    """
    present = {r["symbol"] for r in reported}
    cutoff = (today - timedelta(days=PENDING_MAX_AGE_DAYS)).isoformat()
    out = []
    for p in stored:
        sym, d = p.get("symbol"), p.get("date")
        if not sym or not d or d < cutoff or sym in present:
            continue
        present.add(sym)
        t = p.get("timing") or "unknown"
        out.append({"symbol": sym, "date": d,
                    "timing": "unknown" if t == "bmo*" else t})
    return out
