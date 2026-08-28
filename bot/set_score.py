"""เกณฑ์คะแนนแบบ Set screnner — port stock_core._post_earnings_signals + signal_score ตัวต่อตัว (น้ำหนัก/ดาวเท่ากัน)

ปรัชญา SET: คะแนนคิดใหม่ทุกวันจากราคาย้อนหลัง ("คำนวณย้อนหลังได้เสมอ") — น้ำหนักมากสุดคือ *ความต่อเนื่อง*
ของการทำไฮใหม่หลังงบ (6 คะแนน) ซึ่งต้องพิสูจน์ด้วยเวลา: วันแรกหลังงบได้สูงสุด 11 (⭐⭐), ⭐⭐⭐ (≥13) เฉพาะตัวที่ทะลุไฮ 3 เดือน
และทำไฮต่อเนื่องจริง · คนละมุมกับ composite 5-factor (คิดครั้งเดียว ณ D0) จึงวางคู่กันใน /scanlog + scan_log.csv (port จาก HK Stock Screener hk/set_score.py 28 ส.ค. 2026)

ต่างจาก SET ที่ตั้งใจ: D0 (วันตอบรับ) รู้จาก timing bmo/amc ของปฏิทิน (bot.levels.compute_levels) ไม่ต้องเดา "วันไหน vol สูงกว่า"
bars = list[dict] most-recent-first (คีย์ date/open/high/low/close/volume เหมือน bot.levels / bot.prices.get_prices)
"""
from datetime import date

SET_MIN_RET_PCT = 2.0        # scanner.MIN_CHANGE_PCT ของ SET: ปิดวันตอบรับ ≥ +2%
SET_MIN_VOL_RATIO = 1.5      # scanner.MIN_VOL_RATIO: vol วันตอบรับ ≥ 1.5× เฉลี่ย 20 วันก่อน
SET_SCORE_MAX = 15
_STAR_BANDS = ((13, "⭐⭐⭐"), (9, "⭐⭐"), (5, "⭐"))
_PRE_3M_BARS = 63            # ไฮ 3 เดือน (~63 วันทำการ) ก่อนงบ
_PRE_5D_BARS = 5
_MIN_PRE_BARS = 6            # SET: start < 6 → ไม่ให้คะแนน
_VOL_AVG_BARS = 20
_RATIO_MIN_POST_DAYS = 5     # ความถี่ทำไฮใหม่เริ่มวัดเมื่อมีข้อมูล ≥5 วันหลังงบ


def stars(pts):
    """⭐⭐⭐ ≥13 · ⭐⭐ ≥9 · ⭐ ≥5 · "" ต่ำกว่า/None"""
    if pts is None:
        return ""
    for lo, s in _STAR_BANDS:
        if pts >= lo:
            return s
    return ""


def is_set_hit(ret_d0_pct, vol_ratio, turnover=None, min_turnover=0.0,
               min_ret=SET_MIN_RET_PCT, min_vol=SET_MIN_VOL_RATIO):
    """ด่านเข้าแบบ SET (ปิด D0 ≥ min_ret & vol ≥ min_vol) + ด่านสภาพคล่องเมื่อให้ min_turnover (> 0; US ไม่ใช้ — universe S&P500/DR) · None → False"""
    if ret_d0_pct is None or vol_ratio is None:
        return False
    if ret_d0_pct < min_ret or vol_ratio < min_vol:
        return False
    if min_turnover and (turnover is None or turnover < min_turnover):
        return False
    return True


def _post_signals(asc, start):
    """= _post_earnings_signals ของ SET บน list เรียงเก่า → ใหม่ (start = index ของ D0)"""
    highs = [b["high"] for b in asc]
    lows = [b["low"] for b in asc]
    closes = [b["close"] for b in asc]

    pre3m_high = max(highs[max(0, start - _PRE_3M_BARS):start])
    pre5d_high = max(highs[start - _PRE_5D_BARS:start])
    post_max_close = max(closes[start:])

    # วันที่ตั้งไฮใหม่ของช่วงหลังงบ (high ≥ ไฮสะสม — วันแรกเป็นไฮใหม่เสมอ)
    post_highs = highs[start:]
    running, is_new = None, []
    for h in post_highs:
        running = h if running is None else max(running, h)
        is_new.append(h >= running)
    last_new_pos = max(i for i, v in enumerate(is_new) if v)
    days_since_new_high = len(post_highs) - 1 - last_new_pos

    later = is_new[1:]                       # ไม่นับวันแรก
    post_days = len(later)
    new_high_ratio = round(sum(later) / post_days, 2) if post_days >= _RATIO_MIN_POST_DAYS else None

    # ไฮรายสัปดาห์ ISO ยกสูงขึ้นต่อเนื่องกี่สัปดาห์ (สัปดาห์ล่าสุดยังไม่จบ → ถ้ายังไม่ผ่านไฮสัปดาห์ก่อน ประเมินจากสัปดาห์ที่จบแล้ว)
    weekly, cur = [], None
    for b, h in zip(asc[start:], post_highs):
        key = date.fromisoformat(b["date"]).isocalendar()[:2]
        if key != cur:
            weekly.append(h)
            cur = key
        elif h > weekly[-1]:
            weekly[-1] = h
    i = len(weekly) - 1
    if i >= 1 and weekly[i] <= weekly[i - 1]:
        i -= 1
    streak = 0
    while i >= 1 and weekly[i] > weekly[i - 1]:
        streak += 1
        i -= 1

    pre_low = min(lows[start - _PRE_5D_BARS:start])
    price = closes[-1]
    return {
        "broke_5d": post_max_close > pre5d_high,
        "broke_3m": post_max_close > pre3m_high,
        "days_since_new_high": days_since_new_high,
        "new_high_ratio": new_high_ratio,
        "weekly_hh_streak": streak,
        "pre_low": pre_low,
        "above_pre_low": price > pre_low,
        "price": price,
    }


def _points(ret, vr, s):
    """= signal_score ของ SET (0-15)"""
    pts = 0
    if ret >= 5:
        pts += 2
    elif ret >= 2.5:
        pts += 1
    if vr >= 3:
        pts += 2
    elif vr >= 2:
        pts += 1
    if s["broke_5d"]:
        pts += 1
    if s["broke_3m"]:
        pts += 3
    if s["days_since_new_high"] <= 1:          # ── ความต่อเนื่อง (รวม 6) ──
        pts += 2
    elif s["days_since_new_high"] <= 5:
        pts += 1
    ratio = s["new_high_ratio"]
    if ratio is not None:
        if ratio >= 0.5:
            pts += 2
        elif ratio >= 0.3:
            pts += 1
    if s["weekly_hh_streak"] >= 2:
        pts += 2
    elif s["weekly_hh_streak"] == 1:
        pts += 1
    if s["above_pre_low"]:
        pts += 1
    return pts


def set_score(bars, d0_date):
    """คะแนน SET ณ แท่งล่าสุดใน bars — dict (pts, stars, ret_d0_pct, vol_ratio, องค์ประกอบ, price) หรือ None

    None เมื่อไม่มีแท่ง D0 / มีแท่งก่อน D0 น้อยกว่า 6 / ราคาปิดวันก่อน D0 หรือฐาน vol เป็น 0
    """
    if not bars:
        return None
    idx = next((i for i, b in enumerate(bars) if b.get("date") == d0_date), None)
    if idx is None:
        return None
    asc = bars[::-1]
    start = len(bars) - 1 - idx
    if start < _MIN_PRE_BARS:
        return None
    prev_close = asc[start - 1]["close"]
    vols = [b["volume"] for b in asc[max(0, start - _VOL_AVG_BARS):start]]
    avg = sum(vols) / len(vols) if vols else 0
    if not prev_close or not avg:
        return None
    ret = round((asc[start]["close"] / prev_close - 1) * 100, 2)
    vr = round(asc[start]["volume"] / avg, 2)
    s = _post_signals(asc, start)
    pts = _points(ret, vr, s)
    # since_pct = ราคาล่าสุดเทียบปิดก่อน D0 (= since_earn_pct ของไทย: ปิดก่อนวันงบ) — ลง scan_log.csv
    since = round((s["price"] / prev_close - 1) * 100, 2)
    return {"pts": pts, "stars": stars(pts), "ret_d0_pct": ret, "vol_ratio": vr, "since_pct": since, **s}
