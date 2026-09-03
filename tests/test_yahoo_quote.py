"""fetch_yahoo_quote: quote สดจาก Yahoo v8 (range 1d) สำหรับ /plan, /dr
(ย้ายมาจาก bot/openbell.py แพ็ค B — job ยืนยันเปิดตลาด US ถอดไปแล้ว แต่ quote สดยังใช้อยู่)"""
import importlib

import pytest

from bot.yahoo_quote import fetch_yahoo_quote


class FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


def test_fetch_yahoo_quote_parses_chart_meta():
    payload = {"chart": {"result": [{
        "meta": {"regularMarketPrice": 105.5, "chartPreviousClose": 100.0},
        "indicators": {"quote": [{"open": [102.0]}]},
    }]}}
    q = fetch_yahoo_quote("NVDA", get=lambda *a, **k: FakeResp(payload))
    assert q == {"price": 105.5, "open": 102.0, "previousClose": 100.0}


def test_fetch_yahoo_quote_raw_keeps_symbol():
    urls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        urls.append(url)
        return FakeResp({"chart": {"result": [{
            "meta": {"regularMarketPrice": 35.75, "chartPreviousClose": 35.0},
            "indicators": {"quote": [{"open": [35.25]}]},
        }]}})

    q = fetch_yahoo_quote("NVDA80.BK", get=fake_get, raw=True)
    assert q["price"] == 35.75
    assert urls[0].endswith("NVDA80.BK")    # raw: ไม่แปลงจุดเป็นขีด
    fetch_yahoo_quote("BRK.B", get=fake_get)
    assert urls[1].endswith("BRK-B")        # default: แปลงเหมือนเดิม


def test_fetch_yahoo_quote_failure_returns_none():
    assert fetch_yahoo_quote("NVDA", get=lambda *a, **k: FakeResp({}, 500)) is None
    assert fetch_yahoo_quote(
        "NVDA", get=lambda *a, **k: FakeResp({"chart": {"result": []}})) is None


# ── openbell ถอดออกแล้ว (แพ็ค B) — module ต้องหายไปจริง ไม่ใช่แค่ไม่ import ──

def test_openbell_module_no_longer_exists():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("bot.openbell")
