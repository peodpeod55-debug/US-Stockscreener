"""มุมมอง "น่าสนใจตอนนี้" — จัดกลุ่มหุ้นที่ติดตามจาก snapshot ที่มีอยู่ (pure, ไม่ยิงเครือข่าย)

ถามเมื่ออยากรู้ (พิมพ์ น่าสนใจ / /hot) — ต่างจาก breakout_job ที่เตือน "เหตุการณ์" ตอนเช้า
มุมมองนี้ตอบว่า "ตอนนี้ตัวไหนควรมอง": 🔥 เพิ่งทะลุ / ใกล้แนว / งบใกล้ / รอตอบรับ ·
⚠️ หลุด SL / ปิดใต้ Low ก่อนงบ (อันตรายชนะ ไม่ปนกับ 🔥) · 😴 ที่เหลือ · ดึงไม่ได้แยกไว้
ไม่มี state ใหม่ ไม่มีคะแนนถ่วงน้ำหนัก — แค่จัดกลุ่ม + เรียงตามความใกล้
"""
from bot.levels import below_low_5d

HOT_PCT = 3.0               # ต่ำกว่าแนว H5d/H3m ไม่เกินนี้ (%) = "ใกล้ทะลุ"
EARNINGS_SOON_DAYS = 3      # งบถัดไปภายในกี่วัน = น่าจับตา
_NEAR_LEVELS = ("high_5d", "high_3m")
# sort key ใน 🔥: เพิ่งทะลุ (0) < ใกล้แนว (ระยะ %) < รอตอบรับ (5) < งบใกล้ (10 + วัน)
_KEY_BREAK, _KEY_PENDING, _KEY_EARNINGS = 0.0, 5.0, 10.0


def _risk_reasons(snap):
    lv = snap.get("levels")
    if not lv:
        return []
    reasons = []
    sl = lv.get("sl")
    # edge (เพิ่งหลุด) หรือ state (ปิดใต้ SL อยู่) — state เก็บตัวที่หลุดค้างมาหลายวันด้วย
    if sl is not None and (snap.get("sl_break") or snap["price"] < sl):
        reasons.append(("sl", sl))
    if below_low_5d(lv):
        reasons.append(("low", lv["low_5d"]))
    return reasons


def _hot_reasons(snap):
    """คืน (reasons, sort_key) — reasons ว่าง = ไม่เข้า 🔥"""
    reasons, key = [], None

    def take(k):
        nonlocal key
        key = k if key is None else min(key, k)

    if snap.get("new_breaks"):
        reasons.append(("break", list(snap["new_breaks"])))
        take(_KEY_BREAK)
    lv = snap.get("levels")
    if lv:
        near = []
        for k in _NEAR_LEVELS:
            pct = lv.get(f"pct_vs_{k}")
            if pct is not None and -HOT_PCT <= pct < 0:
                near.append((abs(pct), k))
        for dist, k in sorted(near):
            reasons.append(("near", k, dist, lv[k]))
            take(dist)
    if snap.get("pending_reaction"):
        reasons.append(("pending",))
        take(_KEY_PENDING)
    d = snap.get("days_to_earnings")
    if d is not None and 0 <= d <= EARNINGS_SOON_DAYS:
        reasons.append(("earnings", d, snap.get("timing") or "unknown"))
        take(_KEY_EARNINGS + d)
    return reasons, key


def classify_watch(items):
    """items: [(symbol, snap|None)] → {"hot", "risk", "idle", "failed", "total"}

    hot/risk: [{"symbol", "snap", "reasons"}] — reasons เป็น tuple รหัส
    ("break", [levels]) / ("near", level, ระยะ%, ราคาแนว) / ("pending",) /
    ("earnings", วัน, timing) / ("sl", ราคา SL) / ("low", low_5d) — formatter แปลเป็นไทย
    hot เรียงตามความใกล้ (เพิ่งทะลุก่อน, เท่ากันคงลำดับเดิม) · risk/idle/failed คงลำดับเดิม
    """
    hot, risk, idle, failed = [], [], [], []
    for sym, snap in items:
        if snap is None:
            failed.append(sym)
            continue
        rr = _risk_reasons(snap)
        if rr:
            risk.append({"symbol": sym, "snap": snap, "reasons": rr})
            continue
        hr, key = _hot_reasons(snap)
        if hr:
            hot.append({"symbol": sym, "snap": snap, "reasons": hr, "_key": key})
        else:
            idle.append(sym)
    hot.sort(key=lambda e: e["_key"])
    for e in hot:
        del e["_key"]
    return {"hot": hot, "risk": risk, "idle": idle, "failed": failed,
            "total": len(items)}
