"""ยืนยันเปิดตลาด US: ~30 นาทีหลังระฆังเปิด เช็คหุ้นที่ติดตามว่า gap ยังอยู่ไหม

ตลาดเปิด 09:30 America/New_York = 20:30 ไทย (DST) / 21:30 ไทย (หน้าหนาว)
job ตั้งยิง 21:00 และ 22:00 ไทย แล้วให้ in_open_window ตัดสินว่ารอบไหนตรงจริง
"""
import logging
from zoneinfo import ZoneInfo

import requests

from bot.yahoo_prices import YAHOO_URL, _HEADERS

US_TZ = ZoneInfo("America/New_York")
OPEN_WINDOW_MIN = 20            # นาทีหลังเปิดอย่างน้อย (ให้ราคานิ่งก่อน)
OPEN_WINDOW_MAX = 80            # เกินนี้ = รอบยิงถัดไปของอีกฤดู ไม่ใช่ของเรา

logger = logging.getLogger("bot.openbell")


def in_open_window(now):
    """True ถ้าตอนนี้อยู่ช่วง 20–80 นาทีหลังตลาด US เปิด (จันทร์–ศุกร์ US)"""
    now_us = now.astimezone(US_TZ)
    if now_us.weekday() >= 5:
        return False
    open_dt = now_us.replace(hour=9, minute=30, second=0, microsecond=0)
    minutes = (now_us - open_dt).total_seconds() / 60
    return OPEN_WINDOW_MIN <= minutes <= OPEN_WINDOW_MAX


def build_open_item(symbol, raw):
    """แปลง quote ดิบ (รูป FMP: price/open/previousClose) เป็นรายการรายงาน"""
    if not raw:
        return None
    price, op, prev = raw.get("price"), raw.get("open"), raw.get("previousClose")
    if price is None or not prev:
        return None
    return {
        "symbol": symbol,
        "price": price,
        "day_pct": (price - prev) / prev * 100,
        "gap_pct": (op - prev) / prev * 100 if op else None,
        "above_open": (price >= op) if op else None,
    }


def build_open_report(symbols, get_quote):
    """รวมรายการหุ้นที่ได้ quote — ตัวที่ดึงไม่ได้ข้าม (log ไว้)"""
    items = []
    for sym in symbols:
        try:
            item = build_open_item(sym, get_quote(sym))
        except Exception:
            logger.exception("open quote %s failed", sym)
            continue
        if item:
            items.append(item)
    return items


def fetch_yahoo_quote(symbol, get=requests.get):
    """quote สำรองจาก Yahoo v8 (range 1d) — คืนรูปเดียวกับ FMP หรือ None"""
    ysym = symbol.upper().replace(".", "-")
    try:
        resp = get(YAHOO_URL.format(symbol=ysym),
                   params={"range": "1d", "interval": "1d"},
                   headers=_HEADERS, timeout=15)
        if resp.status_code != 200:
            return None
        result = ((resp.json().get("chart") or {}).get("result")) or []
        if not result:
            return None
        meta = result[0].get("meta") or {}
        quote = ((result[0].get("indicators") or {}).get("quote") or [{}])[0]
        opens = quote.get("open") or []
        return {
            "price": meta.get("regularMarketPrice"),
            "open": opens[0] if opens else None,
            "previousClose": (meta.get("chartPreviousClose")
                              or meta.get("previousClose")),
        }
    except Exception:
        return None
