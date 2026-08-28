import pytest

from bot import earnings_store, fetch_cache, pending, prices, signals


@pytest.fixture(autouse=True)
def _no_yahoo_network(monkeypatch):
    """Yahoo เป็นแหล่งราคาหลัก (bot/prices.py) — เทสต์ห้ามยิงเครือข่ายจริง
    ปิดไว้ = ราคาไหลไป client ปลอม (FMP path) ตามที่เทสต์แต่ละไฟล์ตั้งไว้"""
    monkeypatch.setattr(prices, "fetch_yahoo_prices",
                        lambda symbol, days=250: None)


@pytest.fixture(autouse=True)
def _isolate_pending(tmp_path, monkeypatch):
    """pending.json เป็น state จริงของเครื่อง — run_scan ในเทสต์ต้องไม่เขียนทับ"""
    monkeypatch.setattr(pending, "PENDING_PATH", tmp_path / "pending.json")


@pytest.fixture(autouse=True)
def _isolate_signals(tmp_path, monkeypatch):
    """signals.json จริงมี EL/TGT — fallback วันงบใน lookup ต้องไม่เห็นในเทส (เทสตั้งไฟล์เองได้)"""
    monkeypatch.setattr(signals, "SIGNALS_PATH", tmp_path / "signals.json")


@pytest.fixture(autouse=True)
def _isolate_earnings_store(tmp_path, monkeypatch):
    """earnings_calendar.json เป็นคลังจริงของเครื่อง — run_scan/build_calendar ในเทส merge ลงคลัง
    ต้องไม่เขียนทับ และ lookup ต้องไม่เห็นวันงบจริง"""
    monkeypatch.setattr(earnings_store, "STORE_PATH",
                        tmp_path / "earnings_calendar.json")


@pytest.fixture(autouse=True)
def _clear_fetch_cache():
    """cache เป็น state ระดับโมดูล — ล้างก่อน/หลังทุก test กันรั่วข้าม test"""
    fetch_cache.clear()
    yield
    fetch_cache.clear()
