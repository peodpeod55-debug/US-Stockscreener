"""Watchlist: จำหุ้นที่ผู้ใช้ติดตามลงไฟล์ JSON (ใช้กับเตือนวันงบ + เตือนทะลุแนว)

คำสั่งข้อความไทย: "ติดตาม" ดูรายชื่อ · "ติดตาม NVDA" เพิ่ม · "เลิกติดตาม NVDA" ลบ
auto-watch: หุ้นเกรด A/B จากสแกนเข้าอัตโนมัติ (แยกไฟล์, หมดอายุ 30 วัน)
"""
import json
from datetime import date, timedelta

from bot.config import PROJECT_ROOT
from bot.fileio import write_json_atomic
from bot.lookup import parse_tickers

WATCHLIST_PATH = PROJECT_ROOT / "watchlist.json"
WATCHLIST_MAX = 20              # คุมงบ API ของ job เตือนวันงบ (1 call/ตัว/วัน)

AUTO_WATCH_PATH = PROJECT_ROOT / "auto_watch.json"   # {symbol: วันที่เพิ่ม ISO}
AUTO_WATCH_DAYS = 30            # หุ้น A/B ติดตามอัตโนมัตินานเท่านี้แล้วหลุดเอง
AUTO_WATCH_MAX = 20             # เกิน → ตัวเก่าสุดหลุด (คุมงบ API เหมือน manual)

_CMD_REMOVE = "เลิกติดตาม"
_CMD_ADD = "ติดตาม"             # ไม่มี ticker ต่อท้าย = ขอดูรายชื่อ


def parse_watch_command(text):
    """แปลงข้อความเป็นคำสั่ง watchlist: (action, tickers) หรือ None ถ้าไม่ใช่

    action: "show" | "add" | "remove" — รองรับพิมพ์ติดกันแบบไทย เช่น "ติดตามNVDA"
    """
    text = (text or "").strip()
    if text.startswith(_CMD_REMOVE):
        return ("remove", parse_tickers(text[len(_CMD_REMOVE):]))
    if text.startswith(_CMD_ADD):
        tickers = parse_tickers(text[len(_CMD_ADD):])
        return ("add", tickers) if tickers else ("show", [])
    return None


def load_watchlist(path=WATCHLIST_PATH):
    """อ่านรายชื่อหุ้นจากไฟล์ (ไฟล์หาย/พัง → ลิสต์ว่าง)"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def save_watchlist(symbols, path=WATCHLIST_PATH):
    write_json_atomic(path, symbols)


def add_symbols(symbols, path=WATCHLIST_PATH):
    """เพิ่มหุ้นเข้า watchlist — คืน dict: added / already / full"""
    current = load_watchlist(path)
    result = {"added": [], "already": [], "full": []}
    for sym in symbols:
        if sym in current:
            result["already"].append(sym)
        elif len(current) >= WATCHLIST_MAX:
            result["full"].append(sym)
        else:
            current.append(sym)
            result["added"].append(sym)
    if result["added"]:
        save_watchlist(current, path)
    return result


def remove_symbols(symbols, path=WATCHLIST_PATH):
    """ลบหุ้นออกจาก watchlist — คืน dict: removed / missing"""
    current = load_watchlist(path)
    result = {"removed": [], "missing": []}
    for sym in symbols:
        if sym in current:
            current.remove(sym)
            result["removed"].append(sym)
        else:
            result["missing"].append(sym)
    if result["removed"]:
        save_watchlist(current, path)
    return result


# ── auto-watch: หุ้น A/B จากสแกน ─────────────────────────────────

def load_auto_watch(path=AUTO_WATCH_PATH):
    """อ่าน auto-watch ทั้งไฟล์ {symbol: วันที่เพิ่ม} (ไฟล์หาย/พัง → ว่าง)"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_auto_watch(data, path=AUTO_WATCH_PATH):
    write_json_atomic(path, data)


def active_auto(path=AUTO_WATCH_PATH, today=None):
    """เฉพาะตัวที่ยังไม่หมดอายุ (เพิ่มมาไม่เกิน AUTO_WATCH_DAYS วัน)"""
    today = today or date.today()
    cutoff = (today - timedelta(days=AUTO_WATCH_DAYS)).isoformat()
    return {sym: d for sym, d in load_auto_watch(path).items() if d >= cutoff}


def auto_add(symbols, path=AUTO_WATCH_PATH, manual_path=WATCHLIST_PATH,
             today=None):
    """เพิ่มหุ้น A/B จากสแกน — คืนเฉพาะตัวใหม่จริง (ไว้แจ้งผู้ใช้)

    ตัวที่ user ติดตามเองอยู่แล้วข้าม · ตัวที่อยู่ใน auto แล้วต่ออายุ (นับวันใหม่)
    ล้างตัวหมดอายุทิ้งไปด้วย และถ้าเกินเพดานตัวเก่าสุดหลุด
    """
    today = today or date.today()
    manual = set(load_watchlist(manual_path))
    data = active_auto(path, today)
    added = []
    for sym in symbols:
        if sym in manual:
            continue
        if sym not in data:
            added.append(sym)
        data[sym] = today.isoformat()
    while len(data) > AUTO_WATCH_MAX:
        oldest = min(data, key=lambda s: data[s])
        del data[oldest]
    save_auto_watch(data, path)
    return added


def auto_remove(symbols, path=AUTO_WATCH_PATH):
    """เอาออกจาก auto-watch (ตอน user สั่งเลิกติดตาม) — คืนตัวที่ลบจริง"""
    data = load_auto_watch(path)
    removed = [sym for sym in symbols if sym in data]
    for sym in removed:
        del data[sym]
    if removed:
        save_auto_watch(data, path)
    return removed


def all_watched(manual_path=WATCHLIST_PATH, auto_path=AUTO_WATCH_PATH,
                today=None):
    """รายชื่อรวมสำหรับ job เช้า: manual ก่อน ตามด้วย auto ที่ยังไม่หมดอายุ"""
    manual = load_watchlist(manual_path)
    return manual + [sym for sym in active_auto(auto_path, today)
                     if sym not in manual]
