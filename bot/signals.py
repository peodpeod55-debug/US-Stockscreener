"""บันทึกถาวรของสัญญาณ A/B ที่บอทแจ้ง — signals.json (track ใน git ไว้เป็น backup)

แทนการอ่าน reports/scan_*.json (gitignored, อยู่เครื่องเดียว) — หนึ่งสัญญาณ =
(symbol, earnings_date) บันทึกครั้งแรกที่แจ้ง ใช้ทำสรุปรายสัปดาห์ + สถิติระยะยาว
"""
import json
from datetime import date, timedelta

from bot.config import PROJECT_ROOT

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
        path.write_text(json.dumps(signals + new, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    return new


def signals_since(days, path=SIGNALS_PATH, today=None):
    """สัญญาณที่แจ้งภายใน days วันล่าสุด (ตาม flag_date)"""
    today = today or date.today()
    cutoff = (today - timedelta(days=days)).isoformat()
    return [s for s in load_signals(path) if (s.get("flag_date") or "") >= cutoff]
