"""FMPClient.get_quote (ย้ายมาจาก tests/test_openbell.py แพ็ค B — openbell ถอดไปแล้ว
แต่ get_quote เป็น method ทั่วไปของ vendored client ยังต้องมีเทสต่างหาก)"""
import bot.lookup  # noqa: F401  (ตั้ง sys.path ให้ vendor)
from fmp_client import FMPClient


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
