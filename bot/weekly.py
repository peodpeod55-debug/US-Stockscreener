"""สรุปผลรายสัปดาห์ (PEAD drift): หุ้น A/B ที่บอทแจ้ง ตอนนี้ +/-% เท่าไหร่

ใช้ scan_*.json ใน reports/ เป็นบันทึกการแจ้ง (ไม่ต้องมี state file เพิ่ม)
สัญญาณเดียวกัน = (symbol, earnings_date) — สแกนซ้อนวันกันนับครั้งแรกที่แจ้ง
"""
import json
import logging
from datetime import date, timedelta

SIGNAL_LOOKBACK_DAYS = 30       # มองย้อนการแจ้งไกลสุดเท่านี้

logger = logging.getLogger("bot.weekly")


def collect_signals(reports_dir, today=None):
    """รวบรวมหุ้น A/B ที่เคยแจ้งจากไฟล์สแกน — คืน list เรียงตามวันแจ้ง

    แต่ละตัว: symbol, name, grade, score, earnings_date, flag_date,
    flag_price (ราคาปิดวันแจ้ง), sl, dr_symbols
    """
    today = today or date.today()
    cutoff = (today - timedelta(days=SIGNAL_LOOKBACK_DAYS)).isoformat()
    signals, seen = [], set()
    try:
        files = sorted(reports_dir.glob("scan_*.json"))  # ชื่อไฟล์เรียงตามเวลา
    except OSError:
        return []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("skip unreadable report %s", f.name)
            continue
        flag_date = data.get("to_date")
        if not flag_date or flag_date < cutoff:
            continue
        for c in data.get("candidates") or []:
            key = (c.get("symbol"), c.get("earnings_date"))
            lv = c.get("levels") or {}
            if not key[0] or key in seen or lv.get("price") is None:
                continue
            seen.add(key)
            signals.append({
                "symbol": c["symbol"],
                "name": c.get("name") or c["symbol"],
                "grade": c.get("grade"),
                "score": c.get("score"),
                "earnings_date": c.get("earnings_date"),
                "flag_date": flag_date,
                "flag_price": lv["price"],
                "sl": lv.get("sl"),
                "dr_symbols": c.get("dr_symbols") or "",
            })
    return signals


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


def build_weekly_items(reports_dir, get_prices, today=None):
    """สัญญาณทั้งหมดใน 30 วัน + ผลปัจจุบัน — ตัวที่ดึงราคาไม่ได้ข้าม (log ไว้)"""
    items = []
    for sig in collect_signals(reports_dir, today):
        try:
            prices = get_prices(sig["symbol"])
        except Exception:
            logger.exception("weekly fetch %s failed", sig["symbol"])
            continue
        ev = evaluate_signal(sig, prices)
        if ev:
            items.append(ev)
    return items
