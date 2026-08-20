from datetime import datetime
from zoneinfo import ZoneInfo

from bot.formatter import format_open_report
from bot.openbell import (
    build_open_item,
    build_open_report,
    fetch_yahoo_quote,
    in_open_window,
)

BKK = ZoneInfo("Asia/Bangkok")


def _bkk(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=BKK)


# ── in_open_window (จัดการ DST ของ US เอง) ───────────────────────

def test_summer_2100_bangkok_is_in_window():
    # ส.ค. = DST: ตลาดเปิด 20:30 ไทย → 21:00 คือ 30 นาทีหลังเปิด
    assert in_open_window(_bkk(2026, 8, 20, 21, 0)) is True


def test_summer_2200_bangkok_out_of_window():
    # 90 นาทีหลังเปิด — เกินหน้าต่าง (กัน job 22:00 ยิงซ้ำหน้าร้อน)
    assert in_open_window(_bkk(2026, 8, 20, 22, 0)) is False


def test_winter_2100_before_open_2200_in_window():
    # ม.ค. = ไม่มี DST: ตลาดเปิด 21:30 ไทย
    assert in_open_window(_bkk(2026, 1, 15, 21, 0)) is False   # ยังไม่เปิด
    assert in_open_window(_bkk(2026, 1, 15, 22, 0)) is True    # 30 นาทีหลังเปิด


def test_us_weekend_not_in_window():
    assert in_open_window(_bkk(2026, 8, 22, 21, 0)) is False   # เสาร์
    assert in_open_window(_bkk(2026, 8, 23, 21, 0)) is False   # อาทิตย์


# ── build_open_item ──────────────────────────────────────────────

def test_open_item_math():
    raw = {"price": 217.56, "open": 221.67, "previousClose": 219.74}
    it = build_open_item("NVDA", raw)
    assert round(it["day_pct"], 2) == -0.99
    assert round(it["gap_pct"], 2) == 0.88
    assert it["above_open"] is False
    assert it["price"] == 217.56


def test_open_item_above_open():
    raw = {"price": 105.0, "open": 102.0, "previousClose": 100.0}
    it = build_open_item("X", raw)
    assert it["above_open"] is True
    assert round(it["day_pct"], 2) == 5.0


def test_open_item_missing_fields_none():
    assert build_open_item("X", None) is None
    assert build_open_item("X", {"open": 1.0}) is None
    assert build_open_item("X", {"price": 1.0, "previousClose": 0}) is None


# ── build_open_report ────────────────────────────────────────────

def test_build_open_report_skips_failures():
    quotes = {"NVDA": {"price": 105.0, "open": 102.0, "previousClose": 100.0}}

    def get_quote(sym):
        if sym == "BAD":
            raise RuntimeError("boom")
        return quotes.get(sym)

    items = build_open_report(["NVDA", "BAD", "NONE"], get_quote)
    assert [i["symbol"] for i in items] == ["NVDA"]


# ── fetch_yahoo_quote ────────────────────────────────────────────

class FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


def test_fetch_yahoo_quote_parses_chart_meta():
    payload = {"chart": {"result": [{
        "meta": {"regularMarketPrice": 105.5, "chartPreviousClose": 100.0},
        "indicators": {"quote": [{"open": [102.0]}]},
    }]}}
    q = fetch_yahoo_quote("NVDA", get=lambda *a, **k: FakeResp(payload))
    assert q == {"price": 105.5, "open": 102.0, "previousClose": 100.0}


def test_fetch_yahoo_quote_failure_returns_none():
    assert fetch_yahoo_quote("NVDA", get=lambda *a, **k: FakeResp({}, 500)) is None
    assert fetch_yahoo_quote(
        "NVDA", get=lambda *a, **k: FakeResp({"chart": {"result": []}})) is None


# ── FMPClient.get_quote ──────────────────────────────────────────

import bot.lookup  # noqa: E402,F401  (ตั้ง sys.path ให้ vendor)
from fmp_client import FMPClient  # noqa: E402


def test_fmp_get_quote_uses_stable_endpoint(monkeypatch):
    client = FMPClient(api_key="x")
    calls = []

    def fake(url, params=None, quiet=False):
        calls.append(url)
        return [{"symbol": "NVDA", "price": 217.56, "open": 221.67}]

    monkeypatch.setattr(client, "_rate_limited_get", fake)
    q = client.get_quote("NVDA")
    assert q["price"] == 217.56
    assert "stable/quote" in calls[0]


def test_fmp_get_quote_bad_response_returns_none(monkeypatch):
    client = FMPClient(api_key="x")
    monkeypatch.setattr(client, "_rate_limited_get",
                        lambda *a, **k: [])
    assert client.get_quote("NVDA") is None
    monkeypatch.setattr(client, "_rate_limited_get",
                        lambda *a, **k: None)
    assert client.get_quote("NVDA") is None


# ── format_open_report ───────────────────────────────────────────

def _item(**over):
    it = {"symbol": "NVDA", "price": 105.0, "day_pct": 5.0,
          "gap_pct": 2.0, "above_open": True}
    it.update(over)
    return it


def test_format_open_report_message():
    msg = format_open_report([
        _item(),
        _item(symbol="WMT", price=98.1, day_pct=-1.9, gap_pct=-0.5,
              above_open=False),
    ])
    assert "เปิด" in msg and "US" in msg
    assert "🟢 NVDA" in msg and "+5.0%" in msg and "gap +2.0%" in msg
    assert "🔴 WMT" in msg and "-1.9%" in msg
    assert "เหนือราคาเปิด" in msg and "ต่ำกว่าราคาเปิด" in msg


def test_format_open_report_empty_returns_none():
    assert format_open_report([]) is None
