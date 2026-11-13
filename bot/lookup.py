"""Lookup รายตัว: พิมพ์ ticker → snapshot ราคา + วันงบ + สัญญาณหลังงบ

ราคา EOD ผ่าน bot.prices (Yahoo หลัก, FMP สำรอง) + วันงบรายตัว
daily_prices ทุกฟังก์ชัน = list[dict] most-recent-first (convention เดียวกับ levels.py)
"""
import re
import sys
from datetime import date
from pathlib import Path

ETA_DIR = Path(__file__).resolve().parent / "vendor" / "eta"
if str(ETA_DIR) not in sys.path:
    sys.path.insert(0, str(ETA_DIR))

from analyze_earnings_trades import analyze_stock, normalize_timing  # noqa: E402

from bot import fetch_cache  # noqa: E402
from bot.earnings_store import known_earnings  # noqa: E402
from bot.prices import get_prices  # noqa: E402
from bot.levels import (  # noqa: E402
    compute_levels, detect_gap_pullback, detect_low_break, detect_new_breaks,
    detect_sl_break, infer_bmo, positive_reaction)
from bot.set_score import SET_MIN_RET_PCT, SET_MIN_VOL_RATIO, is_set_hit, set_score  # noqa: E402

LOOKUP_MAX = 5                  # เพดานจำนวนหุ้นต่อหนึ่งข้อความ (คุมงบ API)
RECENT_EARNINGS_DAYS = 60       # งบใหม่กว่านี้ (วันปฏิทิน) ถึงคำนวณสัญญาณหลังงบ
MIN_BARS_FOR_SCORE = 70         # เกณฑ์เดียวกับ screener.run_scan
# ด่านเข้าเกณฑ์ SET ของ US: ปิด D0 ≥2% & vol ≥1.5× เท่านั้น (ไม่มีด่าน turnover — universe S&P500/DR สภาพคล่องพอ)
# ใช้ร่วมกันใน lookup (snap["set_rule"]) และ /scanlog (bot.main)
SET_RULE = {"min_ret_pct": SET_MIN_RET_PCT, "min_vol_ratio": SET_MIN_VOL_RATIO}
# breakout_job ตามเก็บแท่งที่ข้ามไป (เครื่องปิด/วันหยุดไทย) ย้อนสูงสุดเท่านี้ ไม่นับแท่งล่าสุด —
# รวมแท่งล่าสุด = 5 แท่ง ≈ หนึ่งสัปดาห์ซื้อขาย · เก่ากว่านั้นแจ้งไปก็เลยจุดที่ใช้ได้แล้ว
MAX_MISSED_BARS = 4

_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def parse_tickers(text):
    """แยกข้อความเป็นลิสต์ ticker: ตัดคำที่ไม่เข้ารูป, กันซ้ำ, สูงสุด LOOKUP_MAX"""
    out = []
    for tok in (text or "").upper().split():
        if _TICKER_RE.match(tok) and tok not in out:
            out.append(tok)
            if len(out) >= LOOKUP_MAX:
                break
    return out


def _pct(a, base):
    if a is None or not base:
        return None
    return (a - base) / base * 100


def _index_on_or_before(prices, date_str):
    """index ของแท่งวันที่ date_str หรือวันซื้อขายก่อนหน้าที่ใกล้สุด (None = เก่ากว่าข้อมูล)"""
    for i, bar in enumerate(prices):
        if bar.get("date") and bar["date"] <= date_str:
            return i
    return None


def _split_earnings(earnings, last_bar_date):
    """แยกวันงบเป็น (ล่าสุดที่ผ่านแล้ว, รอบถัดไป) โดยใช้วันแท่งล่าสุดเป็นเส้นแบ่ง

    งบ AMC คืนนี้ (ยังไม่มีแท่งใหม่) จะนับเป็น "รอบถัดไป" — ราคายังไม่ทันตอบรับ
    """
    past, future = [], []
    for e in earnings:
        d = e.get("date")
        if not d:
            continue
        (past if d <= last_bar_date else future).append(d)
    return (max(past, default=None), min(future, default=None))


def _timing_for(earnings, date_str):
    for e in earnings:
        if e.get("date") == date_str:
            return normalize_timing(e.get("time"))
    return "unknown"


def build_snapshot(symbol, prices, meta=None, earnings=None, today=None):
    """ประกอบ snapshot จากแท่งราคา (pure function — ไม่ยิงเครือข่าย)

    meta: entry จาก universe (name/dr_symbols) · earnings: raw list จาก FMP
    set / set_rule: เกณฑ์ SET (bot.set_score 0-15 ⭐ คิดสดถึงแท่งล่าสุด + hit = ด่านเข้า SET_RULE)
    เฉพาะงบ ≤ RECENT_EARNINGS_DAYS ที่มีแท่ง D0 (เงื่อนไขเดียวกับ levels) · ไม่งั้น None
    คืน None ถ้าแท่งราคาไม่พอ
    """
    if not prices or len(prices) < 2:
        return None
    today = today or date.today()
    meta = meta or {}
    last = prices[0]
    price = last["close"]

    vols = [b["volume"] for b in prices[1:21]]
    vol_ratio = None
    if len(vols) == 20:
        avg = sum(vols) / 20
        if avg:
            vol_ratio = round(last["volume"] / avg, 2)

    def chg(n):
        return _pct(price, prices[n]["close"]) if len(prices) > n else None

    snap = {
        "symbol": symbol,
        "name": meta.get("name") or symbol,
        "dr_symbols": meta.get("dr_symbols") or "",
        "last_date": last["date"],
        "price": price,
        "low": last["low"],
        "day_change_pct": _pct(price, prices[1]["close"]),
        "gap_pct": _pct(last["open"], prices[1]["close"]),
        "intraday_pct": _pct(price, last["open"]),
        "chg_5d_pct": chg(5),
        "chg_1m_pct": chg(21),
        "volume": last["volume"],
        "vol_ratio": vol_ratio,
        "hi_5d": max(b["high"] for b in prices[:5]),
        "lo_5d": min(b["low"] for b in prices[:5]),
        "hi_3m": max(b["high"] for b in prices[:63]),
        "lo_3m": min(b["low"] for b in prices[:63]),
        "hi_52w": max(b["high"] for b in prices[:250]) if len(prices) >= 240 else None,
        "lo_52w": min(b["low"] for b in prices[:250]) if len(prices) >= 240 else None,
        "last_earnings": None, "next_earnings": None,
        "days_since_earnings": None, "days_to_earnings": None,
        "since_earnings_pct": None, "reaction_pct": None, "timing": "unknown",
        "levels": None, "score": None, "grade": None,
        "pending_reaction": False, "new_breaks": [], "sl_break": False,
        "low_break": False, "gap_pullback": False,
        "set": None, "set_rule": None,
    }

    if not earnings:
        return snap

    last_e, next_e = _split_earnings(earnings, last["date"])
    if next_e:
        snap["next_earnings"] = next_e
        snap["days_to_earnings"] = (date.fromisoformat(next_e) - today).days
    if not last_e:
        return snap

    snap["last_earnings"] = last_e
    snap["days_since_earnings"] = (today - date.fromisoformat(last_e)).days
    timing = _timing_for(earnings, last_e)
    snap["timing"] = timing

    earn_idx = _index_on_or_before(prices, last_e)
    if earn_idx is None:
        return snap
    # FMP อาจให้วันงบที่ไม่ใช่วันซื้อขาย → ใช้วันแท่งจริงกับ compute_levels
    earn_bar_date = prices[earn_idx]["date"]

    if timing == "unknown" and infer_bmo(prices, earn_bar_date):
        timing = "bmo"
        snap["timing"] = "bmo*"  # อนุมานจากแท่งราคา ไม่ใช่ปฏิทิน

    d0 = earn_idx if timing == "bmo" else earn_idx - 1
    if d0 >= 0 and d0 + 1 < len(prices):
        pre_close = prices[d0 + 1]["close"]
        snap["reaction_pct"] = _pct(prices[d0]["close"], pre_close)
        snap["since_earnings_pct"] = _pct(price, pre_close)

    if snap["days_since_earnings"] <= RECENT_EARNINGS_DAYS:
        levels = compute_levels(prices, earn_bar_date, timing)
        snap["levels"] = levels
        if levels is None:
            snap["pending_reaction"] = True  # งบเพิ่งออก ยังไม่มีวันตอบรับ
        else:
            snap["new_breaks"] = detect_new_breaks(prices, levels)
            snap["sl_break"] = detect_sl_break(prices, levels)
            snap["low_break"] = detect_low_break(prices, levels)
            snap["gap_pullback"] = detect_gap_pullback(prices, levels)
            # เกรดเฉพาะตอบรับบวก — เกณฑ์เดียวกับ screener (5-factor ไม่สนทิศ gap)
            if len(prices) >= MIN_BARS_FOR_SCORE and positive_reaction(levels):
                analysis = analyze_stock(prices, earn_bar_date, timing)
                snap["score"] = analysis["composite"]["composite_score"]
                snap["grade"] = analysis["composite"]["grade"]
            # เกณฑ์ SET คู่เกรดเดิม — คะแนนโชว์เสมอ (แม้ตกด่านเข้า) เหมือน lookup ของบอทไทย
            ss = set_score(prices, levels["reaction_date"])
            d0_idx = _index_on_or_before(prices, levels["reaction_date"])
            if ss and d0_idx is not None:
                tv = prices[d0_idx]["close"] * prices[d0_idx]["volume"]
                snap["set"] = {**ss, "turnover_d0": tv,
                               "hit": is_set_hit(ss["ret_d0_pct"], ss["vol_ratio"])}
                snap["set_rule"] = SET_RULE
    return snap


def lookup_symbol(client, symbol, universe, today=None, get_prices_fn=None,
                  known_earnings_fn=known_earnings):
    """ดึงข้อมูลหุ้นหนึ่งตัวแล้วประกอบ snapshot (None = ไม่พบข้อมูล/ไม่มีแหล่งราคา)

    get_prices_fn(symbol, days) → แท่งราคา (ค่าเริ่มต้น bot.prices.get_prices:
    cache → Yahoo → FMP สำรอง) · ticker ผิดหรือทุกแหล่งว่าง = None เหมือนกัน
    known_earnings_fn(symbol) → วันงบที่บอทรู้เอง (คลัง earnings_calendar.json ∪ signals.json)
    ใช้ก่อน — FMP รายตัว (402 เกือบทุกตัวในแผนฟรี + rate-limit) ยิงเฉพาะตอนไม่รู้อะไรเลย
    ราคา/วันงบผ่าน fetch_cache — job เช้าหลายตัวดึงหุ้นชุดเดียวกันไม่เปลืองงบซ้ำ
    """
    fetch = get_prices_fn or (lambda s, d: get_prices(s, d, client=client))
    prices = fetch_cache.get(("prices", symbol, 250))
    if prices is None:
        prices = fetch(symbol, 250)
        if not prices or len(prices) < 2:
            return None
        fetch_cache.put(("prices", symbol, 250), prices)
    earnings = known_earnings_fn(symbol) if known_earnings_fn is not None else None
    if not earnings:
        earnings = fetch_cache.cached(
            ("earnings", symbol), lambda: client.get_earnings_dates(symbol))
    return build_snapshot(symbol, prices, meta=universe.get(symbol),
                          earnings=earnings, today=today)


def missed_snapshots(symbol, universe, since, today=None,
                     known_earnings_fn=known_earnings, max_bars=MAX_MISSED_BARS):
    """snapshot "ณ แท่งนั้น" ของแท่งที่อยู่ระหว่าง since กับแท่งล่าสุด — เรียงเก่า→ใหม่

    detector ทุกตัว (ทะลุแนว/หลุด SL/หลุด Low/ย่อเข้า gap) เป็น edge เทียบแท่งล่าสุดกับแท่ง
    ก่อนหน้า — รอบที่บอทไม่ได้รัน edge ของแท่งนั้นจึงไม่มีใครเห็นอีก ฟังก์ชันนี้คิด snapshot
    ย้อนด้วย build_snapshot ตัวเดิมบนแท่งที่ตัดหัวออก (prices[i:]) = สิ่งที่บอทควรเห็นเช้าวันนั้น
    since: วันแท่งล่าสุดที่ breakout_job แจ้งจบไปแล้ว (ISO) · ว่าง/None = ยังไม่เคย → ไม่ย้อน
    ไม่รวมแท่งล่าสุด (หน้าที่ lookup_symbol) · ย้อนสูงสุด max_bars แท่ง
    แต่ละตัวติด late=True + now_price (ปิดล่าสุดจริง) ให้ข้อความบอกได้ว่าเป็นของย้อนหลัง
    ราคา/วันงบอ่านจาก fetch_cache ที่ lookup_symbol เพิ่งเติมเท่านั้น — ไม่ยิงเครือข่ายเอง
    (ไม่มีใน cache = คืนว่าง) · today ใช้วันจริงเหมือนแท่งล่าสุด: setup ที่เลย
    RECENT_EARNINGS_DAYS ไปแล้ววันนี้ไม่ถูกปลุกย้อน
    """
    if not since:
        return []
    prices = fetch_cache.get(("prices", symbol, 250))
    if not prices:
        return []
    earnings = known_earnings_fn(symbol) if known_earnings_fn is not None else None
    if not earnings:
        earnings = fetch_cache.get(("earnings", symbol))
    out = []
    for i in range(1, min(max_bars, len(prices) - 1) + 1):
        if prices[i]["date"] <= since:
            break
        snap = build_snapshot(symbol, prices[i:], meta=universe.get(symbol),
                              earnings=earnings, today=today)
        if snap is None:
            break
        snap["late"] = True
        snap["now_price"] = prices[0]["close"]
        out.append(snap)
    out.reverse()
    return out
