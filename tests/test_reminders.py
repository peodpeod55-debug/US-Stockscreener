from datetime import date

from bot.formatter import format_reminders
from bot.reminders import build_reminders, next_earnings

TODAY = date(2026, 8, 20)


# ── next_earnings ────────────────────────────────────────────────

def test_next_earnings_picks_earliest_future():
    rows = [
        {"date": "2026-11-19", "time": "amc"},
        {"date": "2026-08-21", "time": "bmo"},
        {"date": "2026-05-20", "time": "amc"},  # อดีต — ข้าม
    ]
    assert next_earnings(rows, TODAY) == ("2026-08-21", "bmo")


def test_next_earnings_today_counts():
    rows = [{"date": "2026-08-20", "time": "amc"}]
    assert next_earnings(rows, TODAY) == ("2026-08-20", "amc")


def test_next_earnings_none_when_all_past():
    rows = [{"date": "2026-05-20", "time": "amc"}]
    assert next_earnings(rows, TODAY) is None
    assert next_earnings([], TODAY) is None
    assert next_earnings(None, TODAY) is None


# ── build_reminders ──────────────────────────────────────────────

def _fake_earnings(data):
    def get(symbol):
        return data.get(symbol)
    return get


def test_build_reminders_today_and_tomorrow_only():
    data = {
        "NVDA": [{"date": "2026-08-20", "time": "bmo"}],   # วันนี้
        "TSLA": [{"date": "2026-08-21", "time": "amc"}],   # พรุ่งนี้
        "AAPL": [{"date": "2026-08-25", "time": "amc"}],   # ไกลไป — ไม่เตือน
        "MSFT": [{"date": "2026-05-01", "time": "amc"}],   # ผ่านแล้ว — ไม่เตือน
    }
    items = build_reminders(["NVDA", "TSLA", "AAPL", "MSFT"],
                            _fake_earnings(data), today=TODAY)
    assert [(i["symbol"], i["days_to"], i["timing"]) for i in items] == [
        ("NVDA", 0, "bmo"), ("TSLA", 1, "amc")]
    assert items[0]["date"] == "2026-08-20"


def test_build_reminders_skips_no_data_and_errors():
    def get(symbol):
        if symbol == "BAD":
            raise RuntimeError("boom")
        return None
    assert build_reminders(["BAD", "XXX"], get, today=TODAY) == []


def test_build_reminders_normalizes_timing():
    # FMP บางทีให้ time เป็นรูปแบบอื่น เช่น "After Market Close"
    data = {"NVDA": [{"date": "2026-08-20", "time": "After Market Close"}]}
    items = build_reminders(["NVDA"], _fake_earnings(data), today=TODAY)
    assert items[0]["timing"] == "amc"


# ── format_reminders ─────────────────────────────────────────────

def test_format_reminders_message():
    items = [
        {"symbol": "NVDA", "date": "2026-08-20", "days_to": 0, "timing": "bmo"},
        {"symbol": "TSLA", "date": "2026-08-21", "days_to": 1, "timing": "amc"},
    ]
    msg = format_reminders(items)
    assert "📅 เตือนวันงบ" in msg
    assert "NVDA" in msg and "วันนี้" in msg and "ก่อนเปิดตลาด US" in msg
    assert "TSLA" in msg and "พรุ่งนี้" in msg and "หลังปิดตลาด US" in msg
    assert "2026-08-21" in msg


def test_format_reminders_unknown_timing_has_no_label():
    items = [{"symbol": "NVDA", "date": "2026-08-20",
              "days_to": 0, "timing": "unknown"}]
    msg = format_reminders(items)
    assert "NVDA" in msg
    assert "ตลาด US" not in msg


def test_format_reminders_empty_returns_none():
    assert format_reminders([]) is None
