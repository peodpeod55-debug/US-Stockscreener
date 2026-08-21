"""ปุ่ม inline ติดตาม/เลิกติดตาม — builders, parse callback data, แปลง markup หลังกด

callback data (จำกัด 64 bytes ต่อปุ่ม): `w:<SYM>` เพิ่มตัวเดียว ·
`wa:<SYM,SYM,...>` เพิ่มทั้งชุด · `u:<SYM>` เอาออก · `-` = ปุ่มปลดชนวนแล้ว (noop)
"""
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")   # รูปเดียวกับ lookup
_DATA_MAX = 64                                          # เพดานของ Telegram
_UNWATCH_PER_ROW = 3
PRESSED_LABEL = "✓ ติดตามแล้ว"


def _all_button(symbols):
    """ปุ่มแถว "ติดตามทั้งชุด" — None ถ้าชุดเล็กไป/ data ยาวเกินเพดาน"""
    if len(symbols) < 2:
        return None
    data = "wa:" + ",".join(symbols)
    if len(data.encode()) > _DATA_MAX:
        return None
    return InlineKeyboardButton(f"➕ ติดตามทั้ง {len(symbols)} ตัว",
                                callback_data=data)


def build_watch_markup(symbol, in_manual=False, in_auto=False, all_symbols=None):
    """ปุ่มติดตามใต้ข้อความรายตัว (lookup/กราฟ) — None ถ้าไม่มีปุ่มให้แสดง

    manual แล้ว → ไม่มีปุ่มรายตัว · auto → เสนอเลื่อนขั้นเป็นติดตามถาวร
    all_symbols (≥2 ตัว) → เพิ่มแถว "ติดตามทั้ง N ตัว" ให้กดทีเดียวทั้งชุด
    """
    rows = []
    if not in_manual:
        label = (f"📌 ติดตามถาวร {symbol}" if in_auto
                 else f"➕ ติดตาม {symbol}")
        rows.append([InlineKeyboardButton(label, callback_data=f"w:{symbol}")])
    all_btn = _all_button(all_symbols or [])
    if all_btn:
        rows.append([all_btn])
    return InlineKeyboardMarkup(rows) if rows else None


def build_watch_all_markup(symbols, permanent=False):
    """ปุ่มเดี่ยว "ติดตามทั้งชุด" ใต้ข้อความสแกน — None ถ้า <2 ตัว/ data ยาวเกิน"""
    btn = _all_button(symbols)
    if btn is None:
        return None
    if permanent:
        btn = InlineKeyboardButton(
            f"📌 ติดตามถาวรทั้งหมด ({', '.join(symbols)})",
            callback_data=btn.callback_data)
    return InlineKeyboardMarkup([[btn]])


def build_unwatch_markup(symbols):
    """ปุ่ม 🗑 รายตัวใต้หน้ารายชื่อติดตาม — กดต่อเนื่องได้จนกว่าจะหมด"""
    buttons = [InlineKeyboardButton(f"🗑 {s}", callback_data=f"u:{s}")
               for s in symbols]
    rows = [buttons[i:i + _UNWATCH_PER_ROW]
            for i in range(0, len(buttons), _UNWATCH_PER_ROW)]
    return InlineKeyboardMarkup(rows) if rows else None


def parse_callback(data):
    """แปลง callback data → ("watch"|"unwatch", [symbols]) หรือ None ถ้าไม่รู้จัก/ปลอม"""
    if data.startswith("w:"):
        action, syms = "watch", [data[2:]]
    elif data.startswith("wa:"):
        action, syms = "watch", data[3:].split(",")
    elif data.startswith("u:"):
        action, syms = "unwatch", [data[2:]]
    else:
        return None
    if not all(_TICKER_RE.match(s) for s in syms):
        return None
    return action, syms


def _rebuild(markup, transform):
    rows = [[b for b in (transform(b) for b in row) if b is not None]
            for row in markup.inline_keyboard]
    rows = [r for r in rows if r]
    return InlineKeyboardMarkup(rows) if rows else None


def mark_pressed(markup, data):
    """แก้ปุ่มที่เพิ่งกดเป็น ✓ (data `-` = กดซ้ำไม่ทำอะไร) แถวอื่นคงเดิม"""
    return _rebuild(markup, lambda b: InlineKeyboardButton(
        PRESSED_LABEL, callback_data="-") if b.callback_data == data else b)


def drop_button(markup, data):
    """ตัดปุ่มที่เพิ่งกดออก (แถวว่างถูกลบ) — None ถ้าไม่เหลือปุ่มเลย"""
    return _rebuild(markup, lambda b: None if b.callback_data == data else b)
