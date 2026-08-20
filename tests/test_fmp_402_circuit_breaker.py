"""402 = หุ้นนอกแผน ไม่ใช่ endpoint เสีย — ต้องไม่สะสมเข้า circuit breaker

เคสจริงที่เจอ: แผนฟรีโดน 402 ติดกัน 3 ตัว → endpoint หลักถูกปิดทั้ง client
→ หุ้นที่เหลือ (รวมตัวที่อยู่ในแผน) ดึงไม่ได้หมดโดยไม่ยิง HTTP เลย
"""
import pytest

from fmp_client import FMPClient

BARS = [{"date": "2026-08-19", "open": 100.0, "high": 101.0,
         "low": 99.0, "close": 100.5, "volume": 1_000_000}]


class Resp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload
        self.text = f"http {status_code}"

    def json(self):
        return self._payload


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(FMPClient, "RATE_LIMIT_DELAY", 0)
    return FMPClient(api_key="test-key", max_api_calls=50)


def fake_session(client, blocked=(), eod_status_for_blocked=402):
    """จำลอง FMP key ใหม่: eod/full ใช้ได้ (แต่หุ้นใน blocked โดน 402)
    ส่วน endpoint fallback เก่าตอบ 403 legacy ทุกกรณี — คืน list URL ที่ถูกยิง"""
    calls = []

    def get(url, params=None, timeout=None):
        calls.append(url)
        if "historical-price-eod/full" in url:
            if params.get("symbol") in blocked:
                return Resp(eod_status_for_blocked)
            return Resp(200, BARS)
        return Resp(403)

    client.session.get = get
    return calls


def test_402_does_not_trip_circuit_breaker(client):
    """402 ติดกัน 3 ตัว แล้วหุ้นในแผนต้องยังดึงได้ (endpoint ไม่ถูกปิด)"""
    fake_session(client, blocked={"HD", "DE", "AMAT"})
    for sym in ["HD", "DE", "AMAT"]:
        client.saw_402 = False
        assert client.get_historical_prices(sym) is None
        assert client.saw_402 is True
    client.saw_402 = False
    prices = client.get_historical_prices("WMT")
    assert prices and prices[0]["close"] == 100.5
    assert client.saw_402 is False


def test_402_stops_fallback_chain(client):
    """โดน 402 แล้วไม่ต้องไล่ endpoint เก่าต่อ — เผางบ API แค่ 1 call"""
    calls = fake_session(client, blocked={"HD"})
    assert client.get_historical_prices("HD") is None
    assert client.saw_402 is True
    assert client.api_calls_made == 1
    assert len(calls) == 1


def test_non_402_failures_still_disable_endpoint(client):
    """พฤติกรรมเดิมต้องอยู่: ล้มเหลวจริง (500) ครบ 3 ครั้งติด → endpoint ถูกปิด"""
    calls = fake_session(client, blocked={"A1", "A2", "A3", "A4"},
                         eod_status_for_blocked=500)
    for sym in ["A1", "A2", "A3"]:
        client.get_historical_prices(sym)
    eod_calls_before = sum("historical-price-eod" in u for u in calls)
    client.get_historical_prices("A4")
    eod_calls_after = sum("historical-price-eod" in u for u in calls)
    assert eod_calls_before == 3
    assert eod_calls_after == 3  # ตัวที่ 4 ไม่ยิง endpoint ที่ถูกปิดแล้ว
