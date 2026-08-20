"""Watchlist: จำหุ้นที่ผู้ใช้ติดตามลงไฟล์ JSON (ใช้กับเตือนวันงบ)

คำสั่งข้อความไทย: "ติดตาม" ดูรายชื่อ · "ติดตาม NVDA" เพิ่ม · "เลิกติดตาม NVDA" ลบ
"""
import json

from bot.config import PROJECT_ROOT
from bot.lookup import parse_tickers

WATCHLIST_PATH = PROJECT_ROOT / "watchlist.json"
WATCHLIST_MAX = 20              # คุมงบ API ของ job เตือนวันงบ (1 call/ตัว/วัน)

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
    path.write_text(json.dumps(symbols, ensure_ascii=False, indent=2),
                    encoding="utf-8")


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
