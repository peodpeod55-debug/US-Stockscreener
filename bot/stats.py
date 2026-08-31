"""สถิติผลงานสะสมของสัญญาณ A/B + ⭐ set_cross ทั้งหมดใน signals.json

ตอบว่าเกรดจากระบบ 5-factor (และเกณฑ์ SET≥10/14 วัน — signal_type "set_cross"
เพิ่ม 31 ส.ค. 2026) มี edge จริงไหม: drift เฉลี่ย +5/+20/+60 วันทำการ,
win rate ต่อ horizon, อัตราเคยหลุด SL — แยกตามเกรด, กลุ่ม set_cross และรวม

นิยามแท่ง "หลังแจ้ง" = date > flag_date (convention เดียวกับ sl_hit ใน weekly
เพื่อให้สองรายงานตัวเลขตรงกัน) · สัญญาณที่หน้าต่างราคา 250 วันย้อนไม่ถึงวันแจ้ง
(เก่ากว่า ~9 เดือน) ประเมินไม่ได้ — ข้ามพร้อมนับแยกใน "ทั้งหมด vs ประเมินได้"
"""
import logging

HORIZONS = (5, 20, 60)          # วันทำการหลังแจ้ง
SET_CROSS = "set_cross"         # คีย์กลุ่มของสัญญาณข้ามเกณฑ์ไทย (⭐) ใน summarize

logger = logging.getLogger("bot.stats")


def evaluate_stat(sig, prices):
    """drift ต่อ horizon + เคยหลุด SL ไหม — None ถ้าข้อมูลไม่ครอบคลุมวันแจ้ง

    prices: list[dict] most-recent-first (convention เดียวกับ levels.py)
    """
    if not prices:
        return None
    if prices[-1]["date"] > sig["flag_date"]:   # แท่งเก่าสุดยังใหม่กว่าวันแจ้ง
        return None
    post = [b for b in reversed(prices) if b["date"] > sig["flag_date"]]
    drifts = {}
    for h in HORIZONS:
        drifts[h] = ((post[h - 1]["close"] - sig["flag_price"])
                     / sig["flag_price"] * 100 if len(post) >= h else None)
    sl_hit = None
    if sig.get("sl") is not None:
        sl_hit = any(b["low"] < sig["sl"] for b in post)
    return {"grade": sig.get("grade"), "signal_type": sig.get("signal_type") or "composite",
            "drifts": drifts, "sl_hit": sl_hit}


def build_stats(signals, get_prices):
    """ประเมินทุกสัญญาณ — ตัวที่ดึงราคาไม่ได้/ข้อมูลไม่ถึง ข้าม (log ไว้)"""
    evaluated = []
    for sig in signals:
        try:
            prices = get_prices(sig["symbol"])
        except Exception:
            logger.exception("stats fetch %s failed", sig["symbol"])
            continue
        ev = evaluate_stat(sig, prices)
        if ev:
            evaluated.append(ev)
    return evaluated


def _empty_group():
    return {"n": 0, "sl_n": 0, "sl_hits": 0,
            "horizons": {h: {"n": 0, "sum": 0.0, "wins": 0, "avg": None}
                         for h in HORIZONS}}


def _group_keys(ev):
    """composite → เกรด · set_cross → "set_cross" (เกรดเดิมเป็นข้อมูลประกอบ ไม่ปนกลุ่ม A/B) · ทุกตัว → "all" """
    key = SET_CROSS if ev.get("signal_type") == SET_CROSS else (ev.get("grade") or "?")
    return (key, "all")


def summarize(evaluated):
    """รวมเป็นกลุ่มต่อเกรด \\ "set_cross" + กลุ่ม "all" — {key: {n, sl_n, sl_hits, horizons}}"""
    groups = {}
    for ev in evaluated:
        for key in _group_keys(ev):
            g = groups.setdefault(key, _empty_group())
            g["n"] += 1
            if ev["sl_hit"] is not None:
                g["sl_n"] += 1
                g["sl_hits"] += 1 if ev["sl_hit"] else 0
            for h in HORIZONS:
                d = ev["drifts"].get(h)
                if d is not None:
                    hh = g["horizons"][h]
                    hh["n"] += 1
                    hh["sum"] += d
                    hh["wins"] += 1 if d > 0 else 0
    for g in groups.values():
        for hh in g["horizons"].values():
            if hh["n"]:
                hh["avg"] = hh["sum"] / hh["n"]
    return groups
