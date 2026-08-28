"""คลังวันงบสะสม — earnings_calendar.json (gitignored, สร้างใหม่ได้จากปฏิทิน NASDAQ/FMP)

FMP แผนฟรี: ปฏิทินรวม (1 call) ใช้ได้ แต่ stable/earnings?symbol= รายตัวตอบ 402 กับหุ้น
เกือบทุกตัว → เตือนวันงบ / น่าสนใจ "งบใกล้" / next_earnings ใช้ไม่ได้ แม้บอทเห็นวันงบ
ตัวนั้นในปฏิทินรวมมาแล้ว · ทางแก้: ทุกแถวปฏิทินที่บอทดึงอยู่แล้ว (สแกน, "งบ", job เช้า,
รายสัปดาห์, Finnhub ถ้ามี key) merge ลงคลังต่อ symbol แล้วอ่านจากคลังก่อน — FMP รายตัว
เหลือเป็นสำรองเฉพาะตอนคลัง+signals.json ว่าง

รูปไฟล์: {"CRM": [{"date": "2026-08-26", "time": "amc"|null, "source": "nasdaq",
"seen": "2026-08-28"}]} คีย์ = canon(symbol) (BRK/B, BRK-B → BRK.B ตาม universe)
กฎ merge: วันงบตัวเดียวกันห่างกัน ≤ SAME_EVENT_DAYS = งบไตรมาสเดียวกัน (ประมาณการ → ยืนยัน
วันเลื่อนได้) รายการใหม่ทับวันที่ แต่ timing ที่รู้แล้ว (bmo/amc) ไม่ถูกทับด้วย unknown
ตัดรายการเก่ากว่า/ไกลกว่า KEEP_DAYS ทุกครั้งที่เขียน · เขียนแบบ atomic

CLI: python -m bot.earnings_store backfill 90   (NASDAQ ย้อน 90 วัน — seed ครั้งแรก)
     python -m bot.earnings_store ahead 35      (NASDAQ ล่วงหน้า 35 วัน)
"""
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

ETA_DIR = Path(__file__).resolve().parent / "vendor" / "eta"
if str(ETA_DIR) not in sys.path:
    sys.path.insert(0, str(ETA_DIR))

from analyze_earnings_trades import normalize_timing  # noqa: E402

from bot.config import PROJECT_ROOT  # noqa: E402
from bot.fileio import write_json_atomic  # noqa: E402
from bot.finnhub_cal import fetch_finnhub_earnings  # noqa: E402
from bot.nasdaq_cal import fetch_nasdaq_earnings  # noqa: E402
from bot.signals import earnings_from_signals  # noqa: E402

STORE_PATH = PROJECT_ROOT / "earnings_calendar.json"
SAME_EVENT_DAYS = 21        # วันงบตัวเดียวกันห่าง ≤ นี้ = งบไตรมาสเดียวกัน (วันเลื่อน)
KEEP_DAYS = 120             # เก็บย้อน/ล่วงหน้าเท่านี้ (lookup ใช้งบ ≤60 วัน · เตือนใช้ ≤1 วัน)

logger = logging.getLogger("bot.earnings_store")


def canon(symbol):
    """สัญลักษณ์แบบเดียวกับ universe: BRK/B (NASDAQ), BRK-B (FMP/Yahoo) → BRK.B"""
    return (symbol or "").strip().upper().replace("/", ".").replace("-", ".")


def _timing(value):
    t = normalize_timing(value)
    return None if t == "unknown" else t


def _valid_date(s):
    try:
        date.fromisoformat(s)
        return True
    except (TypeError, ValueError):
        return False


def load_store(path=None):
    """คลังทั้งหมด (ไฟล์หาย/พัง → ว่าง)"""
    path = path or STORE_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _days_apart(a, b):
    return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)


def _absorb(entries, date_str, time, source, seen, replace_date=True):
    """รวมงบหนึ่งรายการเข้า list ของ symbol เดียว — คืน True ถ้ามีอะไรเปลี่ยน

    replace_date=False: ใช้ตอนรวมแหล่งที่เก่ากว่า (signals.json) — เติมแค่ timing ไม่ย้ายวัน
    """
    for e in entries:
        if _days_apart(e["date"], date_str) > SAME_EVENT_DAYS:
            continue
        changed = False
        if replace_date and e["date"] != date_str:
            e["date"] = date_str
            changed = True
        if time and e.get("time") != time:
            e["time"] = time
            changed = True
        if changed:
            e["source"], e["seen"] = source, seen
        return changed
    entries.append({"date": date_str, "time": time, "source": source, "seen": seen})
    return True


def _prune(store, today):
    lo = (today - timedelta(days=KEEP_DAYS)).isoformat()
    hi = (today + timedelta(days=KEEP_DAYS)).isoformat()
    removed = 0
    for sym in list(store):
        kept = [e for e in store[sym] if lo <= (e.get("date") or "") <= hi]
        removed += len(store[sym]) - len(kept)
        if kept:
            store[sym] = sorted(kept, key=lambda e: e["date"])
        else:
            del store[sym]
    return removed


def merge(rows, source, today=None, path=None):
    """รวมแถวปฏิทิน (รูป FMP/NASDAQ: symbol/date/time) ลงคลัง — คืนจำนวนรายการที่เปลี่ยน"""
    path = path or STORE_PATH
    today = today or date.today()
    seen = today.isoformat()
    store = load_store(path)
    changed = 0
    for r in rows or []:
        sym, d = canon(r.get("symbol")), r.get("date")
        if not sym or not _valid_date(d):
            continue
        if _absorb(store.setdefault(sym, []), d, _timing(r.get("time")), source, seen):
            changed += 1
    removed = _prune(store, today)
    if changed or removed:
        write_json_atomic(path, store)
    return changed


def earnings_for(symbol, path=None):
    """วันงบของหุ้นในคลัง รูปเดียวกับ FMP raw [{"date", "time"}] เรียงวันเก่า → ใหม่"""
    rows = load_store(path).get(canon(symbol)) or []
    return [{"date": e["date"], "time": e.get("time")}
            for e in sorted(rows, key=lambda e: e["date"])]


def known_earnings(symbol, path=None, signals_fn=earnings_from_signals):
    """วันงบที่บอทรู้เองโดยไม่ยิง API: คลัง ∪ signals.json (งบเดียวกัน → วันจากคลัง, timing เติมกัน)"""
    rows = [dict(r) for r in earnings_for(symbol, path)]
    for s in signals_fn(symbol) or []:
        d = s.get("date")
        if _valid_date(d):
            _absorb(rows, d, _timing(s.get("time")), source=None, seen=None,
                    replace_date=False)
    return [{"date": r["date"], "time": r.get("time")}
            for r in sorted(rows, key=lambda r: r["date"])]


def refresh(fetchers, from_date, to_date, today=None, path=None):
    """ดึงปฏิทินช่วง from..to จากทุกแหล่ง [(ชื่อ, fn(from, to))] แล้ว merge

    แหล่งล้มข้าม (log) ไม่พังแหล่งอื่น · คืน {ชื่อ: จำนวนแถวที่ได้ | None ถ้าล้ม}
    """
    result = {}
    for name, fn in fetchers:
        try:
            rows = fn(from_date, to_date) or []
        except Exception:
            logger.warning("calendar source %s failed", name, exc_info=True)
            result[name] = None
            continue
        merge(rows, source=name, today=today, path=path)
        result[name] = len(rows)
    return result


def default_sources(client, finnhub_key="", nasdaq_fn=None, finnhub_fn=None):
    """แหล่งปฏิทินสำหรับ refresh: NASDAQ (ฟรี ไม่ต้อง key) · FMP รวม (ถ้ามี client)
    · Finnhub (ถ้าตั้ง FINNHUB_API_KEY) — คืน [(ชื่อ, fn(from, to))]"""
    nasdaq_fn = nasdaq_fn or fetch_nasdaq_earnings
    finnhub_fn = finnhub_fn or fetch_finnhub_earnings
    sources = [("nasdaq", nasdaq_fn)]
    if client is not None:
        sources.append(("fmp", client.get_earnings_calendar))
    if finnhub_key:
        sources.append(("finnhub",
                        lambda from_date, to_date: finnhub_fn(from_date, to_date, finnhub_key)))
    return sources


def backfill(days, fetch_fn=None, today=None, path=None, source="nasdaq"):
    """seed คลังด้วยปฏิทินย้อนหลัง days วัน (ค่าเริ่มต้น NASDAQ — ฟรี ไม่ต้องใช้ key)"""
    today = today or date.today()
    fetch_fn = fetch_fn or fetch_nasdaq_earnings
    rows = fetch_fn((today - timedelta(days=days)).isoformat(), today.isoformat()) or []
    return merge(rows, source=source, today=today, path=path)


def _main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    n = int(argv[2]) if len(argv) > 2 else 90
    today = date.today()
    if cmd == "backfill":
        print("merged", backfill(n, today=today), "entries from NASDAQ (past", n, "days)")
    elif cmd == "ahead":
        end = (today + timedelta(days=n)).isoformat()
        print(refresh([("nasdaq", fetch_nasdaq_earnings)], today.isoformat(), end,
                      today=today))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
