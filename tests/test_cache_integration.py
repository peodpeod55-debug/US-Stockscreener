"""cache ข้าม job: lookup/breakout/scan ดึงราคา-วันงบชุดเดียวกันซ้ำ → API call เดียว"""
from datetime import date, timedelta

from bot import fetch_cache
from bot.config import Config
from bot.lookup import lookup_symbol
from bot.screener import run_scan

TODAY = date(2026, 8, 20)


def uptrend_prices(n=250):
    bars, d, p = [], date(2026, 8, 19), 500.0
    while len(bars) < n:
        if d.weekday() < 5:
            bars.append({"date": d.isoformat(), "open": p, "high": p + 2,
                         "low": p - 2, "close": p, "volume": 2_000_000})
            p -= 1.5
        d -= timedelta(days=1)
    return bars  # most-recent-first


class CountingClient:
    def __init__(self, prices=None, earnings=None, calendar=None):
        self._prices = prices or {}
        self._earnings = earnings or {}
        self._calendar = calendar or []
        self.price_calls = 0
        self.earnings_calls = 0

    def get_historical_prices(self, symbol, days=250):
        self.price_calls += 1
        return self._prices.get(symbol)

    def get_earnings_dates(self, symbol):
        self.earnings_calls += 1
        return self._earnings.get(symbol) or []

    def get_earnings_calendar(self, from_date, to_date):
        return self._calendar

    def get_api_stats(self):
        return {"api_calls_made": self.price_calls + self.earnings_calls}


def _client_with(symbol, bars, earn_date):
    return CountingClient(
        prices={symbol: bars},
        earnings={symbol: [{"date": earn_date, "time": "amc"}]},
        calendar=[{"symbol": symbol, "date": earn_date, "time": "amc"}])


def test_lookup_second_call_served_from_cache():
    bars = uptrend_prices(120)
    client = _client_with("NVDA", bars, bars[5]["date"])
    s1 = lookup_symbol(client, "NVDA", {}, today=TODAY)
    s2 = lookup_symbol(client, "NVDA", {}, today=TODAY)
    assert s1 and s2 and s1["price"] == s2["price"]
    assert client.price_calls == 1
    assert client.earnings_calls == 1


def test_scan_reuses_prices_cached_by_lookup():
    # breakout_job (ผ่าน lookup) รัน 08:20 → daily scan 08:30 ไม่ต้องดึงราคาซ้ำ
    bars = uptrend_prices(250)
    earn_date = bars[2]["date"]
    warm = _client_with("AAPL", bars, earn_date)
    lookup_symbol(warm, "AAPL", {}, today=TODAY)

    cold = CountingClient(  # ไม่มีราคาให้ — ถ้า cache ไม่โดนใช้ AAPL จะกลายเป็น pending
        calendar=[{"symbol": "AAPL", "date": earn_date, "time": "amc"}])
    cfg = Config(telegram_token="t", chat_id="1", fmp_api_key="k")
    scan = run_scan(cfg, lookback_days=3, client=cold)
    assert scan["pending"] == []
    assert cold.price_calls == 0
    total = (len(scan["candidates"]) + scan["skipped_counts"]["C"]
             + scan["skipped_counts"]["D"])
    assert total == 1


def test_scan_fills_cache_for_later_jobs():
    bars = uptrend_prices(250)
    earn_date = bars[2]["date"]
    cfg = Config(telegram_token="t", chat_id="1", fmp_api_key="k")
    run_scan(cfg, lookback_days=3, client=_client_with("AAPL", bars, earn_date))
    assert fetch_cache.get(("prices", "AAPL", 250)) is not None
