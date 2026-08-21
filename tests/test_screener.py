from datetime import date, timedelta
from pathlib import Path

from bot.config import Config
from bot.screener import load_universe, run_scan

ROOT = Path(__file__).resolve().parents[1]


def test_load_universe_dr_or_sp500():
    uni = load_universe(ROOT / "us_stock_list.csv")
    assert "AAPL" in uni                       # DR + SP500
    assert "ABT" in uni                        # SP500 เท่านั้น (dr=N)
    assert "ABEO" not in uni                   # ไม่มี DR ไม่อยู่ SP500
    assert uni["AAPL"]["dr_symbols"].startswith("AAPL01")
    assert 400 < len(uni) < 700


class FakeClient:
    """FMPClient ปลอม: มีหุ้น 2 ตัวออกงบ — ตัวหนึ่งใน universe อีกตัวไม่อยู่"""

    def __init__(self, calendar, prices):
        self._calendar = calendar
        self._prices = prices
        self.api_calls_made = 0

    def get_earnings_calendar(self, from_date, to_date):
        return self._calendar

    def get_historical_prices(self, symbol, days=250):
        return self._prices.get(symbol)

    def get_api_stats(self):
        return {"api_calls_made": 1}


def _uptrend_prices(n=250):
    bars, d, p = [], date(2026, 8, 19), 500.0
    while len(bars) < n:
        if d.weekday() < 5:
            bars.append({"date": d.isoformat(), "open": p, "high": p + 2,
                         "low": p - 2, "close": p, "volume": 2_000_000})
            p -= 1.5
        d -= timedelta(days=1)
    return bars


def test_run_scan_filters_to_universe_and_grades():
    bars = _uptrend_prices()
    earn_date = bars[2]["date"]
    calendar = [
        {"symbol": "AAPL", "date": earn_date, "time": "amc"},
        {"symbol": "ZZZZ", "date": earn_date, "time": "amc"},  # นอก universe
    ]
    cfg = Config(telegram_token="t", chat_id="1", fmp_api_key="k")
    scan = run_scan(cfg, lookback_days=3,
                    client=FakeClient(calendar, {"AAPL": bars}))
    assert scan["reported_symbols"] == ["AAPL"]
    all_syms = [c["symbol"] for c in scan["candidates"]]
    total = (len(all_syms) + scan["skipped_counts"]["C"]
             + scan["skipped_counts"]["D"] + len(scan["pending"]))
    assert total == 1
    for c in scan["candidates"]:
        assert c["grade"] in ("A", "B")
        assert c["levels"]["price"] > 0
        assert c["dr_symbols"]


class Fake402Client(FakeClient):
    """เหมือน FakeClient แต่หุ้นใน blocked ตอบ HTTP 402 (ตั้งธง saw_402)"""

    def __init__(self, calendar, prices, blocked=()):
        super().__init__(calendar, prices)
        self.blocked = set(blocked)
        self.saw_402 = False

    def get_historical_prices(self, symbol, days=250):
        if symbol in self.blocked:
            self.saw_402 = True
            return None
        return super().get_historical_prices(symbol, days)


def test_run_scan_separates_plan_blocked_from_no_data():
    """402 → reason not_in_plan · ไม่มีข้อมูลเฉย ๆ → no_data (ธงต้อง reset ต่อตัว)"""
    bars = _uptrend_prices()
    earn_date = bars[2]["date"]
    calendar = [
        {"symbol": "WMT", "date": earn_date, "time": "amc"},   # โดน 402 ก่อน
        {"symbol": "AAPL", "date": earn_date, "time": "amc"},  # ไม่มีข้อมูลเฉย ๆ
    ]
    cfg = Config(telegram_token="t", chat_id="1", fmp_api_key="k")
    scan = run_scan(cfg, lookback_days=3,
                    client=Fake402Client(calendar, {}, blocked={"WMT"}))
    reasons = {p["symbol"]: p["reason"] for p in scan["pending"]}
    assert reasons == {"WMT": "not_in_plan", "AAPL": "no_data"}


def test_run_scan_fallback_prices_rescue_402_symbol():
    """หุ้นโดน 402 แต่แหล่งสำรองมีราคา → ต้องถูกวิเคราะห์ปกติ ไม่ค้างใน pending"""
    bars = _uptrend_prices()
    calendar = [{"symbol": "WMT", "date": bars[2]["date"], "time": "amc"}]
    calls = []

    def fallback(symbol, days):
        calls.append((symbol, days))
        return bars

    cfg = Config(telegram_token="t", chat_id="1", fmp_api_key="k")
    scan = run_scan(cfg, lookback_days=3,
                    client=Fake402Client(calendar, {}, blocked={"WMT"}),
                    fallback_prices_fn=fallback)
    assert calls == [("WMT", 250)]
    assert scan["pending"] == []
    total = (len(scan["candidates"]) + scan["skipped_counts"]["C"]
             + scan["skipped_counts"]["D"])
    assert total == 1


def test_run_scan_fallback_failure_keeps_not_in_plan():
    bars = _uptrend_prices()
    calendar = [{"symbol": "WMT", "date": bars[2]["date"], "time": "amc"}]

    def fallback(symbol, days):
        raise ConnectionError("stooq down")

    cfg = Config(telegram_token="t", chat_id="1", fmp_api_key="k")
    scan = run_scan(cfg, lookback_days=3,
                    client=Fake402Client(calendar, {}, blocked={"WMT"}),
                    fallback_prices_fn=fallback)
    assert [(p["symbol"], p["reason"]) for p in scan["pending"]] == \
        [("WMT", "not_in_plan")]


def test_run_scan_fallback_not_used_without_402():
    """ไม่มีข้อมูลเฉย ๆ (ไม่ใช่ 402) → ไม่เรียกแหล่งสำรอง, reason ยังเป็น no_data"""
    bars = _uptrend_prices()
    calendar = [{"symbol": "AAPL", "date": bars[2]["date"], "time": "amc"}]
    calls = []

    def fallback(symbol, days):
        calls.append(symbol)
        return bars

    cfg = Config(telegram_token="t", chat_id="1", fmp_api_key="k")
    scan = run_scan(cfg, lookback_days=3,
                    client=FakeClient(calendar, {}),
                    fallback_prices_fn=fallback)
    assert calls == []
    assert [(p["symbol"], p["reason"]) for p in scan["pending"]] == \
        [("AAPL", "no_data")]


def test_run_scan_merges_secondary_calendar():
    """หุ้นที่แผนฟรีซ่อนจากปฏิทิน FMP ต้องถูกเติมจากแหล่งที่สอง
    → ตัวที่โดน 402 ขึ้น not_in_plan / ตัวซ้ำ+นอก universe ถูกกรอง"""
    bars = _uptrend_prices()
    earn_date = bars[2]["date"]
    calendar = [{"symbol": "AAPL", "date": earn_date, "time": "amc"}]
    seen_ranges = []

    def secondary(from_date, to_date):
        seen_ranges.append((from_date, to_date))
        return [
            {"symbol": "HD", "date": earn_date, "time": "bmo"},    # โดนซ่อน + 402
            {"symbol": "AAPL", "date": earn_date, "time": None},   # ซ้ำกับ FMP
            {"symbol": "ZZZZ", "date": earn_date, "time": None},   # นอก universe
        ]

    cfg = Config(telegram_token="t", chat_id="1", fmp_api_key="k")
    scan = run_scan(cfg, lookback_days=3,
                    client=Fake402Client(calendar, {"AAPL": bars},
                                         blocked={"HD"}),
                    secondary_cal_fn=secondary)
    assert scan["reported_symbols"] == ["AAPL", "HD"]
    assert seen_ranges == [(scan["from_date"], scan["to_date"])]
    reasons = {p["symbol"]: p["reason"] for p in scan["pending"]}
    assert reasons.get("HD") == "not_in_plan"


def test_run_scan_secondary_failure_does_not_break_scan():
    bars = _uptrend_prices()
    calendar = [{"symbol": "AAPL", "date": bars[2]["date"], "time": "amc"}]

    def broken(from_date, to_date):
        raise ConnectionError("nasdaq down")

    cfg = Config(telegram_token="t", chat_id="1", fmp_api_key="k")
    scan = run_scan(cfg, lookback_days=3,
                    client=FakeClient(calendar, {"AAPL": bars}),
                    secondary_cal_fn=broken)
    assert scan["reported_symbols"] == ["AAPL"]


def test_run_scan_pending_when_reaction_day_missing():
    """งบ AMC ของ bar ล่าสุด → วันตอบรับยังไม่มีข้อมูล → ต้องเข้า pending"""
    bars = _uptrend_prices()
    calendar = [
        {"symbol": "WMT", "date": bars[0]["date"], "time": "amc"},   # รอวันตอบรับ
        {"symbol": "AAPL", "date": bars[0]["date"], "time": None},   # ไม่มีข้อมูลราคา
    ]
    cfg = Config(telegram_token="t", chat_id="1", fmp_api_key="k")
    scan = run_scan(cfg, lookback_days=3,
                    client=FakeClient(calendar, {"WMT": bars}))
    pending_syms = {p["symbol"] for p in scan["pending"]}
    assert pending_syms == {"WMT", "AAPL"}
    assert scan["candidates"] == []


def _bmo_reaction_bars():
    """ขาขึ้น + แท่งล่าสุด (วันงบ) gap up 6% วอลุ่ม 4x — ลายเซ็นตอบรับงบ BMO"""
    bars = _uptrend_prices()
    prev_close = bars[1]["close"]
    bars[0]["open"] = prev_close * 1.06
    bars[0]["close"] = prev_close * 1.08
    bars[0]["high"] = prev_close * 1.09
    bars[0]["low"] = prev_close * 1.05
    bars[0]["volume"] = 8_000_000
    return bars


def test_run_scan_takes_timing_from_secondary_for_fmp_symbol():
    """ปฏิทิน FMP ไม่มี field time — timing ต้องถูกเติมจากแหล่งที่สอง
    (เดิมตัวซ้ำโดน dedup ทิ้งทั้ง entry ทำให้ timing หายไปด้วย)"""
    bars = _uptrend_prices()
    earn_date = bars[0]["date"]  # งบวันเดียวกับ bar ล่าสุด
    calendar = [{"symbol": "AAPL", "date": earn_date}]  # FMP: ไม่มี time
    secondary = [{"symbol": "AAPL", "date": earn_date, "time": "bmo"}]
    cfg = Config(telegram_token="t", chat_id="1", fmp_api_key="k")
    scan = run_scan(cfg, lookback_days=3,
                    client=FakeClient(calendar, {"AAPL": bars}),
                    secondary_cal_fn=lambda f, t: secondary)
    # bmo → D0 = วันงบเอง มีแท่งแล้ว ต้องไม่ค้าง waiting
    assert scan["pending"] == []


def test_run_scan_secondary_timing_joins_slash_symbol():
    """สัญลักษณ์คนละ format (BRK.B vs BRK/B) ต้อง join timing กันเจอ"""
    bars = _uptrend_prices()
    earn_date = bars[0]["date"]
    calendar = [{"symbol": "BRK.B", "date": earn_date}]
    secondary = [{"symbol": "BRK/B", "date": earn_date, "time": "bmo"}]
    cfg = Config(telegram_token="t", chat_id="1", fmp_api_key="k")
    scan = run_scan(cfg, lookback_days=3,
                    client=FakeClient(calendar, {"BRK.B": bars}),
                    secondary_cal_fn=lambda f, t: secondary)
    assert scan["pending"] == []


def test_run_scan_infers_bmo_from_reaction_bar():
    """timing unknown แต่แท่งวันงบ gap แรง+วอลุ่มพุ่ง → อนุมาน BMO ป้าย bmo*"""
    bars = _bmo_reaction_bars()
    calendar = [{"symbol": "AAPL", "date": bars[0]["date"]}]  # ไม่มี timing เลย
    cfg = Config(telegram_token="t", chat_id="1", fmp_api_key="k")
    scan = run_scan(cfg, lookback_days=3,
                    client=FakeClient(calendar, {"AAPL": bars}))
    assert scan["pending"] == []
    assert len(scan["candidates"]) == 1
    c = scan["candidates"][0]
    assert c["timing"] == "bmo*"
    assert c["levels"]["reaction_date"] == bars[0]["date"]


def test_run_scan_explicit_amc_not_overridden_by_inference():
    """แหล่งข้อมูลบอก amc ชัด — ต่อให้แท่งวันงบดู BMO แค่ไหนก็ห้ามเดาทับ"""
    bars = _bmo_reaction_bars()
    earn_date = bars[0]["date"]
    calendar = [{"symbol": "AAPL", "date": earn_date}]
    secondary = [{"symbol": "AAPL", "date": earn_date, "time": "amc"}]
    cfg = Config(telegram_token="t", chat_id="1", fmp_api_key="k")
    scan = run_scan(cfg, lookback_days=3,
                    client=FakeClient(calendar, {"AAPL": bars}),
                    secondary_cal_fn=lambda f, t: secondary)
    assert [(p["symbol"], p["reason"]) for p in scan["pending"]] == \
        [("AAPL", "waiting")]
