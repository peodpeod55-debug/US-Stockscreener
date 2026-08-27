"""fmp_client ต้อง log ผ่าน logging ไม่ใช่ print ลง stderr

บอทรันผ่าน start_bot_hidden.vbs ไม่มี console → stderr หายเฉย ๆ: 402/403/timeout
ของ FMP ไม่เคยถึง bot.log เลย (บั๊ก D0 ผิดวันถึงเจอช้า) · URL/params ไม่มี API key
(key อยู่ใน header) จึง log ได้ปลอดภัย
"""
import logging

import pytest
import requests

from fmp_client import FMPClient


class Resp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload
        self.text = f"http {status_code} body"

    def json(self):
        return self._payload


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(FMPClient, "RATE_LIMIT_DELAY", 0)
    return FMPClient(api_key="secret-key-123", max_api_calls=50)


def _records(caplog, level):
    return [r for r in caplog.records if r.name == "bot.fmp" and r.levelno == level]


def test_402_logged_at_info_not_printed(client, caplog, capsys):
    client.session.get = lambda url, params=None, timeout=None: Resp(402)
    with caplog.at_level(logging.INFO, logger="bot.fmp"):
        assert client.get_historical_prices("HD") is None
    assert client.saw_402 is True
    assert capsys.readouterr().err == ""
    infos = _records(caplog, logging.INFO)
    assert infos and "402" in infos[0].getMessage() and "HD" in infos[0].getMessage()
    assert "secret-key-123" not in caplog.text


def test_server_error_logged_as_warning_with_body(client, caplog, capsys):
    client.session.get = lambda url, params=None, timeout=None: Resp(500)
    with caplog.at_level(logging.INFO, logger="bot.fmp"):
        assert client.get_earnings_calendar("2026-08-01", "2026-08-02") is None
    assert capsys.readouterr().err == ""
    warns = _records(caplog, logging.WARNING)
    assert warns and "500" in warns[0].getMessage()
    assert "http 500 body" in warns[0].getMessage()


def test_quiet_fallback_failure_only_debug(client, caplog, capsys):
    """endpoint สำรองที่คาดว่า 403 (quiet=True) ไม่ควรดัง — เดิมก็ไม่ print"""
    client.session.get = lambda url, params=None, timeout=None: Resp(403)
    with caplog.at_level(logging.DEBUG, logger="bot.fmp"):
        client._rate_limited_get("https://x/legacy", {"symbol": "A"}, quiet=True)
    assert capsys.readouterr().err == ""
    assert not _records(caplog, logging.WARNING)
    assert _records(caplog, logging.DEBUG)


def test_timeout_and_request_error_logged(client, caplog, capsys):
    def timeout(url, params=None, timeout=None):
        raise requests.exceptions.Timeout()

    def conn_err(url, params=None, timeout=None):
        raise requests.exceptions.ConnectionError("dns down")

    with caplog.at_level(logging.INFO, logger="bot.fmp"):
        client.session.get = timeout
        assert client.get_earnings_calendar("2026-08-01", "2026-08-02") is None
        client.session.get = conn_err
        assert client.get_earnings_calendar("2026-08-03", "2026-08-04") is None
    assert capsys.readouterr().err == ""
    msgs = [r.getMessage() for r in _records(caplog, logging.WARNING)]
    assert any("timeout" in m.lower() for m in msgs)
    assert any("dns down" in m for m in msgs)


def test_429_retry_then_give_up_logged(client, caplog, capsys, monkeypatch):
    monkeypatch.setattr("fmp_client.time.sleep", lambda s: None)
    client.session.get = lambda url, params=None, timeout=None: Resp(429)
    with caplog.at_level(logging.INFO, logger="bot.fmp"):
        assert client.get_earnings_calendar("2026-08-01", "2026-08-02") is None
    assert client.rate_limit_reached is True
    assert capsys.readouterr().err == ""
    assert any("429" in r.getMessage() for r in _records(caplog, logging.WARNING))
    assert _records(caplog, logging.ERROR)
