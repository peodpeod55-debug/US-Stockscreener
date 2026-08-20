"""Lookup รายตัว: พิมพ์ ticker → snapshot ราคา + วันงบ + สัญญาณหลังงบ

ใช้ข้อมูล EOD จาก FMP (2 API calls ต่อหุ้น: แท่งราคา 250 วัน + วันงบรายตัว)
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
from bot.levels import compute_levels, detect_new_breaks, detect_sl_break  # noqa: E402

LOOKUP_MAX = 5                  # เพดานจำนวนหุ้นต่อหนึ่งข้อความ (คุมงบ API)
RECENT_EARNINGS_DAYS = 60       # งบใหม่กว่านี้ (วันปฏิทิน) ถึงคำนวณสัญญาณหลังงบ
MIN_BARS_FOR_SCORE = 70         # เกณฑ์เดียวกับ screener.run_scan

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
            if len(prices) >= MIN_BARS_FOR_SCORE:
                analysis = analyze_stock(prices, earn_bar_date, timing)
                snap["score"] = analysis["composite"]["composite_score"]
                snap["grade"] = analysis["composite"]["grade"]
    return snap


class SymbolNotCovered(Exception):
    """FMP ตอบ 402: หุ้นนอกแผนปัจจุบัน (ฟรีทีร์จำกัดรายชื่อ) — ticker ที่ไม่มีจริง
    ก็ได้ 402 เหมือนกัน จึงแยกสองเคสนี้จากกันไม่ได้"""


def lookup_symbol(client, symbol, universe, today=None, fallback_prices_fn=None):
    """ดึงข้อมูลหุ้นหนึ่งตัวแล้วประกอบ snapshot (None = ไม่พบข้อมูล)

    fallback_prices_fn(symbol, days) → แท่งราคาแหล่งสำรอง ใช้เมื่อ FMP ตอบ 402
    raise SymbolNotCovered ถ้าแผน FMP ไม่ครอบคลุมและแหล่งสำรองก็ไม่มีข้อมูล
    ราคา/วันงบผ่าน fetch_cache — job เช้าหลายตัวดึงหุ้นชุดเดียวกันไม่เปลืองงบซ้ำ
    """
    prices = fetch_cache.get(("prices", symbol, 250))
    if prices is None:
        client.saw_402 = False  # ธงต่อ symbol — client ตัวเดียวใช้หลายตัวต่อข้อความ
        prices = client.get_historical_prices(symbol, days=250)
        if not prices or len(prices) < 2:
            if not getattr(client, "saw_402", False):
                return None
            if fallback_prices_fn:
                try:
                    prices = fallback_prices_fn(symbol, 250)
                except Exception:
                    prices = None
            if not prices or len(prices) < 2:
                raise SymbolNotCovered(symbol)
        fetch_cache.put(("prices", symbol, 250), prices)
    earnings = fetch_cache.cached(
        ("earnings", symbol), lambda: client.get_earnings_dates(symbol))
    return build_snapshot(symbol, prices, meta=universe.get(symbol),
                          earnings=earnings, today=today)
