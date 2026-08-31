"""เกณฑ์ไทย "มีชีวิต" หลังงบ — จำ D0 ของตัวที่ติดสแกน แล้วคิดคะแนน SET ซ้ำรายวันจนครบ RESCORE_DAYS

ทำไม: บล็อกความต่อเนื่อง 6 คะแนน (ความถี่ไฮใหม่ + weekly streak) ต้องพิสูจน์ด้วยเวลา — วันแรกเพดาน ~11
แต่หน้าต่างสแกนเดิมเห็นแค่ D0–D0+lookback ตัวที่ "ค่อย ๆ แข็งแรง" จึงไม่มีวันถึงเกณฑ์ ที่นี่ตามต่อให้
แล้ว upsert ลง scan_log.csv เดิม (schema เดิม — gem-lab/dashboard อ่านไฟล์เดียวกันต่อได้ทันที)
และแจ้งเฉพาะตัวที่ "เพิ่งข้ามเกณฑ์ครั้งแรก" (คะแนน ≥ SET_QUALIFY_MIN จาก config)

ตามเฉพาะตัวที่ผ่านด่านวันแรก (แถวใน scan_log = set_hit หรือเข้าเกณฑ์เดิม) — ตัวที่ไม่มี
ปฏิกิริยาบวกวันแรกไม่ตามย้อนหลัง ตามปรัชญา Set screnner · ดึงราคาไม่ได้ = ข้าม รอลองพรุ่งนี้

state: rescore_state.json {symbol: {earn_date, d0, grade, qualified}} — gitignored
qualified = วันที่ข้ามเกณฑ์ครั้งแรก (กันแจ้งซ้ำข้ามวัน — retry วันเดียวกันแจ้งซ้ำได้) · grade = เกรด composite ของ D0 ติดไปกับแถว CSV
"""
import json
import logging
from datetime import date, timedelta

from bot import scan_csv
from bot.config import PROJECT_ROOT
from bot.fileio import write_json_atomic
from bot.set_score import SET_SCORE_MAX, set_score, stars

logger = logging.getLogger("bot.rescore")

STATE_PATH = PROJECT_ROOT / "rescore_state.json"


def _valid_entry(v):
    """entry ใช้ได้ = dict ที่ d0 เป็นวันที่ ISO — ที่เหลือถือว่าเสีย (คัดทิ้ง ไม่ให้ล้มทั้งสแกน)"""
    if not isinstance(v, dict):
        return False
    try:
        date.fromisoformat(v.get("d0") or "")
    except (TypeError, ValueError):
        return False
    return True


def load_state(path=None):
    path = STATE_PATH if path is None else path
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    bad = sorted(sym for sym, v in data.items() if not _valid_entry(v))
    if bad:
        logger.warning("rescore state: คัด entry เสียทิ้ง %d ตัว (%s) — ที่เหลือไปต่อ",
                       len(bad), ", ".join(bad))
    return {sym: v for sym, v in data.items() if sym not in set(bad)}


def save_state(state, path=None):
    write_json_atomic(STATE_PATH if path is None else path, state)


def track(state, rows, today, days):
    """จำแถวที่ติดสแกนวันนี้ + ตัดตัวที่งบเก่าเกินกรอบ — คืน state ใหม่ (pure ไม่แตะไฟล์)

    รอบงบเดิม (earn_date เท่าเดิม) คง qualified ไว้ · งบไตรมาสใหม่เริ่มนับหนึ่งใหม่
    กรอบ days นับจาก D0 (วันตอบรับจริง) — งบประกาศศุกร์เย็น D0 คือวันทำการถัดไป
    """
    cutoff = (today - timedelta(days=days)).isoformat()
    out = {sym: dict(v) for sym, v in state.items()
           if (v.get("d0") or v.get("earn_date") or "") >= cutoff}
    for r in rows:
        prev = out.get(r["symbol"])
        if prev and prev.get("earn_date") == r.get("earnings_date"):
            prev.update(d0=r["d0"], grade=r.get("grade"))
        else:
            out[r["symbol"]] = {"earn_date": r.get("earnings_date"),
                                "d0": r["d0"], "grade": r.get("grade"),
                                "qualified": None}
    return out


def due(state, today, days, exclude=()):
    """ตัวที่ต้องคิดคะแนนซ้ำวันนี้ — ในกรอบ days (นับจาก D0) และไม่ใช่แถวที่สแกนรอบนี้เพิ่งคิดสดไปแล้ว"""
    cutoff = (today - timedelta(days=days)).isoformat()
    return sorted(sym for sym, v in state.items()
                  if sym not in exclude and (v.get("d0") or v.get("earn_date") or "") >= cutoff)


def rescore_entries(state, symbols, get_bars):
    """คิดคะแนนสดจาก bars ปัจจุบัน → ([(แถวให้ scan_csv, ผล set_score)], {symbol: pts})

    get_bars(symbol) → bars most-recent-first หรือ None — ตัวที่ไม่มีราคา/คิดไม่ได้ ข้ามเงียบ ๆ
    (ไม่ลงโทษเป็นคะแนน 0 — พรุ่งนี้ due จะหยิบมาลองใหม่เอง)
    """
    entries, pts_map = [], {}
    for sym in symbols:
        st = state[sym]
        bars = get_bars(sym)
        ss = set_score(bars, st["d0"]) if bars else None
        if ss is None:
            continue
        row = {"symbol": sym, "earnings_date": st.get("earn_date"),
               "ret_d0_pct": ss.get("ret_d0_pct"), "vol_ratio": ss.get("vol_ratio"),
               "set_pts": ss["pts"], "grade": st.get("grade")}
        entries.append((row, ss))
        pts_map[sym] = ss["pts"]
    return entries, pts_map


def first_crossings(state, pts_map, today, min_pts, days_map=None):
    """ตัวที่เพิ่งข้ามเกณฑ์ครั้งแรก — mark qualified ใน state (คืน state ใหม่, list ตัวที่ข้าม)

    เรียกซ้ำวันเดียวกันได้ตัวเดิมกลับมา (retry หลังส่งล้มต้องไม่ทำ ⭐/auto-watch หายถาวร) —
    ข้ามเฉพาะตัวที่ qualified ไปแล้ว *ก่อนวันนี้* · days_after เอาจาก days_map
    (วันทำการหลัง D0 ที่ set_score นับจากแท่งจริง) — ไม่มีค่อยถอยไปนับวันปฏิทิน
    """
    out = {sym: dict(v) for sym, v in state.items()}
    crossed = []
    for sym in sorted(pts_map):
        pts, st = pts_map[sym], out.get(sym)
        if st is None or pts is None or pts < min_pts:
            continue
        q = st.get("qualified")
        if q and q != today.isoformat():
            continue
        st["qualified"] = today.isoformat()
        days_after = (days_map or {}).get(sym)
        if days_after is None:
            days_after = (today - date.fromisoformat(st["d0"])).days
        crossed.append({"symbol": sym, "pts": pts, "days_after": days_after,
                        "grade": st.get("grade")})
    crossed.sort(key=lambda c: (-c["pts"], c["symbol"]))
    return out, crossed


def format_crossed(items, min_pts):
    """ข้อความแจ้งตัวข้ามเกณฑ์ครั้งแรก — ว่าง = "" (ไม่ส่ง)"""
    if not items:
        return ""
    lines = [f"⭐ ข้ามเกณฑ์ไทยครั้งแรก (≥{min_pts}/{SET_SCORE_MAX}):"]
    for c in items:
        grade = c.get("grade") or "?"
        lines.append(f"• {c['symbol']} {c['pts']}/{SET_SCORE_MAX} {stars(c['pts'])}"
                     f" — วันทำการที่ {c['days_after']} หลังงบ · เกรดเดิม {grade}")
    lines.append("เข้า auto-watch 30 วันแล้ว — เตือนทะลุแนว/หลุด ⛔ ต่อให้เอง")
    return "\n".join(lines)


def run(rows, scored, get_bars, today, min_pts, days,
        csv_path=None, state_path=None, prefetch=None):
    """ขั้นตอนหลังสแกนรายวัน (เรียกจาก _do_scan_and_send *หลัง* ส่งรายงานสแกนแล้ว):
    จำตัวติดใหม่ → คิดคะแนนซ้ำตัวเก่าในกรอบ → upsert scan_log.csv → หาตัวข้ามเกณฑ์ครั้งแรก

    คืน list ตัวที่เพิ่งข้ามเกณฑ์ (รวมตัวที่ถึงตั้งแต่วันสแกนแรก — ใช้คะแนนสดที่สแกนคิดแล้ว
    ไม่ดึงราคาซ้ำ) · เรียกซ้ำวันเดียวกันได้ตัวเดิมกลับมา (retry หลังส่งล้มไม่ทำสัญญาณหาย)
    ข้ามวันแล้วถึงหยุดแจ้ง · prefetch(symbols) อุ่น cache ก่อนลูปดึงทีละตัว (ไม่มี = ดึง serial เดิม)
    """
    picked = scan_csv.pick_rows(rows)
    state = track(load_state(state_path), picked, today, days)
    todays_pts = {r["symbol"]: (scored.get(r["symbol"]) or {}).get("pts", r.get("set_pts"))
                  for r in picked}
    symbols = due(state, today, days, exclude=set(todays_pts))
    if prefetch and symbols:
        prefetch(symbols)
    entries, pts_map = rescore_entries(state, symbols, get_bars)
    if entries:
        n = scan_csv.record_scan_csv(
            entries, today, path=csv_path or scan_csv.SCAN_CSV_PATH)
        logger.info("rescore: คิดซ้ำ %d ตัว → scan_log.csv %d แถว", len(symbols), n)
    # days_after = วันทำการหลัง D0 จาก set_score (แถวสแกนวันนี้ + ตัวคิดซ้ำ) — ไม่มีค่อยถอยเป็นวันปฏิทิน
    days_map = {r["symbol"]: (scored.get(r["symbol"]) or {}).get("days_after")
                for r in picked}
    days_map.update({row["symbol"]: ss.get("days_after") for row, ss in entries})
    state, crossed = first_crossings(state, {**todays_pts, **pts_map},
                                     today, min_pts, days_map)
    save_state(state, state_path)
    return crossed
