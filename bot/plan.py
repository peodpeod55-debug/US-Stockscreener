"""แผนเทรดรายตัว (/plan, พิมพ์ "แผน CRM") — pure: ข้อมูลราคา/DR ส่งเข้ามา ไม่ยิงเครือข่าย

3 ทางเข้าในราคา US: ① เข้าตอนนี้ (ปิดล่าสุด) ② ทะลุ High วันงบ (breakout)
③ ย่อถึง D0 Open (pullback ขอบบน gap) · SL = D0 Low เหมือนทั้งระบบ · เป้า 1R/2R/3R
DR: ราคาบาท = US × FX × implied ratio (bot/dr.py) · จำนวนหน่วย = เงินเสี่ยง ÷ (entry − SL บาท)
ปัดลงเป็น lot LOT หน่วย · ยังไม่ตั้ง /risk → มีราคาบาทแต่ไม่มีจำนวนหน่วย
"""
import math

from bot.levels import positive_reaction
from bot.lookup import parse_tickers

LOT = 100                       # board lot ของ DR บน SET
PLAN_MAX = 3                    # หุ้นต่อข้อความ (แผนยาว + ดึง DR ต่อตัว)
DR_MAX_PLAN = 3                 # DR ต่อหุ้นที่แสดง (เรียงตามวอลุ่ม) เกินบอกจำนวน
TARGET_R = (1, 2, 3)
ENTRIES = (("now", "เข้าตอนนี้"), ("breakout", "ทะลุ High วันงบ"),
           ("pullback", "ย่อถึง D0 Open"))
_CMD_WORDS = ("แผน", "plan")


def parse_plan_command(text):
    """"แผน CRM" / "plan crm nvda" / "แผนCRM" → tickers (≤ PLAN_MAX) · "แผน" → [] · None = ไม่ใช่"""
    t = (text or "").strip()
    low = t.lower()
    for w in _CMD_WORDS:
        if not low.startswith(w):
            continue
        rest = t[len(w):]
        tickers = parse_tickers(rest)
        if rest and not rest[0].isspace() and (w == "plan" or not tickers):
            return None                     # "แผนการ" / "planet" — คำอื่น ไม่ใช่คำสั่ง
        return tickers[:PLAN_MAX]
    return None


def plan_unavailable_reason(snap):
    """ทำไมทำแผนไม่ได้ (ข้อความไทย) — None = ทำได้"""
    lv = snap.get("levels")
    if lv is None:
        if snap.get("pending_reaction"):
            return "⏳ รอวันตอบรับงบ — ยังไม่มีแท่ง D0 ให้ตั้ง SL/แนว ลองใหม่พรุ่งนี้เช้า"
        return "ไม่มีงบใน 60 วัน — ไม่มี setup หลังงบให้ทำแผน"
    if not positive_reaction(lv):
        pct = lv.get("reaction_pct")
        shown = f" ({pct:+.1f}%)" if pct is not None else ""
        return f"วันตอบรับงบปิดตอบรับลบ{shown} — ไม่เข้าเกณฑ์ ไม่ทำแผน"
    if lv.get("sl") is None or lv.get("d0_high") is None or lv.get("d0_open") is None:
        return "ข้อมูลแนววันงบไม่ครบ — ทำแผนไม่ได้"
    return None


def _entry(kind, label, entry, price, sl):
    risk = entry - sl
    valid = risk > 0
    if kind == "now":
        state = "below_sl" if price < sl else "ok"
        valid = valid and state == "ok"
    elif kind == "breakout":
        state = "pending" if price < entry else "above"
    else:
        state = "waiting" if price > entry else "in_zone"
    return {
        "kind": kind, "label": label, "entry": entry, "state": state,
        "risk": risk if valid else None,
        "risk_pct": risk / entry * 100 if valid and entry else None,
        "targets": [entry + r * risk for r in TARGET_R] if valid else [],
    }


def _dr_rows(entries, sl, mult, risk_amount):
    rows = []
    for e in entries:
        entry_thb, sl_thb = e["entry"] * mult, sl * mult
        units = cost = None
        if risk_amount and e["risk"] is not None and entry_thb > sl_thb:
            n = math.floor(risk_amount / (entry_thb - sl_thb) / LOT) * LOT
            if n >= LOT:
                units, cost = n, n * entry_thb
        rows.append({"kind": e["kind"], "entry_thb": entry_thb, "sl_thb": sl_thb,
                     "targets_thb": [t * mult for t in e["targets"]],
                     "units": units, "cost_thb": cost})
    return rows


def rank_drs(drs, max_n=DR_MAX_PLAN):
    """เรียง DR ตามวอลุ่มเฉลี่ย (มาก → น้อย) ตัดที่ max_n — คืน (ที่แสดง, จำนวนที่ตัด)"""
    ordered = sorted(drs, key=lambda d: d.get("avg_volume") or -1, reverse=True)
    return ordered[:max_n], max(0, len(ordered) - max_n)


def build_plan(snap, risk_amount=None, drs=()):
    """แผนจาก snapshot (levels ต้องครบ — เช็คด้วย plan_unavailable_reason ก่อน)

    drs: [{"dr", "ratio", "fx", "dr_price", "avg_volume"}] (ratio = implied ratio จาก dr.py)
    คืน dict: symbol, price, sl, sl_pct, entries[3], risk_amount, drs[{... rows[3]}]
    """
    lv = snap["levels"]
    price, sl = snap["price"], lv["sl"]
    levels = {"now": price, "breakout": lv["d0_high"], "pullback": lv["d0_open"]}
    entries = [_entry(k, label, levels[k], price, sl) for k, label in ENTRIES]
    out_drs = []
    for d in drs:
        mult = (d.get("fx") or 0) * (d.get("ratio") or 0)
        if mult <= 0:
            continue
        out_drs.append({**d, "rows": _dr_rows(entries, sl, mult, risk_amount)})
    return {"symbol": snap["symbol"], "price": price, "sl": sl,
            "sl_pct": lv.get("sl_pct"), "entries": entries,
            "risk_amount": risk_amount, "drs": out_drs}
