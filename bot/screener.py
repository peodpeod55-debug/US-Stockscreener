"""Core scan: universe → earnings calendar → 5-factor score → levels"""
import csv
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ETA_DIR = Path(__file__).resolve().parent / "vendor" / "eta"
if str(ETA_DIR) not in sys.path:
    sys.path.insert(0, str(ETA_DIR))

from analyze_earnings_trades import analyze_stock, normalize_timing  # noqa: E402
from fmp_client import ApiCallBudgetExceeded, FMPClient  # noqa: E402

from bot import earnings_store, fetch_cache, pending as pending_store  # noqa: E402
from bot.levels import compute_levels, infer_bmo, positive_reaction  # noqa: E402
from bot.prices import get_prices, prefetch  # noqa: E402
from bot.set_score import is_set_hit, set_score  # noqa: E402

UNIVERSE_CSV = PROJECT_ROOT / "us_stock_list.csv"
REPORTS_DIR = PROJECT_ROOT / "reports"

logger = logging.getLogger("bot.screener")


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


def run_scan(config, lookback_days=None, client=None, secondary_cal_fn=None,
             get_prices_fn=None, today=None, pending_path=None):
    """สแกนหุ้นออกงบใน universe ให้คะแนน 5-factor + levels

    secondary_cal_fn(from_date, to_date) → ปฏิทินแหล่งที่สอง (รูปเดียวกับ FMP)
    ไว้เติมหุ้นที่แผนฟรี FMP กรองออกจากปฏิทินเงียบ ๆ — แหล่งเสริมล้มได้โดยไม่พังสแกน
    get_prices_fn(symbol, days) → แท่งราคา (ค่าเริ่มต้น bot.prices.get_prices: Yahoo → FMP)
    today: datetime อ้างอิง (เทส) · pending_path: ไฟล์รายการรอตอบรับข้ามรอบ (bot/pending.py)

    เกณฑ์ candidate: วันตอบรับงบต้องปิดบวก (positive_reaction) แล้วค่อยให้เกรด A/B —
    5-factor ให้คะแนน |gap| ไม่สนทิศทาง ตัวที่ปิดลบนับใน skipped_counts["down"]

    คืน dict: from_date, to_date, universe_size, reported_symbols,
    candidates (เกรด A/B เรียง score มาก→น้อย), skipped_counts, pending, api_stats
    """
    lookback = lookback_days or config.lookback_days
    client = client or FMPClient(api_key=config.fmp_api_key,
                                 max_api_calls=config.max_api_calls)
    universe = load_universe()

    today = today or datetime.now()
    from_date = (today - timedelta(days=lookback)).strftime("%Y-%m-%d")
    to_date = today.strftime("%Y-%m-%d")

    calendar = list(client.get_earnings_calendar(from_date, to_date) or [])
    if secondary_cal_fn:
        try:
            # ต่อท้าย: FMP มาก่อนจึงชนะเรื่อง date/timing, ตัวซ้ำโดน seen กรอง
            calendar += secondary_cal_fn(from_date, to_date) or []
        except Exception:
            pass
    # ทุกแถว (รวมนอก universe) ลงคลังวันงบ — lookup/เตือนวันงบใช้ต่อโดยไม่ยิง FMP รายตัว
    earnings_store.merge(calendar, source="scan", today=today.date())
    # FMP stable ไม่มี field time เลย — เก็บ timing จากทุก entry (รวมตัวที่แพ้
    # dedup เช่น NASDAQ) ไว้เติมให้ตัวที่ยัง unknown; join แบบ normalize จุด/ทับ
    _canon = earnings_store.canon

    seen, reported, timing_map = set(), [], {}
    for e in calendar:
        sym = e.get("symbol")
        if not sym:
            continue
        t = normalize_timing(e.get("time"))
        if t != "unknown":
            timing_map.setdefault(_canon(sym), t)
        if sym in universe and sym not in seen:
            seen.add(sym)
            reported.append({"symbol": sym, "date": e.get("date"), "timing": t})
    # entry ที่รอตอบรับจากรอบก่อนแต่หลุดหน้าต่างปฏิทินไปแล้ว (งบ AMC ศุกร์ / ก่อนวันหยุด US)
    reported += pending_store.carry_forward(
        reported, pending_store.load_pending(pending_path), today.date())
    for item in reported:
        if item["timing"] == "unknown":
            item["timing"] = timing_map.get(_canon(item["symbol"]), "unknown")

    # อุ่น cache ทุกตัวพร้อมกันก่อน (Yahoo หลัก) — ลูปข้างล่างอ่านจาก cache เป็นหลัก
    fetch = get_prices_fn or (lambda s, d: get_prices(s, d, client=client))
    prefetch([i["symbol"] for i in reported], 250, get_fn=fetch)
    candidates, skipped, pending, rows = [], {"C": 0, "D": 0, "down": 0}, [], []
    for item in reported:
        sym = item["symbol"]
        prices = fetch_cache.get(("prices", sym, 250))
        if prices is None:
            try:
                prices = fetch(sym, 250)
            except ApiCallBudgetExceeded:
                break
            except Exception:
                logger.warning("prices %s failed", sym, exc_info=True)
                prices = None
            fetch_cache.put(("prices", sym, 250), prices)
        if not prices or len(prices) < 70:
            # ไม่มีแหล่งไหนให้ราคา (Yahoo สะดุด/FMP 402) → จำไว้ลองใหม่รอบถัดไป
            pending.append({**item, "reason": "no_data"})
            continue
        timing = item["timing"]
        if timing == "unknown" and infer_bmo(prices, item["date"]):
            timing = "bmo"
            item["timing"] = "bmo*"  # อนุมานจากแท่งราคา ไม่ใช่ปฏิทิน — ไว้ audit
        levels = compute_levels(prices, item["date"], timing)
        if levels is None:
            # วันตอบรับงบยังไม่มีในข้อมูล (งบวันนี้/เมื่อคืน) — รอสแกนรอบถัดไป
            pending.append({**item, "reason": "waiting"})
            continue
        # แถวต่อทุกตัวที่มีแท่ง D0 (แจ้ง + ตกเกณฑ์) — ฐานของ scan_log.csv / /scanlog · เกรดคิดให้ทุกแถวแม้ปิดลบ
        # เกณฑ์ SET (bot/set_score, port จาก HK 28 ส.ค. 2026): ด่านเข้า ปิด D0 ≥2% & vol ≥1.5× · set_pts 0-15 ณ วันสแกน — ไม่กระทบตัวกรองเดิม
        analysis = analyze_stock(prices, item["date"], timing)
        grade = analysis["composite"]["grade"]
        ss = set_score(prices, levels["reaction_date"])
        row = {
            "symbol": sym, "name": universe[sym]["name"], "earnings_date": item["date"], "timing": item["timing"],
            "d0": levels["reaction_date"], "ret_d0_pct": levels.get("reaction_pct"), "vol_ratio": levels.get("vol_ratio"),
            "score": analysis["composite"]["composite_score"], "grade": grade, "skip_reason": None, "signal_type": None,
            "set_hit": is_set_hit(levels.get("reaction_pct"), levels.get("vol_ratio")),
            "set_pts": ss["pts"] if ss else None,
        }
        rows.append(row)
        if not positive_reaction(levels):
            # วันตอบรับปิดลบ = ไม่ใช่ "อาการหลังงบดี" ไม่ว่าคะแนนเท่าไร — ตัดก่อนให้เกรด
            skipped["down"] += 1
            row["skip_reason"] = "down"
            continue
        if grade in ("C", "D"):
            skipped[grade] += 1
            row["skip_reason"] = grade
            continue
        row["signal_type"] = "composite"
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

    # จำตัวที่ยังรอ (waiting/no_data) ไว้เติมรอบหน้าแม้หลุดหน้าต่างปฏิทิน
    pending_store.save_pending(pending, pending_path)
    candidates.sort(key=lambda c: c["score"], reverse=True)
    return {
        "from_date": from_date,
        "to_date": to_date,
        "universe_size": len(universe),
        "reported_symbols": [r["symbol"] for r in reported],
        "candidates": candidates,
        "skipped_counts": skipped,
        "pending": pending,
        "rows": rows,
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
