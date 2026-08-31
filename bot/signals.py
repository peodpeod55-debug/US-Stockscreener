"""บันทึกถาวรของสัญญาณ A/B ที่บอทแจ้ง — signals.json (gitignore ตั้งแต่ 31 ส.ค. 2026 — กัน checkout ทับไฟล์ live, ประวัติเก่าอยู่ใน git history)

แทนการอ่าน reports/scan_*.json (gitignored, อยู่เครื่องเดียว) — หนึ่งสัญญาณ =
(symbol, earnings_date) บันทึกครั้งแรกที่แจ้ง ใช้ทำสรุปรายสัปดาห์ + สถิติระยะยาว
"""
import json
from datetime import date, timedelta

from bot.config import PROJECT_ROOT
from bot.fileio import write_json_atomic

SIGNALS_PATH = PROJECT_ROOT / "signals.json"


def load_signals(path=SIGNALS_PATH):
    """สัญญาณทั้งหมดในไฟล์ (ไฟล์หาย/พัง → ลิสต์ว่าง)"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def record_signals(candidates, flag_date, path=SIGNALS_PATH):
    """บันทึกหุ้น A/B จากสแกน — คืนเฉพาะสัญญาณใหม่จริง (dedup ครั้งแรกที่แจ้งชนะ)"""
    signals = load_signals(path)
    seen = {(s.get("symbol"), s.get("earnings_date")) for s in signals}
    new = []
    for c in candidates:
        key = (c.get("symbol"), c.get("earnings_date"))
        lv = c.get("levels") or {}
        if not key[0] or key in seen or lv.get("price") is None:
            continue
        seen.add(key)
        new.append({
            "symbol": c["symbol"],
            "name": c.get("name") or c["symbol"],
            "grade": c.get("grade"),
            "score": c.get("score"),
            "earnings_date": c.get("earnings_date"),
            "timing": c.get("timing"),
            "flag_date": flag_date,
            "flag_price": lv["price"],
            "sl": lv.get("sl"),
            "dr_symbols": c.get("dr_symbols") or "",
        })
    if new:
        write_json_atomic(path, signals + new)
    return new


def signals_since(days, path=SIGNALS_PATH, today=None):
    """สัญญาณที่แจ้งภายใน days วันล่าสุด (ตาม flag_date)"""
    today = today or date.today()
    cutoff = (today - timedelta(days=days)).isoformat()
    return [s for s in load_signals(path) if (s.get("flag_date") or "") >= cutoff]


# timing ที่บอทอนุมานเอง/ไม่รู้ — ไม่ส่งต่อเป็นข้อมูลจริง ให้ lookup อนุมานใหม่จากแท่งล่าสุด
_UNCERTAIN_TIMING = (None, "", "unknown", "bmo*")


def earnings_from_signals(symbol, path=None):
    """วันงบที่บอทบันทึกไว้ตอนให้เกรด (signals.json) ในรูปเดียวกับ FMP raw: [{"date", "time"}]

    fallback ของ lookup_symbol เมื่อ FMP รายตัวไม่ให้ (402 แผนฟรี เช่น EL) —
    ปฏิทินรวมตอนสแกนเห็นหุ้นตัวนั้น แต่ stable/earnings?symbol= ถูกบล็อก
    path resolve ตอนเรียก (ไม่ใช่ตอน def) ให้เทส/conftest สลับไฟล์ได้
    """
    path = path or SIGNALS_PATH
    out = []
    for s in load_signals(path):
        if s.get("symbol") != symbol or not s.get("earnings_date"):
            continue
        t = s.get("timing")
        out.append({"date": s["earnings_date"],
                    "time": None if t in _UNCERTAIN_TIMING else t})
    return out
