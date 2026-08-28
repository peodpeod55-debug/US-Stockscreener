"""แหล่งราคารวมศูนย์: cache → Yahoo (หลัก) → FMP (สำรอง) + prefetch ขนาน

FMP แผนฟรีตอบ 402 กับหุ้นเกือบทั้ง universe (28 ส.ค. 19/21 ตัว) — Yahoo จึงเป็นหลัก
FMP เหลือเป็นสำรองตอน Yahoo ล้ม · ธง saw_402 บน client ไม่ thread-safe → FMP ต้องเรียกทีละตัว
"""
import threading
import time

from bot import fetch_cache
from bot.prices import get_prices, prefetch

BARS = [{"date": "2026-08-27", "open": 1, "high": 2, "low": 0.5, "close": 1.5,
         "volume": 100}]


class FakeFMP:
    def __init__(self, prices=None, blocked=False):
        self._prices = prices
        self._blocked = blocked
        self.calls = []
        self.saw_402 = False
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def get_historical_prices(self, symbol, days=250):
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.02)
        with self._lock:
            self.active -= 1
        self.calls.append((symbol, days))
        if self._blocked:
            self.saw_402 = True
            return None
        return self._prices


def _yahoo(bars, calls=None, delay=0.0, fail_for=()):
    def fn(symbol, days=250):
        if calls is not None:
            calls.append((symbol, days))
        if delay:
            time.sleep(delay)
        if symbol in fail_for:
            raise RuntimeError("boom")
        return bars
    return fn


def test_get_prices_uses_yahoo_first_and_caches():
    calls = []
    client = FakeFMP(prices=[{"date": "fmp"}])
    p1 = get_prices("NVDA", 250, client=client, yahoo_fn=_yahoo(BARS, calls))
    p2 = get_prices("NVDA", 250, client=client, yahoo_fn=_yahoo(BARS, calls))
    assert p1 == BARS and p2 == BARS
    assert calls == [("NVDA", 250)]          # ครั้งที่สองมาจาก cache
    assert client.calls == []                 # Yahoo มีข้อมูล → ไม่แตะ FMP


def test_get_prices_falls_back_to_fmp_when_yahoo_empty():
    client = FakeFMP(prices=BARS)
    p = get_prices("HD", 250, client=client, yahoo_fn=_yahoo(None))
    assert p == BARS
    assert client.calls == [("HD", 250)]
    assert fetch_cache.get(("prices", "HD", 250)) == BARS


def test_get_prices_yahoo_exception_falls_back_to_fmp():
    client = FakeFMP(prices=BARS)
    p = get_prices("HD", 250, client=client,
                   yahoo_fn=_yahoo(None, fail_for=("HD",)))
    assert p == BARS


def test_get_prices_returns_none_when_no_source_has_data():
    client = FakeFMP(prices=None, blocked=True)
    assert get_prices("XXXX", 250, client=client, yahoo_fn=_yahoo(None)) is None
    assert fetch_cache.get(("prices", "XXXX", 250)) is None   # ค่าว่างไม่ cache


def test_get_prices_without_client_skips_fmp():
    assert get_prices("HD", 250, client=None, yahoo_fn=_yahoo(None)) is None


def test_get_prices_resets_saw_402_before_fmp_call():
    client = FakeFMP(prices=BARS)
    client.saw_402 = True  # ค้างจากตัวก่อนหน้า
    get_prices("HD", 250, client=client, yahoo_fn=_yahoo(None))
    assert client.saw_402 is False


def test_prefetch_warms_cache_in_parallel():
    calls = []
    syms = [f"S{i}" for i in range(8)]
    t0 = time.perf_counter()
    prefetch(syms, 250, client=None, workers=4,
             yahoo_fn=_yahoo(BARS, calls, delay=0.1))
    elapsed = time.perf_counter() - t0
    assert sorted(c[0] for c in calls) == syms
    assert all(fetch_cache.get(("prices", s, 250)) == BARS for s in syms)
    assert elapsed < 0.5                      # ทีละตัว = 0.8 วิ


def test_prefetch_skips_symbols_already_cached():
    fetch_cache.put(("prices", "A", 250), BARS)
    calls = []
    prefetch(["A", "B", "A"], 250, client=None, yahoo_fn=_yahoo(BARS, calls))
    assert calls == [("B", 250)]


def test_prefetch_one_failure_does_not_stop_others():
    calls = []
    prefetch(["A", "B", "C"], 250, client=None,
             yahoo_fn=_yahoo(BARS, calls, fail_for=("B",)))
    assert fetch_cache.get(("prices", "A", 250)) == BARS
    assert fetch_cache.get(("prices", "C", 250)) == BARS
    assert fetch_cache.get(("prices", "B", 250)) is None


def test_prefetch_uses_injected_get_fn_and_caches_result():
    """ผู้เรียก (screener/lookup ในเทส) ฉีดแหล่งราคาเองได้ — ผลต้องลง cache ให้ลูปถัดไป"""
    calls = []

    def source(symbol, days):
        calls.append((symbol, days))
        return BARS

    prefetch(["A", "B"], 250, get_fn=source)
    assert sorted(calls) == [("A", 250), ("B", 250)]
    assert fetch_cache.get(("prices", "A", 250)) == BARS
    assert fetch_cache.get(("prices", "B", 250)) == BARS


def test_prefetch_serializes_fmp_fallback_calls():
    """ธง saw_402 อยู่บน client ตัวเดียว — FMP ห้ามถูกเรียกซ้อนจากหลาย thread"""
    client = FakeFMP(prices=BARS)
    prefetch([f"S{i}" for i in range(6)], 250, client=client, workers=4,
             yahoo_fn=_yahoo(None))
    assert len(client.calls) == 6
    assert client.max_active == 1
