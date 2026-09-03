"""เกณฑ์ไทย "มีชีวิต" หลังงบ — จำ D0 ของตัวที่ติดสแกน แล้วคิดคะแนน SET ซ้ำรายวันจนครบ RESCORE_DAYS

ทำไม: บล็อกความต่อเนื่อง 6 คะแนน (ความถี่ไฮใหม่ + weekly streak) ต้องพิสูจน์ด้วยเวลา — วันแรกเพดาน ~11
แต่หน้าต่างสแกนเดิมเห็นแค่ D0–D0+lookback ตัวที่ "ค่อย ๆ แข็งแรง" จึงไม่มีวันถึงเกณฑ์ ที่นี่ตามต่อให้
แล้ว upsert ลง scan_log.csv เดิม (schema เดิม — gem-lab/dashboard อ่านไฟล์เดียวกันต่อได้ทันที)
และแจ้งเฉพาะตัวที่ "เพิ่งข้ามเกณฑ์ครั้งแรก" (คะแนน ≥ SET_QUALIFY_MIN จาก config)

ตามเฉพาะตัวที่ผ่านด่านวันแรก (แถวใน scan_log = set_hit หรือเข้าเกณฑ์เดิม) — ตัวที่ไม่มี
ปฏิกิริยาบวกวันแรกไม่ตามย้อนหลัง ตามปรัชญา Set screnner · ดึงราคาไม่ได้ = ข้าม รอลองพรุ่งนี้

state: rescore_state.json {symbol: {earn_date, d0, grade, qualified, skip_streak, skip_reason, skip_date}} — gitignored
qualified = วันที่ข้ามเกณฑ์ครั้งแรก (กันแจ้งซ้ำข้ามวัน — retry วันเดียวกันแจ้งซ้ำได้) · grade = เกรด composite ของ D0 ติดไปกับแถว CSV
skip_streak/skip_reason = ข้ามติดกันกี่วันและเพราะอะไร (entry เก่าไม่มีคีย์นี้ = 0/None) — ข้ามติดกันคือ
"หลุดจากการตาม 14 วัน" เงียบ ๆ เช่น Yahoo เขียนแท่ง D0 ทิ้ง จึงต้องเตือน (stale_notice) และโชว์ที่ /status
skip_date = วันที่นับสตรีคไปแล้ว — สแกนซ้ำวันเดียวกัน (job รายวัน + /scan) ต้องไม่เพิ่มสตรีค เพราะนับเป็น "วัน"
stale_notice_due = ธง "ยังไม่ได้แจ้ง ⚠️ รอบนี้" ปักตอนสตรีคขึ้นเป็น 2 พอดี แล้ว pop_stale_notices กินทิ้ง —
⚠️ เป็น *เหตุการณ์* 1→2 ไม่ใช่สภาพ ถ้ากรองจากสตรีคทุกรอบ สแกนซ้ำวันเดิมจะยิงข้อความเดิมซ้ำ
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
SKIP_REASON_TH = {"no_bars": "ดึงราคาไม่ได้", "score_none": "คิดคะแนนไม่ได้"}   # no_d0_bar/error:X ประกอบข้อความเอง


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
    """คิดคะแนนสดจาก bars ปัจจุบัน → ([(แถวให้ scan_csv, ผล set_score)], {symbol: pts}, {symbol: เหตุที่ข้าม})

    get_bars(symbol) → bars most-recent-first หรือ None — ตัวที่ไม่มีราคา/คิดไม่ได้ ข้าม *พร้อมบอกเหตุ*
    (ไม่ลงโทษเป็นคะแนน 0 — พรุ่งนี้ due จะหยิบมาลองใหม่เอง) เพราะข้ามเงียบ ๆ = หลุดจากการตาม 14 วันโดยไม่มีใครรู้
    เหตุ: no_bars (ดึงราคาไม่ได้) · no_d0_bar (Yahoo เขียนแท่ง D0 ทิ้ง) · score_none (แท่งก่อนงบไม่พอ ฯลฯ) ·
    error:<ชื่อ exception> — ตัวเดียวพังต้องไม่ล้มทั้งลูป (เดิม: ทุกตัวหายจากการตามพร้อมกัน)
    """
    entries, pts_map, skipped = [], {}, {}
    for sym in symbols:
        try:
            st = state[sym]
            bars = get_bars(sym)
            if not bars:
                skipped[sym] = "no_bars"
                continue
            ss = set_score(bars, st["d0"])
            if ss is None:
                # หาแท่ง D0 แบบเดียวกับ set_score — แท่งหายกับคิดไม่ได้คนละเหตุ คนละทางแก้
                skipped[sym] = ("no_d0_bar"
                                if not any(b.get("date") == st["d0"] for b in bars)
                                else "score_none")
                continue
            row = {"symbol": sym, "earnings_date": st.get("earn_date"),
                   "ret_d0_pct": ss.get("ret_d0_pct"), "vol_ratio": ss.get("vol_ratio"),
                   "set_pts": ss["pts"], "grade": st.get("grade")}
        except Exception as exc:
            logger.exception("rescore: %s ล้ม — ข้ามตัวนี้ ตัวที่เหลือไปต่อ", sym)
            skipped[sym] = f"error:{type(exc).__name__}"
            continue
        entries.append((row, ss))
        pts_map[sym] = ss["pts"]
    return entries, pts_map, skipped


def _stale_item(sym, v):
    """entry ใน state → รูปที่ stale_entries/pop_stale_notices/stale_notice ใช้ร่วมกัน"""
    return {"symbol": sym, "d0": v.get("d0"),
            "skip_streak": v.get("skip_streak") or 0,
            "skip_reason": v.get("skip_reason")}


def stale_entries(state, min_streak=2):
    """ตัวที่ข้ามติดกัน ≥ min_streak วัน — เรียงตามรหัส (entry เก่าไม่มี skip_streak = 0 ไม่ติด)

    ใช้กับ /status ที่ถามว่า "ตอนนี้มีตัวไหนค้าง" — ส่วนการ *แจ้ง* ใช้ pop_stale_notices
    """
    return [_stale_item(sym, v) for sym, v in sorted(state.items())
            if (v.get("skip_streak") or 0) >= min_streak]


def pop_stale_notices(path=None):
    """ตัวที่ run() เพิ่งปักธง ⚠️ ไว้ (สตรีคขึ้นเป็น 2 พอดี) — คืนครั้งเดียวแล้วล้างธงลงไฟล์

    ⚠️ ต้องเป็นเหตุการณ์ ไม่ใช่การกรองสภาพ: _do_scan_and_send รันได้หลายรอบต่อวัน (job + /scan +
    catch-up) การกรอง skip_streak == 2 ใหม่ทุกรอบจึงยิงข้อความเดิมซ้ำ · entry เก่าไม่มีคีย์นี้ = ไม่ติด
    ล้มตอนส่งหลังกินธงแล้ว = เสียใบแจ้งนั้นไป (ตัวนั้นยังโชว์ที่ /status)
    """
    state = load_state(path)
    items = [_stale_item(sym, v) for sym, v in sorted(state.items())
             if v.get("stale_notice_due")]
    if items:
        for it in items:
            state[it["symbol"]]["stale_notice_due"] = False
        save_state(state, path)
    return items


def _skip_reason_th(reason, d0):
    """เหตุที่ข้าม → ไทย (no_d0_bar บอกวัน D0 ที่หายไปด้วย — ผู้ใช้เช็ค Yahoo ต่อได้ทันที)"""
    if reason == "no_d0_bar":
        return f"ไม่มีแท่ง D0 {d0} ใน Yahoo"
    if (reason or "").startswith("error:"):
        return f"error {reason.split(':', 1)[1]}"
    return SKIP_REASON_TH.get(reason, reason or "ไม่ทราบเหตุ")


def stale_notice(stale):
    """ข้อความเตือนตัวที่ข้ามติดกัน (บรรทัดละตัว) — None = ไม่มีอะไรต้องเตือน (ไม่ส่ง)"""
    if not stale:
        return None
    return "\n".join(
        f"⚠️ เกณฑ์ไทย 14 วัน: ข้าม {s['symbol']} {s['skip_streak']} วันติด"
        f" — {_skip_reason_th(s.get('skip_reason'), s.get('d0'))}"
        for s in stale)


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


def format_crossed(items, min_pts, auto_days=30):
    """ข้อความแจ้งตัวข้ามเกณฑ์ครั้งแรก — ว่าง = "" (ไม่ส่ง)

    บรรทัดบริบท (ราคา/%จากงบ/⛔) โผล่เมื่อ crossed พกมา (run เติมให้) —
    entry จาก state เก่าที่ไม่มีก็ยังแจ้งบรรทัดหลักได้ · auto_days = AUTO_WATCH_DAYS จริงจากผู้เรียก
    """
    if not items:
        return ""
    lines = [f"⭐ ข้ามเกณฑ์ไทยครั้งแรก (≥{min_pts}/{SET_SCORE_MAX}):"]
    for c in items:
        grade = c.get("grade") or "?"
        lines.append(f"• {c['symbol']} {c['pts']}/{SET_SCORE_MAX} {stars(c['pts'])}"
                     f" — วันทำการที่ {c['days_after']} หลังงบ · เกรดเดิม {grade}")
        if c.get("price") is not None:
            since = (f" · {c['since_pct']:+.1f}% จากงบ"
                     if c.get("since_pct") is not None else "")
            stop = f" · ⛔ {c['pre_low']:,.2f}" if c.get("pre_low") is not None else ""
            lines.append(f"   ราคา {c['price']:,.2f}{since}{stop}")
    lines.append(f"เข้า auto-watch {auto_days} วันแล้ว — เตือนทะลุแนว/หลุด ⛔ ต่อให้เอง")
    return "\n".join(lines)


def signal_candidates(crossed):
    """crossed → รูป candidate ให้ record_signals — signal_type="set_cross"

    feedback loop ของเกณฑ์ SET≥10: flag_date=วันข้าม flag_price=ปิดวันข้าม sl=⛔ pre_low
    → เข้า weekly drift + /stats แยก cohort วัดว่าเกณฑ์นี้ work จริงไหม
    score เก็บ pts (สเกล 0-15 ไม่ใช่ 0-100 — กลุ่ม set_cross แยกอยู่แล้วไม่ปน)
    """
    return [{"symbol": c["symbol"], "grade": c.get("grade"), "score": c.get("pts"),
             "earnings_date": c.get("earn_date"), "signal_type": "set_cross",
             "levels": {"price": c.get("price"), "sl": c.get("pre_low")}}
            for c in crossed]


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
    entries, pts_map, skipped = rescore_entries(state, symbols, get_bars)
    # จำสตรีคการข้าม — ข้ามติดกัน = หลุดจากการตามเงียบ ๆ (ต้องเตือน) · ตัวที่ติดแถวสแกนวันนี้ (todays_pts)
    # คิดคะแนนสดไปแล้ว = สำเร็จ ต้องล้างสตรีคด้วย ไม่งั้น due() ตัดมันออกแล้วสตรีคค้าง → ⚠️ ซ้ำ/ /status ค้างชื่อ
    today_iso = today.isoformat()
    for sym in list(todays_pts) + symbols:  # ทั้งสองชุดมาจาก state (track ลงแถวสแกน · due อ่านจาก state)
        st, reason = state[sym], skipped.get(sym)
        if not reason:
            st.update(skip_streak=0, skip_reason=None, skip_date=None,
                      stale_notice_due=False)
        elif st.get("skip_date") == today_iso:
            st["skip_reason"] = reason      # สแกนซ้ำวันเดิม — อัปเดตเหตุ แต่ไม่เพิ่มสตรีค (สตรีคนับเป็นวัน)
        else:
            streak = (st.get("skip_streak") or 0) + 1
            st.update(skip_streak=streak, skip_reason=reason, skip_date=today_iso)
            if streak == 2:                 # วันแรกที่ "ข้ามถาวร" — ปักธงให้ pop_stale_notices กินไปแจ้ง
                st["stale_notice_due"] = True
    n = 0
    if entries:
        n = scan_csv.record_scan_csv(
            entries, today, path=csv_path or scan_csv.SCAN_CSV_PATH)
    # สรุป *ทุกรอบ* แม้ไม่มีตัวไหนคิดสำเร็จ — เดิม log อยู่ใน `if entries:` จึงเงียบสนิทตอนที่ควรดังที่สุด
    if not symbols:
        logger.info("rescore: ไม่มีตัว due วันนี้")
    else:
        note = (" (ข้าม %d: %s)" % (len(skipped), ", ".join(
            f"{s}={r}" for s, r in sorted(skipped.items()))) if skipped else "")
        logger.info("rescore: คิดซ้ำ %d/%d ตัว → scan_log.csv %d แถว%s",
                    len(entries), len(symbols), n, note)
    # days_after = วันทำการหลัง D0 จาก set_score (แถวสแกนวันนี้ + ตัวคิดซ้ำ) — ไม่มีค่อยถอยเป็นวันปฏิทิน
    days_map = {r["symbol"]: (scored.get(r["symbol"]) or {}).get("days_after")
                for r in picked}
    days_map.update({row["symbol"]: ss.get("days_after") for row, ss in entries})
    state, crossed = first_crossings(state, {**todays_pts, **pts_map},
                                     today, min_pts, days_map)
    save_state(state, state_path)
    # เติมบริบทจาก set_score (สแกนวันนี้ = scored · ตัวคิดซ้ำ = entries) + state —
    # ฐานของข้อความ ⭐ เต็ม และ record ลง signals.json (signal_candidates)
    ss_map = {sym: scored.get(sym) for sym in todays_pts}
    ss_map.update({row["symbol"]: ss for row, ss in entries})
    for c in crossed:
        ss = ss_map.get(c["symbol"]) or {}
        st = state.get(c["symbol"]) or {}
        c.update(price=ss.get("price"), since_pct=ss.get("since_pct"),
                 pre_low=ss.get("pre_low"), earn_date=st.get("earn_date"),
                 d0=st.get("d0"))
    return crossed
