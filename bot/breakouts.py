"""บันทึกถาวรของเหตุการณ์ทะลุแนว — breakouts.json (track ใน git แบบ signals.json)

ป้อนให้ gem-lab เป็น candidate ยิง Gem (source [us]) — เก็บเฉพาะทะลุแนวขึ้น
(new_breaks) ไม่เก็บหลุด SL/Low ก่อนงบ เพราะเป็นสัญญาณขาออก ไม่ใช่ candidate
หนึ่งเหตุการณ์ = (symbol, วันแท่งที่ทะลุ) บันทึกครั้งแรกชนะ
"""
import json

from bot.config import PROJECT_ROOT
from bot.fileio import write_json_atomic

BREAKOUTS_PATH = PROJECT_ROOT / "breakouts.json"


def load_breakouts(path=BREAKOUTS_PATH):
    """เหตุการณ์ทั้งหมดในไฟล์ (ไฟล์หาย/พัง → ลิสต์ว่าง)"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def record_breakouts(snaps, path=BREAKOUTS_PATH):
    """บันทึก snapshot ที่เพิ่งทะลุแนว — คืนเฉพาะเหตุการณ์ใหม่จริง"""
    events = load_breakouts(path)
    seen = {(e.get("symbol"), e.get("date")) for e in events}
    new = []
    for s in snaps:
        key = (s.get("symbol"), s.get("last_date"))
        if not key[0] or not key[1] or key in seen or not s.get("new_breaks"):
            continue
        seen.add(key)
        new.append({
            "symbol": s["symbol"],
            "date": s["last_date"],
            "breaks": list(s["new_breaks"]),
            "close": s.get("price"),
            "grade": s.get("grade"),
        })
    if new:
        write_json_atomic(path, events + new)
    return new
