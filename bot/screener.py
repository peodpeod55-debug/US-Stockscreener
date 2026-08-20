"""Core scan: universe → earnings calendar → 5-factor score → levels"""
import csv
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ETA_DIR = Path(__file__).resolve().parent / "vendor" / "eta"
if str(ETA_DIR) not in sys.path:
    sys.path.insert(0, str(ETA_DIR))

from analyze_earnings_trades import analyze_stock, normalize_timing  # noqa: E402
from fmp_client import ApiCallBudgetExceeded, FMPClient  # noqa: E402

from bot.levels import compute_levels  # noqa: E402

UNIVERSE_CSV = PROJECT_ROOT / "us_stock_list.csv"
REPORTS_DIR = PROJECT_ROOT / "reports"


def load_universe(csv_path=UNIVERSE_CSV):
    """หุ้นที่มี DR ไทย หรืออยู่ใน S&P 500 → ticker -> metadata"""
    universe = {}
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row.get("dr") == "Y" or "SP500" in (row.get("index") or ""):
                universe[row["ticker"]] = {
                    "name": row.get("name", row["ticker"]),
                    "sector": row.get("sector", ""),
                    "dr_symbols": (row.get("dr_symbols") or "").strip(),
                }
    return universe


def run_scan(config, lookback_days=None, client=None, secondary_cal_fn=None):
    """สแกนหุ้นออกงบใน universe ให้คะแนน 5-factor + levels

    secondary_cal_fn(from_date, to_date) → ปฏิทินแหล่งที่สอง (รูปเดียวกับ FMP)
    ไว้เติมหุ้นที่แผนฟรี FMP กรองออกจากปฏิทินเงียบ ๆ — แหล่งเสริมล้มได้โดยไม่พังสแกน

    คืน dict: from_date, to_date, universe_size, reported_symbols,
    candidates (เกรด A/B เรียง score มาก→น้อย), skipped_counts, api_stats
    """
    lookback = lookback_days or config.lookback_days
    client = client or FMPClient(api_key=config.fmp_api_key,
                                 max_api_calls=config.max_api_calls)
    universe = load_universe()

    today = datetime.now()
    from_date = (today - timedelta(days=lookback)).strftime("%Y-%m-%d")
    to_date = today.strftime("%Y-%m-%d")

    calendar = list(client.get_earnings_calendar(from_date, to_date) or [])
    if secondary_cal_fn:
        try:
            # ต่อท้าย: FMP มาก่อนจึงชนะเรื่อง date/timing, ตัวซ้ำโดน seen กรอง
            calendar += secondary_cal_fn(from_date, to_date) or []
        except Exception:
            pass
    seen, reported = set(), []
    for e in calendar:
        sym = e.get("symbol")
        if sym and sym in universe and sym not in seen:
            seen.add(sym)
            reported.append({"symbol": sym,
                             "date": e.get("date"),
                             "timing": normalize_timing(e.get("time"))})

    candidates, skipped, pending = [], {"C": 0, "D": 0}, []
    for item in reported:
        sym = item["symbol"]
        client.saw_402 = False  # ธงต่อ symbol — ดู lookup.lookup_symbol
        try:
            prices = client.get_historical_prices(sym, days=250)
        except ApiCallBudgetExceeded:
            break
        if not prices or len(prices) < 70:
            reason = ("not_in_plan" if getattr(client, "saw_402", False)
                      else "no_data")
            pending.append({**item, "reason": reason})
            continue
        analysis = analyze_stock(prices, item["date"], item["timing"])
        levels = compute_levels(prices, item["date"], item["timing"])
        if levels is None:
            # วันตอบรับงบยังไม่มีในข้อมูล (งบวันนี้/เมื่อคืน) — รอสแกนรอบถัดไป
            pending.append({**item, "reason": "waiting"})
            continue
        grade = analysis["composite"]["grade"]
        if grade in ("C", "D"):
            skipped[grade] += 1
            continue
        candidates.append({
            "symbol": sym,
            "name": universe[sym]["name"],
            "dr_symbols": universe[sym]["dr_symbols"],
            "sector": universe[sym]["sector"],
            "earnings_date": item["date"],
            "timing": item["timing"],
            "gap_pct": analysis["gap"]["gap_pct"],
            "score": analysis["composite"]["composite_score"],
            "grade": grade,
            "levels": levels,
        })

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return {
        "from_date": from_date,
        "to_date": to_date,
        "universe_size": len(universe),
        "reported_symbols": [r["symbol"] for r in reported],
        "candidates": candidates,
        "skipped_counts": skipped,
        "pending": pending,
        "api_stats": client.get_api_stats(),
    }


def save_reports(scan, messages, out_dir=REPORTS_DIR):
    """บันทึกผลสแกนเป็น JSON + Markdown ใน reports/"""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    json_path = out_dir / f"scan_{stamp}.json"
    md_path = out_dir / f"scan_{stamp}.md"
    json_path.write_text(json.dumps(scan, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    md_path.write_text("\n\n---\n\n".join(messages), encoding="utf-8")
    return json_path, md_path
