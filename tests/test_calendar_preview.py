from datetime import date

from bot.calendar_preview import (
    DEFAULT_AHEAD,
    MAX_AHEAD,
    build_calendar,
    parse_calendar_command,
)
from bot.formatter import MAX_LEN, format_calendar

UNI = {
    "NVDA": {"name": "NVIDIA Corp", "dr_symbols": "NVDA80 NVDA19"},
    "TGT": {"name": "Target", "dr_symbols": ""},
    "WMT": {"name": "Walmart", "dr_symbols": "WMT23"},
    "BRK.B": {"name": "Berkshire", "dr_symbols": ""},
}

TODAY = date(2026, 8, 24)


def _cal(rows):
    return lambda from_date, to_date: rows


# ── parse_calendar_command ───────────────────────────────────────

def test_parse_calendar_command_default():
    assert parse_calendar_command("งบ") == DEFAULT_AHEAD
    assert parse_calendar_command("ปฏิทินงบ") == DEFAULT_AHEAD


def test_parse_calendar_command_days_arg():
    assert parse_calendar_command("งบ 5") == 5
    assert parse_calendar_command("งบ 0") == 0
    assert parse_calendar_command("งบ 99") == MAX_AHEAD
    assert parse_calendar_command("งบ -3") == 0


def test_parse_calendar_command_today_alias():
    assert parse_calendar_command("งบวันนี้") == 0


def test_parse_calendar_command_not_this_command():
    assert parse_calendar_command("NVDA") is None
    assert parse_calendar_command("ติดตาม NVDA") is None
    assert parse_calendar_command("") is None
    assert parse_calendar_command(None) is None
    assert parse_calendar_command("งบดุล") is None    # ต้องตรงคำ ไม่ใช่ prefix


def test_parse_calendar_command_bad_arg_uses_default():
    assert parse_calendar_command("งบ x") == DEFAULT_AHEAD


# ── build_calendar ───────────────────────────────────────────────

def test_build_calendar_records_rows_into_earnings_store():
    """พิมพ์ "งบ" = ได้ปฏิทินล่วงหน้ามาแล้ว → เก็บลงคลังให้เตือนวันงบ/lookup ใช้ต่อ (ฟรี)"""
    from bot import earnings_store as es
    rows = [{"symbol": "NVDA", "date": "2026-08-25", "time": "amc"},
            {"symbol": "ZZZZ", "date": "2026-08-26", "time": None}]   # นอก universe ก็เก็บ
    build_calendar(_cal(rows), UNI, today=TODAY, days_ahead=2)
    assert es.earnings_for("NVDA") == [{"date": "2026-08-25", "time": "amc"}]
    assert es.earnings_for("ZZZZ") == [{"date": "2026-08-26", "time": None}]


def test_build_calendar_filters_universe_and_range():
    rows = [
        {"symbol": "NVDA", "date": "2026-08-25", "time": "amc"},
        {"symbol": "ZZZZ", "date": "2026-08-25", "time": "bmo"},   # นอก universe
        {"symbol": "TGT", "date": "2026-08-28", "time": "bmo"},    # เกินช่วง
        {"symbol": "WMT", "date": "2026-08-23", "time": "bmo"},    # ก่อนวันนี้
        {"symbol": "BRK.B", "date": None, "time": "bmo"},          # ไม่มีวัน
    ]
    items, from_date, to_date = build_calendar(_cal(rows), UNI, today=TODAY,
                                               days_ahead=2)
    assert from_date == "2026-08-24" and to_date == "2026-08-26"
    assert [it["symbol"] for it in items] == ["NVDA"]
    assert items[0]["name"] == "NVIDIA Corp"
    assert items[0]["dr_symbols"] == "NVDA80 NVDA19"
    assert items[0]["timing"] == "amc"


def test_build_calendar_dedup_first_entry_wins():
    rows = [{"symbol": "NVDA", "date": "2026-08-25", "time": "amc"},
            {"symbol": "NVDA", "date": "2026-08-26", "time": "bmo"}]
    items, _, _ = build_calendar(_cal(rows), UNI, today=TODAY)
    assert len(items) == 1
    assert items[0]["date"] == "2026-08-25" and items[0]["timing"] == "amc"


def test_build_calendar_secondary_fills_timing():
    # FMP ไม่บอกเวลา · NASDAQ (แพ้ dedup) บอก bmo — join แบบ normalize จุด/ทับ
    fmp = [{"symbol": "BRK.B", "date": "2026-08-25", "time": None}]
    items, _, _ = build_calendar(
        _cal(fmp), UNI, today=TODAY,
        secondary_cal_fn=_cal([{"symbol": "BRK/B", "date": "2026-08-25",
                                "time": "bmo"}]))
    assert items[0]["timing"] == "bmo"


def test_build_calendar_secondary_adds_symbols_fmp_missed():
    fmp = [{"symbol": "NVDA", "date": "2026-08-25", "time": "amc"}]
    items, _, _ = build_calendar(
        _cal(fmp), UNI, today=TODAY,
        secondary_cal_fn=_cal([{"symbol": "WMT", "date": "2026-08-24",
                                "time": "bmo"}]))
    assert [it["symbol"] for it in items] == ["WMT", "NVDA"]


def test_build_calendar_secondary_failure_is_not_fatal():
    def boom(from_date, to_date):
        raise RuntimeError("down")
    rows = [{"symbol": "NVDA", "date": "2026-08-25", "time": "amc"}]
    items, _, _ = build_calendar(_cal(rows), UNI, today=TODAY,
                                 secondary_cal_fn=boom)
    assert [it["symbol"] for it in items] == ["NVDA"]


def test_build_calendar_empty_calendar():
    items, _, _ = build_calendar(_cal(None), UNI, today=TODAY)
    assert items == []


def test_build_calendar_sorted_by_date_then_timing_then_symbol():
    rows = [
        {"symbol": "WMT", "date": "2026-08-26", "time": "bmo"},
        {"symbol": "TGT", "date": "2026-08-25", "time": None},
        {"symbol": "NVDA", "date": "2026-08-25", "time": "amc"},
        {"symbol": "BRK.B", "date": "2026-08-25", "time": "bmo"},
    ]
    items, _, _ = build_calendar(_cal(rows), UNI, today=TODAY)
    assert [it["symbol"] for it in items] == ["BRK.B", "NVDA", "TGT", "WMT"]


# ── format_calendar ──────────────────────────────────────────────

def _item(sym="NVDA", d="2026-08-24", timing="bmo", dr="NVDA80"):
    return {"symbol": sym, "date": d, "timing": timing,
            "name": sym, "dr_symbols": dr}


def test_format_calendar_groups_by_day_and_timing():
    items = [_item(d="2026-08-24", timing="bmo"),
             _item(sym="TGT", d="2026-08-25", timing="amc", dr=""),
             _item(sym="WMT", d="2026-08-25", timing="unknown", dr="WMT23")]
    text = "\n\n".join(format_calendar(items, "2026-08-24", "2026-08-26", 2,
                                       watchlist=["WMT"]))
    assert "2026-08-24 → 2026-08-26" in text
    assert "วันนี้ (2026-08-24) — 1 ตัว" in text
    assert "พรุ่งนี้ (2026-08-25) — 2 ตัว" in text
    assert "อีก 2 วัน (2026-08-26) — ไม่มี" in text
    assert "ก่อนเปิดตลาด US: NVDA🇹🇭" in text
    assert "หลังปิดตลาด US: TGT" in text
    assert "ไม่ระบุเวลา: WMT🇹🇭📌" in text
    assert "🇹🇭 = มี DR ไทย" in text


def test_format_calendar_empty_range_says_none_per_day():
    msgs = format_calendar([], "2026-08-24", "2026-08-24", 0)
    assert len(msgs) == 1
    assert "วันนี้ (2026-08-24) — ไม่มี" in msgs[0]


def test_format_calendar_wraps_long_symbol_rows():
    items = [_item(sym=f"SYM{i}", timing="bmo", dr="") for i in range(25)]
    msgs = format_calendar(items, "2026-08-24", "2026-08-24", 0)
    body = "\n\n".join(msgs)
    # 25 ตัว × แถวละ 10 → 3 บรรทัด (บรรทัดต่อเนื่องไม่มีป้ายเวลา)
    assert body.count("ก่อนเปิดตลาด US:") == 1
    assert "SYM24" in body


def test_format_calendar_splits_when_over_max_len():
    items = []
    for day in range(24, 31):                       # 7 วัน × 60 ตัว
        for i in range(60):
            items.append(_item(sym=f"S{day}X{i}", d=f"2026-08-{day}",
                               timing="bmo", dr=""))
    msgs = format_calendar(items, "2026-08-24", "2026-08-30", 6)
    assert len(msgs) >= 2
    assert all(len(m) <= MAX_LEN for m in msgs)
