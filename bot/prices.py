"""แหล่งราคา EOD รวมศูนย์: cache → Yahoo (หลัก) → FMP (สำรอง)

FMP แผนฟรีตอบ 402 กับหุ้นเกือบทั้ง universe (28 ส.ค. 2026: 19/21 ตัว) ราคาจึงมาจาก
Yahoo อยู่แล้วในทางปฏิบัติ — ให้ Yahoo เป็นหลักทุกตัว ข้อมูลทั้ง universe มาจากแหล่ง
เดียวกัน FMP เหลือเป็นสำรองตอน Yahoo ล้ม/ว่าง (ปฏิทินงบยังใช้ FMP ตามเดิม)

get_prices  — ทางเดียวที่ทุก job/คำสั่งใช้ดึงราคา (แทน pattern FMP→402→Yahoo ที่เคยซ้ำ 5 ที่)
prefetch    — อุ่น cache หลายตัวพร้อมกัน (ThreadPool) ก่อนลูปเดิมที่อ่านทีละตัว
ธง saw_402 บน FMPClient ไม่ thread-safe → FMP fallback ถูก serialize ด้วย lock
exception จาก FMP (เช่น ApiCallBudgetExceeded) ปล่อยผ่านให้ผู้เรียกจัดการ · Yahoo ล้ม = ข้าม
"""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from bot import fetch_cache
from bot.yahoo_prices import fetch_yahoo_prices

PREFETCH_WORKERS = 4

logger = logging.getLogger("bot.prices")
_fmp_lock = threading.Lock()


def get_prices(symbol, days=250, client=None, yahoo_fn=None):
    """แท่งราคา most-recent-first ≤ days แท่ง หรือ None ถ้าไม่มีแหล่งไหนให้

    ค่าว่างไม่ cache — รอบถัดไปลองใหม่ได้ (Yahoo สะดุดชั่วคราวไม่กลายเป็นถาวร)
    """
    key = ("prices", symbol, days)
    prices = fetch_cache.get(key)
    if prices is not None:
        return prices
    yahoo_fn = yahoo_fn or fetch_yahoo_prices
    try:
        prices = yahoo_fn(symbol, days)
    except Exception:
        logger.warning("yahoo prices %s failed", symbol, exc_info=True)
        prices = None
    if not prices and client is not None:
        with _fmp_lock:
            client.saw_402 = False  # ธงต่อ symbol — client ตัวเดียวใช้หลายตัว
            prices = client.get_historical_prices(symbol, days=days)
    if not prices:
        return None
    fetch_cache.put(key, prices)
    return prices


def prefetch(symbols, days=250, client=None, workers=PREFETCH_WORKERS,
             yahoo_fn=None, get_fn=None):
    """อุ่น cache ราคาหลายตัวพร้อมกัน — best-effort: ตัวที่ล้มข้าม (log) ไม่ raise

    get_fn(symbol, days) แทนแหล่งราคา (ผู้เรียกฉีดได้ เช่น เทส) — ผลลง cache เสมอ
    ลูปที่ตามมาเรียกทีละตัวแล้วเจอ cache ทันที
    """
    todo = [s for s in dict.fromkeys(symbols)
            if fetch_cache.get(("prices", s, days)) is None]
    if not todo:
        return
    fetch = get_fn or (lambda s, d: get_prices(s, d, client=client,
                                                yahoo_fn=yahoo_fn))

    def one(sym):
        try:
            result = fetch(sym, days)
            if result:
                fetch_cache.put(("prices", sym, days), result)
        except Exception:
            logger.warning("prefetch %s failed", sym, exc_info=True)

    with ThreadPoolExecutor(max_workers=min(workers, len(todo))) as pool:
        list(pool.map(one, todo))
