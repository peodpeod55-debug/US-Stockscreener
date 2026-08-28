"""get_earnings_dates: stable/earnings อย่างเดียว (legacy v3 ตายสำหรับ key ใหม่ — ไม่ลองแล้ว)"""
from fmp_client import FMPClient


def make_client():
    return FMPClient(api_key="test-key", max_api_calls=10)


def test_stable_endpoint_used_first(monkeypatch):
    calls = []

    def fake_get(self, url, params=None, quiet=False):
        calls.append(url)
        return [{"symbol": "AAPL", "date": "2026-08-14", "time": "amc"}]

    monkeypatch.setattr(FMPClient, "_rate_limited_get", fake_get)
    rows = make_client().get_earnings_dates("AAPL")
    assert rows == [{"symbol": "AAPL", "date": "2026-08-14", "time": "amc"}]
    assert len(calls) == 1
    assert "stable/earnings" in calls[0]


def test_no_legacy_v3_fallback(monkeypatch):
    """api/v3/historical/earning_calendar ตอบ 403 "Legacy Endpoint" กับ key หลัง 31 ส.ค. 2025
    ทุกครั้ง — เรียกต่อมีแต่เสียเวลา rate-limit + log noise · stable ว่าง = จบ"""
    calls = []

    def fake_get(self, url, params=None, quiet=False):
        calls.append(url)
        return None

    monkeypatch.setattr(FMPClient, "_rate_limited_get", fake_get)
    assert make_client().get_earnings_dates("AAPL") is None
    assert len(calls) == 1
    assert "stable/earnings" in calls[0]


def test_returns_none_when_all_fail(monkeypatch):
    monkeypatch.setattr(FMPClient, "_rate_limited_get",
                        lambda self, url, params=None, quiet=False: None)
    assert make_client().get_earnings_dates("AAPL") is None


def test_http_402_sets_saw_402_flag(monkeypatch):
    class Resp:
        status_code = 402
        text = "Premium Query Parameter"

    client = make_client()
    monkeypatch.setattr(client.session, "get", lambda *a, **kw: Resp())
    assert client.saw_402 is False
    assert client._rate_limited_get("https://example.test", {}, quiet=True) is None
    assert client.saw_402 is True


def test_result_cached(monkeypatch):
    calls = []

    def fake_get(self, url, params=None, quiet=False):
        calls.append(url)
        return [{"symbol": "AAPL", "date": "2026-08-14"}]

    monkeypatch.setattr(FMPClient, "_rate_limited_get", fake_get)
    client = make_client()
    client.get_earnings_dates("AAPL")
    client.get_earnings_dates("AAPL")
    assert len(calls) == 1
