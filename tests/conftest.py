import pytest

from bot import fetch_cache


@pytest.fixture(autouse=True)
def _clear_fetch_cache():
    """cache เป็น state ระดับโมดูล — ล้างก่อน/หลังทุก test กันรั่วข้าม test"""
    fetch_cache.clear()
    yield
    fetch_cache.clear()
