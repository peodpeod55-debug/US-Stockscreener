import pytest

from bot import fetch_cache, pending


@pytest.fixture(autouse=True)
def _isolate_pending(tmp_path, monkeypatch):
    """pending.json เป็น state จริงของเครื่อง — run_scan ในเทสต์ต้องไม่เขียนทับ"""
    monkeypatch.setattr(pending, "PENDING_PATH", tmp_path / "pending.json")


@pytest.fixture(autouse=True)
def _clear_fetch_cache():
    """cache เป็น state ระดับโมดูล — ล้างก่อน/หลังทุก test กันรั่วข้าม test"""
    fetch_cache.clear()
    yield
    fetch_cache.clear()
