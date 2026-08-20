"""แหล่งราคาสำรอง (Yahoo v8 chart) — ใช้เมื่อ FMP แผนฟรีตอบ 402
ต้องคืนรูปเดียวกับ FMP: list[dict] most-recent-first, คีย์ date/open/high/low/close/volume"""
from datetime import datetime, timezone

from bot.yahoo_prices import fetch_yahoo_prices


def _ts(day):
    """epoch ของ 13:30 UTC (= 09:30 ET เปิดตลาด) วันที่ 2026-08-<day>"""
    return int(datetime(2026, 8, day, 13, 30, tzinfo=timezone.utc).timestamp())


def make_payload(ts, open_, high, low, close, volume):
    return {"chart": {"result": [{
        "meta": {"symbol": "HD"},
        "timestamp": ts,
        "indicators": {"quote": [{
            "open": open_, "high": high, "low": low,
            "close": close, "volume": volume,
        }]},
    }], "error": None}}


class Resp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def make_get(payload, status_code=200):
    calls = []

    def get(url, params=None, headers=None, timeout=None):
        calls.append((url, params))
        return Resp(payload, status_code)

    return get, calls


def test_parses_chart_to_fmp_shape_most_recent_first():
    payload = make_payload([_ts(17), _ts(18), _ts(19)],
                           [100.0, 101.0, 102.0], [102.0, 103.0, 104.0],
                           [99.0, 100.0, 101.0], [101.0, 102.0, 103.0],
                           [1000000, 1100000, 1200000])
    get, calls = make_get(payload)
    bars = fetch_yahoo_prices("HD", days=250, get=get)
    assert "/v8/finance/chart/HD" in calls[0][0]
    assert [b["date"] for b in bars] == ["2026-08-19", "2026-08-18", "2026-08-17"]
    assert bars[0] == {"date": "2026-08-19", "open": 102.0, "high": 104.0,
                       "low": 101.0, "close": 103.0, "volume": 1200000}


def test_dot_ticker_maps_to_dash():
    get, calls = make_get(make_payload([_ts(19)], [1.0], [1.0], [1.0], [1.0], [1]))
    fetch_yahoo_prices("BRK.B", get=get)
    assert "/v8/finance/chart/BRK-B" in calls[0][0]


def test_null_bars_skipped():
    # วันหยุด/แท่งพัง Yahoo ใส่ null มาในทุก array
    payload = make_payload([_ts(18), _ts(19)],
                           [101.0, None], [103.0, None], [100.0, None],
                           [102.0, None], [1100000, None])
    get, _ = make_get(payload)
    bars = fetch_yahoo_prices("HD", get=get)
    assert [b["date"] for b in bars] == ["2026-08-18"]


def test_days_cap_keeps_most_recent():
    payload = make_payload([_ts(17), _ts(18), _ts(19)],
                           [1.0] * 3, [1.0] * 3, [1.0] * 3, [1.0] * 3, [1] * 3)
    get, _ = make_get(payload)
    bars = fetch_yahoo_prices("HD", days=2, get=get)
    assert [b["date"] for b in bars] == ["2026-08-19", "2026-08-18"]


def test_returns_none_on_http_error():
    get, _ = make_get({}, status_code=429)
    assert fetch_yahoo_prices("HD", get=get) is None


def test_returns_none_on_empty_result():
    get, _ = make_get({"chart": {"result": None,
                                 "error": {"code": "Not Found"}}})
    assert fetch_yahoo_prices("ZZZZ", get=get) is None


def test_returns_none_on_network_error():
    def get(url, params=None, headers=None, timeout=None):
        raise ConnectionError("down")

    assert fetch_yahoo_prices("HD", get=get) is None
