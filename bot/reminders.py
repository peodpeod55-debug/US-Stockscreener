"""เตือนวันงบของหุ้นใน watchlist: งบวันนี้/พรุ่งนี้ → แจ้งเตือนตอนเช้า

ใช้ endpoint วันงบรายตัวเดียวกับ lookup (1 API call/ตัว, มี cache ใน client)
"""
import logging
import sys
from datetime import date
from pathlib import Path

ETA_DIR = Path(__file__).resolve().parent / "vendor" / "eta"
if str(ETA_DIR) not in sys.path:
    sys.path.insert(0, str(ETA_DIR))

from analyze_earnings_trades import normalize_timing  # noqa: E402

REMIND_MAX_DAYS = 1             # เตือนเมื่องบอีก 0 (วันนี้) หรือ 1 วัน (พรุ่งนี้)

logger = logging.getLogger("bot.reminders")


def next_earnings(earnings, today):
    """วันงบถัดไป (>= today) จาก raw rows ของ FMP → (date_str, timing) หรือ None"""
    best = None
    for e in earnings or []:
        d = e.get("date")
        if d and d >= today.isoformat() and (best is None or d < best["date"]):
            best = e
    if best is None:
        return None
    return (best["date"], normalize_timing(best.get("time")))


def build_reminders(symbols, get_earnings, today=None):
    """รวมหุ้นที่งบวันนี้/พรุ่งนี้ — คืน list ของ {symbol, date, days_to, timing}

    get_earnings: callable(symbol) → raw earnings rows (เช่น client.get_earnings_dates)
    หุ้นที่ดึงไม่ได้/ไม่มีข้อมูล ข้ามเงียบๆ (log ไว้) ไม่ให้ล้ม job ทั้งตัว
    """
    today = today or date.today()
    items = []
    for sym in symbols:
        try:
            nxt = next_earnings(get_earnings(sym), today)
        except Exception:
            logger.exception("reminder fetch %s failed", sym)
            continue
        if nxt is None:
            continue
        date_str, timing = nxt
        days_to = (date.fromisoformat(date_str) - today).days
        if days_to <= REMIND_MAX_DAYS:
            items.append({"symbol": sym, "date": date_str,
                          "days_to": days_to, "timing": timing})
    return items
