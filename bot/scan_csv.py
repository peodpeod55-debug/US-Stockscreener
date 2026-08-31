"""scan_log.csv — ไฟล์ให้ gem-lab อ่านต่อตลาด: schema เดียวกับ Set screnner (`scanner._append_log`) + คอลัมน์ `grade` ท้ายสุด
(port จาก HK Stock Screener bot/scan_csv.py 28 ส.ค. 2026 — ต่างแค่ ticker US ไม่มีนามสกุล: "NVDA")

gem-lab (`lib/scanlog.mjs`) อ่าน CSV ตามชื่อคอลัมน์ `ticker,score,scan_date` คัด score ≥ 11 ในกรอบ 30 วัน เอาคะแนนสูงสุดต่อชื่อ —
ไฟล์นี้จึงต้อง "สะสม" หนึ่งแถวต่อ (scan_date, ticker) เหมือนไทย (ไทย append ซ้ำแล้ว dedup ตอนอ่าน — ที่นี่กันตั้งแต่เขียน: รอบหลังทับรอบก่อนของวันเดียวกัน)
score = คะแนน SET 0-15 (bot.set_score คิดสด ณ วันเขียน) · grade = A–D ของ composite 5-factor (เพิ่มท้ายสุด ไม่กระทบตัวอ่านของไทย)
เขียนจาก /scanlog และสแกน 08:30 (bot.main — bars จาก fetch_cache ที่ run_scan เพิ่งดึง ไม่ยิงเน็ตซ้ำ) · utf-8-sig + CRLF เปิด Excel ได้ ·
เขียนไม่ได้ (ไฟล์ถูก Excel ล็อก) → log เตือน ไม่ล้มสแกน (พฤติกรรมเดียวกับไทย) · gitignore เหมือน signals.json
"""
import csv
import logging
import os

from bot.config import PROJECT_ROOT
from bot.set_score import set_score

logger = logging.getLogger("bot.scan_csv")

SCAN_CSV_PATH = PROJECT_ROOT / "scan_log.csv"
CSV_COLUMNS = [
    "scan_date", "ticker", "earn_date", "reaction_pct", "reaction_vol_ratio", "since_earn_pct", "price",
    "broke_5d_high", "broke_3m_high", "days_since_new_high", "pre_earn_low", "above_pre_low", "score",   # = ไทย
    "grade",                                                                                              # เพิ่ม
]


def csv_ticker(symbol):
    """US ไม่มีนามสกุล — gem-lab รู้ตลาดจาก config ของไฟล์ (ไม่ใช่จาก ticker)"""
    return str(symbol).upper()


def pick_rows(rows):
    """แถวที่ลง CSV: ผ่านด่าน SET (set_hit) *หรือ* เข้าเกณฑ์เดิม (skip_reason None) — ตัว A/B ที่ SET ไม่ผ่านก็ลง เพราะมี grade"""
    return [r for r in rows if r.get("set_hit") or not r.get("skip_reason")]


def live_scores(rows, get_bars):
    """{symbol: set_score dict | None} — get_bars(symbol) → bars หรือ None (ผู้เรียกเลือกว่าดึงสดหรือจาก cache)"""
    out = {}
    for r in rows:
        bars = get_bars(r["symbol"])
        out[r["symbol"]] = set_score(bars, r["d0"]) if bars else None
    return out


def _f2(x):
    return "" if x is None else f"{x:.2f}"


def _flag(x):
    return str(int(bool(x)))


def csv_row(row, scored, scan_date):
    """แถว CSV จากแถวสแกน + คะแนนสด (None = ดึงราคาไม่ได้ → ใช้ set_pts ณ วันสแกน เว้นช่องที่คิดไม่ได้)"""
    s = scored or {}
    pts = s.get("pts") if scored else row.get("set_pts")
    day = scan_date.isoformat() if hasattr(scan_date, "isoformat") else str(scan_date)
    return [
        day, csv_ticker(row["symbol"]), row.get("earnings_date") or "",
        _f2(row.get("ret_d0_pct")), _f2(row.get("vol_ratio")), _f2(s.get("since_pct")), _f2(s.get("price")),
        _flag(s.get("broke_5d")), _flag(s.get("broke_3m")),
        "" if s.get("days_since_new_high") is None else str(s["days_since_new_high"]),
        _f2(s.get("pre_low")), _flag(s.get("above_pre_low")),
        "" if pts is None else str(pts), row.get("grade") or "",
    ]


def record_scan_csv(entries, scan_date, path=SCAN_CSV_PATH):
    """entries = [(แถวสแกน, set_score dict | None)] → เขียน/ทับแถวของ (scan_date, ticker) นั้น คืนจำนวนแถวที่เขียน (0 = ไม่มี/เขียนไม่ได้)"""
    if not entries:
        return 0
    new = [csv_row(r, s, scan_date) for r, s in entries]
    keys = {(x[0], x[1]) for x in new}
    try:
        existing = []
        if path.exists():
            with open(path, encoding="utf-8-sig", newline="") as f:
                reader = csv.reader(f)
                next(reader, None)                                      # หัวตารางเดิม — เขียนใหม่เป็น CSV_COLUMNS เสมอ
                existing = [x for x in reader if x and (x[0], x[1]) not in keys]
        tmp = path.with_name(path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8-sig", newline="") as f:      # newline="" → csv.writer ออก CRLF เดียว ไม่ซ้อน
            w = csv.writer(f)
            w.writerow(CSV_COLUMNS)
            w.writerows(existing)
            w.writerows(new)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except OSError as e:
        logger.warning("เขียน scan_log.csv ไม่ได้ (%s) — ข้าม ไม่ล้มสแกน", e)
        return 0
    return len(new)
