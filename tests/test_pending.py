"""pending.json: จำ entry ที่รอวันตอบรับข้ามรอบสแกน

บั๊กจริง: งบ AMC วันศุกร์ D0 = จันทร์ แท่งมาเช้าอังคาร แต่สแกนอังคาร (lookback 2 วัน)
ปฏิทินเริ่มอาทิตย์ → entry วันศุกร์หายไปเฉย ๆ ไม่เคยได้เกรด (เช่นกันกับงบก่อนวันหยุด US)
"""
from datetime import date

from bot import pending


def test_carry_forward_adds_missing_skips_present_and_expired():
    today = date(2026, 8, 25)
    reported = [{"symbol": "AAPL", "date": "2026-08-24", "timing": "amc"}]
    stored = [
        {"symbol": "AAPL", "date": "2026-08-21", "timing": "amc"},   # ปฏิทินรอบนี้มีแล้ว → ข้าม
        {"symbol": "WMT", "date": "2026-08-21", "timing": "bmo*"},   # เติม + timing ล้างเป็น unknown
        {"symbol": "OLD", "date": "2026-08-10", "timing": "amc"},    # เก่าเกิน 10 วัน
        {"symbol": "", "date": "2026-08-21"},                        # entry พัง
        {"symbol": "WMT", "date": "2026-08-21", "timing": "amc"},    # ซ้ำใน stored เอง
    ]
    assert pending.carry_forward(reported, stored, today) == [
        {"symbol": "WMT", "date": "2026-08-21", "timing": "unknown"}]


def test_carry_forward_keeps_explicit_timing():
    items = [{"symbol": "TGT", "date": "2026-08-21", "timing": "amc"}]
    assert pending.carry_forward([], items, date(2026, 8, 25)) == items


def test_save_keeps_only_carryable_reasons(tmp_path):
    p = tmp_path / "pending.json"
    scanned = [
        {"symbol": "A", "date": "2026-08-21", "timing": "amc", "reason": "waiting"},
        {"symbol": "B", "date": "2026-08-21", "timing": None, "reason": "no_data"},
        {"symbol": "C", "date": "2026-08-21", "timing": "bmo", "reason": "not_in_plan"},
    ]
    pending.save_pending(scanned, p)
    assert pending.load_pending(p) == [
        {"symbol": "A", "date": "2026-08-21", "timing": "amc"},
        {"symbol": "B", "date": "2026-08-21", "timing": "unknown"},
    ]


def test_save_empty_clears_previous(tmp_path):
    p = tmp_path / "pending.json"
    pending.save_pending([{"symbol": "A", "date": "2026-08-21",
                           "reason": "waiting"}], p)
    pending.save_pending([], p)
    assert pending.load_pending(p) == []


def test_load_missing_or_broken_file(tmp_path):
    assert pending.load_pending(tmp_path / "nope.json") == []
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert pending.load_pending(bad) == []
    bad.write_text('{"symbol": "A"}', encoding="utf-8")   # dict ไม่ใช่ list
    assert pending.load_pending(bad) == []
