"""ปฏิทินงบแหล่งที่สอง (NASDAQ) — แผนฟรี FMP กรองหุ้นออกจากปฏิทินเงียบ ๆ
เลยต้องมีแหล่งเทียบว่าหุ้น universe ตัวไหนออกงบจริงบ้าง"""
from bot.nasdaq_cal import fetch_nasdaq_earnings


class Resp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def make_get(rows_by_date, fail_dates=()):
    """fake requests.get: คืน rows ตามวันที่ + จด date ที่ถูกเรียก"""
    calls = []

    def get(url, params=None, headers=None, timeout=None):
        d = params["date"]
        calls.append(d)
        if d in fail_dates:
            raise ConnectionError("network down")
        return Resp({"data": {"rows": rows_by_date.get(d)}})

    return get, calls


def test_parses_rows_and_maps_timing():
    get, _ = make_get({"2026-08-18": [
        {"symbol": "HD", "time": "time-pre-market"},
        {"symbol": "AMAT", "time": "time-after-hours"},
        {"symbol": "XYZ", "time": "time-not-supplied"},
    ]})
    rows = fetch_nasdaq_earnings("2026-08-18", "2026-08-18", get=get)
    assert rows == [
        {"symbol": "HD", "date": "2026-08-18", "time": "bmo"},
        {"symbol": "AMAT", "date": "2026-08-18", "time": "amc"},
        {"symbol": "XYZ", "date": "2026-08-18", "time": None},
    ]


def test_iterates_range_skipping_weekends():
    # ศ 14 → จ 17: เสาร์ 15 / อาทิตย์ 16 ต้องไม่ถูกยิง
    get, calls = make_get({})
    fetch_nasdaq_earnings("2026-08-14", "2026-08-17", get=get)
    assert calls == ["2026-08-14", "2026-08-17"]


def test_one_bad_day_does_not_kill_the_rest():
    get, _ = make_get(
        {"2026-08-19": [{"symbol": "DE", "time": "time-pre-market"}]},
        fail_dates={"2026-08-18"})
    rows = fetch_nasdaq_earnings("2026-08-18", "2026-08-19", get=get)
    assert rows == [{"symbol": "DE", "date": "2026-08-19", "time": "bmo"}]


def test_null_rows_and_blank_symbols_skipped():
    get, _ = make_get({"2026-08-18": None,
                       "2026-08-19": [{"symbol": "", "time": None},
                                      {"symbol": " WMT ", "time": None}]})
    rows = fetch_nasdaq_earnings("2026-08-18", "2026-08-19", get=get)
    assert rows == [{"symbol": "WMT", "date": "2026-08-19", "time": None}]
