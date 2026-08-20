from datetime import datetime, timedelta

from bot.fetch_cache import CACHE_TTL, cached, clear, get, put

T0 = datetime(2026, 8, 20, 8, 20)


def test_put_get_roundtrip():
    put(("prices", "NVDA", 250), [{"close": 1.0}], now=T0)
    assert get(("prices", "NVDA", 250), now=T0) == [{"close": 1.0}]


def test_get_missing_returns_none():
    assert get(("prices", "ไม่มี", 250), now=T0) is None


def test_within_ttl_still_fresh():
    put("k", [1], now=T0)
    assert get("k", now=T0 + CACHE_TTL - timedelta(seconds=1)) == [1]


def test_expired_returns_none():
    put("k", [1], now=T0)
    assert get("k", now=T0 + CACHE_TTL + timedelta(seconds=1)) is None


def test_put_falsy_ignored():
    # อย่า cache ผลว่าง — fetch ล้มชั่วคราวต้องลองใหม่ได้ ไม่ใช่ค้าง 60 นาที
    put("k", None, now=T0)
    put("k2", [], now=T0)
    assert get("k", now=T0) is None
    assert get("k2", now=T0) is None


def test_get_returns_copy_of_list():
    put("k", [{"close": 1.0}], now=T0)
    got = get("k", now=T0)
    got.append("junk")
    assert get("k", now=T0) == [{"close": 1.0}]


def test_cached_fetches_once_then_serves_from_cache():
    calls = []

    def fetch():
        calls.append(1)
        return [{"close": 1.0}]

    assert cached("k", fetch, now=T0) == [{"close": 1.0}]
    assert cached("k", fetch, now=T0 + timedelta(minutes=5)) == [{"close": 1.0}]
    assert len(calls) == 1


def test_cached_does_not_cache_falsy_result():
    calls = []

    def fetch():
        calls.append(1)
        return None

    assert cached("k", fetch, now=T0) is None
    assert cached("k", fetch, now=T0) is None
    assert len(calls) == 2


def test_clear_empties_cache():
    put("k", [1], now=T0)
    clear()
    assert get("k", now=T0) is None
