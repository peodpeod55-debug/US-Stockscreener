"""ปุ่ม inline ติดตาม/เลิกติดตาม: builders, parse callback data, แปลง markup หลังกด"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.buttons import (
    build_unwatch_markup,
    build_watch_all_markup,
    build_watch_markup,
    drop_button,
    mark_pressed,
    parse_callback,
)


def _flat(markup):
    """[(label, data), ...] เรียงตามแถว — ไว้ assert ง่ายๆ"""
    return [(b.text, b.callback_data)
            for row in markup.inline_keyboard for b in row]


# ── build_watch_markup ──────────────────────────────────────────


def test_watch_markup_new_symbol():
    m = build_watch_markup("NVDA")
    assert _flat(m) == [("➕ ติดตาม NVDA", "w:NVDA")]


def test_watch_markup_auto_symbol_offers_permanent():
    m = build_watch_markup("EL", in_auto=True)
    assert _flat(m) == [("📌 ติดตามถาวร EL", "w:EL")]


def test_watch_markup_manual_symbol_returns_none():
    assert build_watch_markup("NVDA", in_manual=True) is None


def test_watch_markup_with_all_row():
    m = build_watch_markup("AAPL", all_symbols=["NVDA", "TSLA", "AAPL"])
    assert _flat(m) == [("➕ ติดตาม AAPL", "w:AAPL"),
                        ("➕ ติดตามทั้ง 3 ตัว", "wa:NVDA,TSLA,AAPL")]


def test_watch_markup_manual_but_all_row_remains():
    m = build_watch_markup("AAPL", in_manual=True,
                           all_symbols=["NVDA", "AAPL"])
    assert _flat(m) == [("➕ ติดตามทั้ง 2 ตัว", "wa:NVDA,AAPL")]


# ── build_watch_all_markup ──────────────────────────────────────


def test_watch_all_markup_permanent_names_in_label():
    m = build_watch_all_markup(["EL", "TGT"], permanent=True)
    assert _flat(m) == [("📌 ติดตามถาวรทั้งหมด (EL, TGT)", "wa:EL,TGT")]


def test_watch_all_markup_single_symbol_returns_none():
    assert build_watch_all_markup(["EL"]) is None


def test_watch_all_markup_oversized_data_returns_none():
    # 12 ตัว ตัวละ 5 ตัวอักษร = data ~75 bytes เกินเพดาน 64 ของ Telegram
    syms = [f"AAAA{i}" for i in range(12)]
    assert build_watch_all_markup(syms) is None


# ── build_unwatch_markup ────────────────────────────────────────


def test_unwatch_markup_rows_of_three():
    m = build_unwatch_markup(["A", "B", "C", "D"])
    rows = m.inline_keyboard
    assert [len(r) for r in rows] == [3, 1]
    assert _flat(m) == [("🗑 A", "u:A"), ("🗑 B", "u:B"),
                        ("🗑 C", "u:C"), ("🗑 D", "u:D")]


def test_unwatch_markup_empty_returns_none():
    assert build_unwatch_markup([]) is None


# ── parse_callback ──────────────────────────────────────────────


def test_parse_watch_single():
    assert parse_callback("w:NVDA") == ("watch", ["NVDA"])


def test_parse_watch_all():
    assert parse_callback("wa:EL,TGT") == ("watch", ["EL", "TGT"])


def test_parse_unwatch():
    assert parse_callback("u:BRK.B") == ("unwatch", ["BRK.B"])


def test_parse_rejects_bad_ticker_and_noop():
    assert parse_callback("w:nvda!") is None
    assert parse_callback("wa:EL,") is None
    assert parse_callback("-") is None
    assert parse_callback("") is None


# ── แปลง markup หลังกด ──────────────────────────────────────────


def _markup(*rows):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t, callback_data=d) for t, d in row]
        for row in rows])


def test_mark_pressed_replaces_label_and_disarms():
    m = _markup([("➕ ติดตาม EL", "w:EL")], [("➕ ติดตามทั้ง 2 ตัว", "wa:EL,TGT")])
    out = mark_pressed(m, "w:EL")
    assert _flat(out) == [("✓ ติดตามแล้ว", "-"),
                          ("➕ ติดตามทั้ง 2 ตัว", "wa:EL,TGT")]


def test_drop_button_removes_and_prunes_empty_row():
    m = _markup([("🗑 A", "u:A"), ("🗑 B", "u:B")], [("🗑 C", "u:C")])
    out = drop_button(m, "u:C")
    assert _flat(out) == [("🗑 A", "u:A"), ("🗑 B", "u:B")]


def test_drop_last_button_returns_none():
    m = _markup([("🗑 A", "u:A")])
    assert drop_button(m, "u:A") is None
