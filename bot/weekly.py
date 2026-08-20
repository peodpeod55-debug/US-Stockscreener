"""สรุปผลรายสัปดาห์ (PEAD drift): หุ้น A/B ที่บอทแจ้ง ตอนนี้ +/-% เท่าไหร่

สัญญาณอ่านจาก signals.json (ดู bot/signals.py) — main ส่ง list เข้ามาตรงๆ
"""
import logging
from datetime import date

SIGNAL_LOOKBACK_DAYS = 30       # มองย้อนการแจ้งไกลสุดเท่านี้

logger = logging.getLogger("bot.weekly")


def evaluate_signal(sig, prices):
    """เทียบราคาปัจจุบันกับวันแจ้ง — คืน dict เดิม + price_now/pct/days/sl_hit

    prices: list[dict] most-recent-first · sl_hit = วันแรกที่ low หลุด SL
    (นับเฉพาะวันหลังวันแจ้ง) · คืน None ถ้าไม่มีข้อมูลราคา
    """
    if not prices:
        return None
    price_now = prices[0]["close"]
    last_date = prices[0]["date"]
    pct = (price_now - sig["flag_price"]) / sig["flag_price"] * 100
    days = (date.fromisoformat(last_date)
            - date.fromisoformat(sig["flag_date"])).days
    sl_hit = None
    if sig.get("sl") is not None:
        for bar in reversed(prices):        # เก่า → ใหม่ เอาวันแรกที่หลุด
            if bar["date"] > sig["flag_date"] and bar["low"] < sig["sl"]:
                sl_hit = bar["date"]
                break
    return {**sig, "price_now": price_now, "pct": pct,
            "days": days, "sl_hit": sl_hit}


def build_weekly_items(signals, get_prices):
    """สัญญาณทั้งหมด + ผลปัจจุบัน — ตัวที่ดึงราคาไม่ได้ข้าม (log ไว้)"""
    items = []
    for sig in signals:
        try:
            prices = get_prices(sig["symbol"])
        except Exception:
            logger.exception("weekly fetch %s failed", sig["symbol"])
            continue
        ev = evaluate_signal(sig, prices)
        if ev:
            items.append(ev)
    return items
