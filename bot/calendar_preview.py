"""ปฏิทินงบล่วงหน้า: พิมพ์ "งบ" → หุ้น universe ที่จะออกงบวันนี้..อีก N วัน

FMP earnings calendar 1 call + ปฏิทิน NASDAQ เสริม timing BMO/AMC
(merge แบบเดียวกับ run_scan: FMP มาก่อนชนะ, timing เติมจาก entry ที่แพ้ dedup)
"""
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

ETA_DIR = Path(__file__).resolve().parent / "vendor" / "eta"
if str(ETA_DIR) not in sys.path:
    sys.path.insert(0, str(ETA_DIR))

from analyze_earnings_trades import normalize_timing  # noqa: E402

from bot import earnings_store  # noqa: E402

DEFAULT_AHEAD = 2               # "งบ" เฉยๆ = วันนี้ + ล่วงหน้า 2 วัน
MAX_AHEAD = 7                   # เพดานล่วงหน้า (ปฏิทินไกลกว่านี้ยังเปลี่ยนได้บ่อย)

_CMD_WORDS = ("งบ", "ปฏิทินงบ")
_TIMING_ORDER = {"bmo": 0, "amc": 1}

logger = logging.getLogger("bot.calendar_preview")


def parse_calendar_command(text):
    """"งบ" → 2 · "งบ 5" → 5 (คุม 0..MAX_AHEAD) · "งบวันนี้" → 0 · None = ไม่ใช่คำสั่งนี้

    อาร์กิวเมนต์ที่ไม่ใช่ตัวเลขไม่ตีตก — ใช้ default (ผู้ใช้พิมพ์เพี้ยนยังได้ปฏิทิน)
    """
    tokens = (text or "").split()
    if not tokens:
        return None
    if tokens[0] == "งบวันนี้":
        return 0
    if tokens[0] not in _CMD_WORDS:
        return None
    if len(tokens) > 1:
        try:
            return max(0, min(MAX_AHEAD, int(tokens[1])))
        except ValueError:
            pass
    return DEFAULT_AHEAD


def build_calendar(get_calendar, universe, today=None, days_ahead=DEFAULT_AHEAD,
                   secondary_cal_fn=None):
    """หุ้น universe ที่จะออกงบช่วง today..today+days_ahead

    get_calendar(from_date, to_date) → raw rows รูป FMP ({symbol, date, time})
    secondary_cal_fn รูปเดียวกัน — แหล่งเสริม ล้มได้โดยไม่พังปฏิทินหลัก
    คืน (items, from_date, to_date) — items เรียง วัน → BMO→AMC→ไม่ระบุ → symbol
    """
    today = today or date.today()
    from_date = today.isoformat()
    to_date = (today + timedelta(days=days_ahead)).isoformat()
    calendar = list(get_calendar(from_date, to_date) or [])
    if secondary_cal_fn:
        try:
            calendar += secondary_cal_fn(from_date, to_date) or []
        except Exception:
            logger.exception("secondary calendar failed")
    # ปฏิทินล่วงหน้าที่ดึงมาแล้ว → ลงคลังวันงบ (เตือนวันงบ/lookup ใช้ต่อ ฟรี)
    earnings_store.merge(calendar, source="preview", today=today)
    _canon = earnings_store.canon
    seen, items, timing_map = set(), [], {}
    for e in calendar:
        sym, d = e.get("symbol"), e.get("date")
        # FMP อาจคืน entry นอกช่วงที่ขอ — กรองตามช่วงจริงเสมอ
        if not sym or not d or not from_date <= d <= to_date:
            continue
        t = normalize_timing(e.get("time"))
        if t != "unknown":
            timing_map.setdefault(_canon(sym), t)
        if sym in universe and sym not in seen:
            seen.add(sym)
            meta = universe[sym]
            items.append({"symbol": sym, "date": d, "timing": t,
                          "name": meta.get("name") or sym,
                          "dr_symbols": meta.get("dr_symbols") or ""})
    for it in items:
        if it["timing"] == "unknown":
            it["timing"] = timing_map.get(_canon(it["symbol"]), "unknown")
    items.sort(key=lambda it: (it["date"],
                               _TIMING_ORDER.get(it["timing"], 2),
                               it["symbol"]))
    return items, from_date, to_date
