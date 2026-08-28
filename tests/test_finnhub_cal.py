"""ปฏิทินงบ Finnhub (ตัวเลือก — ต้องมี FINNHUB_API_KEY) — จุดเด่นคือ field hour = bmo/amc
ที่ NASDAQ มักไม่บอก (time-not-supplied) · คืนรูปเดียวกับ FMP/NASDAQ: {symbol, date, time}
เป็นแหล่งเสริม: ไม่มี key / ล้ม / JSON พัง → [] ห้าม raise"""
from bot.finnhub_cal import FINNHUB_URL, fetch_finnhub_earnings


class Resp:
    def __init__(self, payload, status_code=200):
        self._payload, self.status_code = payload, status_code

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _get(payload, calls, status_code=200):
    def get(url, params=None, headers=None, timeout=None):
        calls.append((url, params, headers))
        return Resp(payload, status_code)
    return get


def test_parses_rows_and_maps_hour_to_timing():
    payload = {"earningsCalendar": [
        {"date": "2026-09-02", "symbol": "CRM", "hour": "amc", "epsEstimate": 2.1},
        {"date": "2026-09-03", "symbol": "BRK.B", "hour": "bmo"},
        {"date": "2026-09-03", "symbol": "X", "hour": "dmh"},   # ระหว่างวัน → ไม่ระบุ
        {"date": "2026-09-04", "symbol": "Y", "hour": ""},
        {"date": "2026-09-04", "symbol": "", "hour": "amc"},    # ไม่มี symbol → ข้าม
    ]}
    calls = []
    rows = fetch_finnhub_earnings("2026-09-01", "2026-09-05", api_key="k",
                                  get=_get(payload, calls))
    assert rows == [
        {"symbol": "CRM", "date": "2026-09-02", "time": "amc"},
        {"symbol": "BRK.B", "date": "2026-09-03", "time": "bmo"},
        {"symbol": "X", "date": "2026-09-03", "time": None},
        {"symbol": "Y", "date": "2026-09-04", "time": None},
    ]


def test_sends_token_in_header_not_in_url():
    calls = []
    fetch_finnhub_earnings("2026-09-01", "2026-09-05", api_key="secret-k",
                           get=_get({"earningsCalendar": []}, calls))
    url, params, headers = calls[0]
    assert url == FINNHUB_URL
    assert params == {"from": "2026-09-01", "to": "2026-09-05"}
    assert headers["X-Finnhub-Token"] == "secret-k"
    assert "secret-k" not in url and "token" not in params


def test_no_key_returns_empty_without_request():
    calls = []
    assert fetch_finnhub_earnings("2026-09-01", "2026-09-05", api_key="",
                                  get=_get({}, calls)) == []
    assert fetch_finnhub_earnings("2026-09-01", "2026-09-05", api_key=None,
                                  get=_get({}, calls)) == []
    assert calls == []


def test_http_error_or_bad_payload_returns_empty():
    assert fetch_finnhub_earnings("2026-09-01", "2026-09-05", api_key="k",
                                  get=_get({}, [], status_code=429)) == []
    assert fetch_finnhub_earnings("2026-09-01", "2026-09-05", api_key="k",
                                  get=_get(ValueError("bad json"), [])) == []
    assert fetch_finnhub_earnings("2026-09-01", "2026-09-05", api_key="k",
                                  get=_get({"earningsCalendar": None}, [])) == []

    def boom(*a, **k):
        raise ConnectionError("down")
    assert fetch_finnhub_earnings("2026-09-01", "2026-09-05", api_key="k",
                                  get=boom) == []
