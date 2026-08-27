"""fallback วันงบจาก signals.json เมื่อ FMP รายตัวไม่ให้ (402 แผนฟรี / คืนว่าง)

เหตุจริง 27 ส.ค.: EL ได้เกรด B จากปฏิทินรวมตอนสแกน แต่ stable/earnings?symbol=EL ตอบ 402
→ ติดตาม / น่าสนใจ / breakout_job คำนวณแนว (H5d/SL) ไม่ได้ ทั้งที่บอทบันทึกวันงบไว้แล้ว
"""
import json
from datetime import date, timedelta

from bot import fetch_cache, signals
from bot.lookup import lookup_symbol
from bot.signals import earnings_from_signals

TODAY = date(2026, 8, 20)


def make_prices(n=120, start_price=100.0):
    """ขาขึ้นนิ่งๆ จบ 2026-08-19 (ไม่มี gap/วอลุ่มพุ่ง → infer_bmo ไม่ติด)"""
    bars, d, price = [], date(2026, 8, 19), start_price
    while len(bars) < n:
        if d.weekday() < 5:
            bars.append({"date": d.isoformat(), "open": price, "high": price + 1.0,
                         "low": price - 1.0, "close": price, "volume": 1_000_000})
            price -= 2.0
        d -= timedelta(days=1)
    return bars


class FakeClient:
    def __init__(self, prices, earnings=None):
        self._prices, self._earnings = prices, earnings

    def get_historical_prices(self, symbol, days=250):
        return self._prices

    def get_earnings_dates(self, symbol):
        return self._earnings


def _signals_file(tmp_path, rows):
    p = tmp_path / "signals.json"
    p.write_text(json.dumps(rows), encoding="utf-8")
    return p


# ── earnings_from_signals ────────────────────────────────────────


def test_rows_shaped_like_fmp_earnings_for_that_symbol_only(tmp_path):
    p = _signals_file(tmp_path, [
        {"symbol": "EL", "earnings_date": "2026-08-19", "timing": "amc", "flag_date": "2026-08-21"},
        {"symbol": "TGT", "earnings_date": "2026-08-19", "timing": "bmo", "flag_date": "2026-08-21"},
        {"symbol": "EL", "earnings_date": "2026-05-01", "timing": "unknown", "flag_date": "2026-05-05"},
    ])
    assert earnings_from_signals("EL", path=p) == [
        {"date": "2026-08-19", "time": "amc"},
        {"date": "2026-05-01", "time": None},
    ]


def test_inferred_timing_is_dropped_so_lookup_reinfers(tmp_path):
    # "bmo*" = เดาจากแท่ง ไม่ใช่ข้อมูลจริง → ส่ง None ให้ lookup อนุมานใหม่ (convention เดียวกับ pending)
    p = _signals_file(tmp_path, [{"symbol": "TGT", "earnings_date": "2026-08-19", "timing": "bmo*"}])
    assert earnings_from_signals("TGT", path=p) == [{"date": "2026-08-19", "time": None}]


def test_unknown_symbol_or_missing_file_gives_empty(tmp_path):
    p = _signals_file(tmp_path, [{"symbol": "EL", "earnings_date": "2026-08-19", "timing": "amc"}])
    assert earnings_from_signals("NVDA", path=p) == []
    assert earnings_from_signals("EL", path=tmp_path / "missing.json") == []


def test_rows_without_date_are_skipped(tmp_path):
    p = _signals_file(tmp_path, [{"symbol": "EL", "timing": "amc"}])
    assert earnings_from_signals("EL", path=p) == []


def test_default_path_is_resolved_at_call_time(tmp_path, monkeypatch):
    p = _signals_file(tmp_path, [{"symbol": "EL", "earnings_date": "2026-08-19", "timing": "amc"}])
    monkeypatch.setattr(signals, "SIGNALS_PATH", p)
    assert earnings_from_signals("EL") == [{"date": "2026-08-19", "time": "amc"}]


# ── lookup_symbol ใช้ fallback ───────────────────────────────────


def test_lookup_uses_known_earnings_when_fmp_has_none():
    bars = make_prices(120)
    s = lookup_symbol(FakeClient(bars, None), "EL", {}, today=TODAY,
                      known_earnings_fn=lambda sym: [{"date": bars[5]["date"], "time": "amc"}])
    assert s["last_earnings"] == bars[5]["date"]
    assert s["timing"] == "amc"
    assert s["levels"] is not None and s["levels"]["sl"] is not None


def test_lookup_prefers_fmp_earnings_over_fallback():
    bars = make_prices(120)
    calls = []

    def known(sym):
        calls.append(sym)
        return [{"date": bars[20]["date"], "time": "amc"}]
    client = FakeClient(bars, [{"date": bars[5]["date"], "time": "amc"}])
    s = lookup_symbol(client, "EL", {}, today=TODAY, known_earnings_fn=known)
    assert s["last_earnings"] == bars[5]["date"]
    assert calls == []


def test_fallback_result_is_not_cached_as_fmp_earnings():
    # ถ้า FMP กลับมาใช้ได้ในรอบถัดไป (ภายใน TTL) ต้องได้ข้อมูลจริง ไม่ติดค่าสำรอง
    bars = make_prices(120)
    lookup_symbol(FakeClient(bars, None), "EL", {}, today=TODAY,
                  known_earnings_fn=lambda sym: [{"date": bars[5]["date"], "time": "amc"}])
    assert fetch_cache.get(("earnings", "EL")) is None


def test_no_source_at_all_still_returns_price_snapshot():
    bars = make_prices(120)
    s = lookup_symbol(FakeClient(bars, None), "EL", {}, today=TODAY,
                      known_earnings_fn=lambda sym: [])
    assert s["price"] == bars[0]["close"]
    assert s["last_earnings"] is None and s["levels"] is None


def test_default_fallback_reads_signals_file(tmp_path, monkeypatch):
    bars = make_prices(120)
    p = _signals_file(tmp_path, [{"symbol": "EL", "earnings_date": bars[5]["date"],
                                  "timing": "bmo*"}])
    monkeypatch.setattr(signals, "SIGNALS_PATH", p)
    s = lookup_symbol(FakeClient(bars, None), "EL", {}, today=TODAY)
    assert s["last_earnings"] == bars[5]["date"]
    assert s["levels"] is not None
    assert s["timing"] == "unknown"      # bmo* ไม่ถูกส่งต่อ และแท่งนิ่งอนุมาน BMO ไม่ได้


def test_tests_are_isolated_from_real_signals_file():
    # conftest ชี้ SIGNALS_PATH ไป tmp — เทสอื่นที่ใช้ FakeClient(earnings=None) ต้องไม่เห็น EL/TGT จริง
    assert earnings_from_signals("EL") == []
