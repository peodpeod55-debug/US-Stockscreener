from datetime import date, timedelta

import pytest

from bot.formatter import format_lookup
from bot.lookup import (
    LOOKUP_MAX,
    SymbolNotCovered,
    build_snapshot,
    lookup_symbol,
    parse_tickers,
)


# ── helpers ──────────────────────────────────────────────────────

def make_prices(n=120, start_price=100.0):
    """ซีรีส์ขาขึ้น (เหมือน test_levels): จบ 2026-08-19 ราคาขึ้นวันละ 2.0"""
    bars = []
    d = date(2026, 8, 19)
    price = start_price
    while len(bars) < n:
        if d.weekday() < 5:
            bars.append({
                "date": d.isoformat(),
                "open": price, "high": price + 1.0, "low": price - 1.0,
                "close": price, "volume": 1_000_000,
            })
            price -= 2.0
        d -= timedelta(days=1)
    return bars  # most-recent-first


def flat_prices(n=30):
    """แท่งราคานิ่งๆ ปิด 100 วอลุ่ม 1M — ไว้เช็คสูตรเลขแบบตายตัว"""
    bars = []
    d = date(2026, 8, 19)
    while len(bars) < n:
        if d.weekday() < 5:
            bars.append({
                "date": d.isoformat(),
                "open": 100.0, "high": 101.0, "low": 99.0,
                "close": 100.0, "volume": 1_000_000,
            })
        d -= timedelta(days=1)
    return bars


TODAY = date(2026, 8, 20)


# ── parse_tickers ────────────────────────────────────────────────

def test_parse_tickers_basic():
    assert parse_tickers("nvda") == ["NVDA"]
    assert parse_tickers("NVDA tsla AAPL") == ["NVDA", "TSLA", "AAPL"]


def test_parse_tickers_dot_and_dash():
    assert parse_tickers("BRK.B bf-b") == ["BRK.B", "BF-B"]


def test_parse_tickers_filters_junk():
    # คำไทย/ตัวเลขล้วน ไม่ใช่ ticker
    assert parse_tickers("ซื้อ NVDA 32.50") == ["NVDA"]
    assert parse_tickers("สวัสดีครับ") == []
    assert parse_tickers("") == []


def test_parse_tickers_dedupe_and_cap():
    assert parse_tickers("AAPL aapl AAPL") == ["AAPL"]
    many = " ".join(f"SYM{i}" for i in range(10))
    assert len(parse_tickers(many)) == LOOKUP_MAX


# ── build_snapshot: ราคาพื้นฐาน ──────────────────────────────────

def test_snapshot_price_fields():
    bars = flat_prices(30)
    # วันล่าสุด: เปิด 102 ปิด 105 วอลุ่ม 3M (ที่เหลือปิด 100 วอลุ่ม 1M)
    bars[0] = {**bars[0], "open": 102.0, "high": 106.0, "low": 101.0,
               "close": 105.0, "volume": 3_000_000}
    s = build_snapshot("TEST", bars, today=TODAY)
    assert s["symbol"] == "TEST"
    assert s["price"] == 105.0
    assert s["last_date"] == bars[0]["date"]
    assert round(s["day_change_pct"], 2) == 5.0       # 105 vs 100
    assert round(s["gap_pct"], 2) == 2.0              # เปิด 102 vs ปิดก่อน 100
    assert round(s["intraday_pct"], 2) == 2.94        # 105 vs 102
    assert round(s["chg_5d_pct"], 2) == 5.0           # vs close[5]=100
    assert round(s["chg_1m_pct"], 2) == 5.0           # vs close[21]=100
    assert s["vol_ratio"] == 3.0                      # 3M / เฉลี่ย 1M (20 วันก่อนหน้า)
    assert s["hi_5d"] == 106.0
    assert s["lo_5d"] == 99.0
    assert s["hi_3m"] == 106.0


def test_snapshot_52w_needs_history():
    s_short = build_snapshot("TEST", flat_prices(120), today=TODAY)
    assert s_short["hi_52w"] is None and s_short["lo_52w"] is None
    s_full = build_snapshot("TEST", make_prices(250), today=TODAY)
    assert s_full["hi_52w"] is not None and s_full["lo_52w"] is not None


def test_snapshot_meta_from_universe():
    meta = {"name": "NVIDIA Corp", "dr_symbols": "NVDA80", "sector": "Tech"}
    s = build_snapshot("NVDA", flat_prices(30), meta=meta, today=TODAY)
    assert s["name"] == "NVIDIA Corp"
    assert s["dr_symbols"] == "NVDA80"
    s2 = build_snapshot("NVDA", flat_prices(30), today=TODAY)
    assert s2["name"] == "NVDA" and s2["dr_symbols"] == ""


# ── build_snapshot: วันงบ + สัญญาณหลังงบ ─────────────────────────

def test_snapshot_earnings_recent_scored():
    bars = make_prices(120)
    earn_date = bars[5]["date"]  # งบ AMC 5 แท่งก่อน → D0 = index 4
    earnings = [
        {"date": "2026-11-05", "time": "amc"},
        {"date": earn_date, "time": "amc"},
        {"date": "2026-05-10", "time": "amc"},
    ]
    s = build_snapshot("TEST", bars, earnings=earnings, today=TODAY)
    assert s["last_earnings"] == earn_date
    assert s["next_earnings"] == "2026-11-05"
    assert s["days_to_earnings"] == 77
    assert s["days_since_earnings"] == (TODAY - date.fromisoformat(earn_date)).days
    # close[5]=90 → close[4]=92 → close[0]=100
    assert round(s["reaction_pct"], 2) == 2.22        # 92 vs 90
    assert round(s["since_earnings_pct"], 2) == 11.11  # 100 vs 90
    assert s["levels"] is not None
    assert s["levels"]["sl"] == bars[4]["low"]
    assert s["grade"] in "ABCD"
    assert isinstance(s["score"], (int, float))
    assert s["pending_reaction"] is False


def test_snapshot_old_earnings_no_levels():
    bars = make_prices(250)
    earn_date = bars[80]["date"]  # ~112+ วันปฏิทินก่อน → เกิน 60 วัน
    s = build_snapshot("TEST", bars, earnings=[{"date": earn_date}], today=TODAY)
    assert s["days_since_earnings"] > 60
    assert s["levels"] is None
    assert s["grade"] is None
    assert s["pending_reaction"] is False
    # % ตั้งแต่งบยังคำนวณให้ (มีประโยชน์แม้งบเก่า)
    assert s["since_earnings_pct"] is not None


def test_snapshot_amc_today_pending_reaction():
    bars = make_prices(120)
    # งบ AMC เมื่อคืน (วันเดียวกับแท่งล่าสุด) → ยังไม่มีวันตอบรับ
    s = build_snapshot("TEST", bars,
                       earnings=[{"date": bars[0]["date"], "time": "amc"}],
                       today=TODAY)
    assert s["last_earnings"] == bars[0]["date"]
    assert s["levels"] is None
    assert s["pending_reaction"] is True


def test_snapshot_no_earnings_data():
    s = build_snapshot("TEST", flat_prices(30), earnings=None, today=TODAY)
    assert s["last_earnings"] is None
    assert s["next_earnings"] is None
    assert s["levels"] is None
    assert s["pending_reaction"] is False


# ── lookup_symbol (fake client) ──────────────────────────────────

class FakeClient:
    def __init__(self, prices, earnings=None):
        self._prices = prices
        self._earnings = earnings

    def get_historical_prices(self, symbol, days=250):
        return self._prices

    def get_earnings_dates(self, symbol):
        return self._earnings


def test_lookup_symbol_assembles_snapshot():
    bars = make_prices(120)
    client = FakeClient(bars, [{"date": bars[5]["date"], "time": "amc"}])
    uni = {"NVDA": {"name": "NVIDIA Corp", "sector": "Tech",
                    "dr_symbols": "NVDA80"}}
    s = lookup_symbol(client, "NVDA", uni, today=TODAY)
    assert s["name"] == "NVIDIA Corp"
    assert s["dr_symbols"] == "NVDA80"
    assert s["grade"] in "ABCD"


def test_lookup_symbol_unknown_ticker_returns_none():
    assert lookup_symbol(FakeClient(None), "XXXX", {}, today=TODAY) is None
    assert lookup_symbol(FakeClient([]), "XXXX", {}, today=TODAY) is None


def test_lookup_symbol_plan_blocked_raises():
    # FMP แผนฟรีจำกัดบาง symbol (HTTP 402) — ต้องแยกจาก "ไม่พบข้อมูล"
    class BlockedClient(FakeClient):
        def get_historical_prices(self, symbol, days=250):
            self.saw_402 = True
            return None

    with pytest.raises(SymbolNotCovered):
        lookup_symbol(BlockedClient(None), "HD", {}, today=TODAY)


def test_lookup_symbol_fallback_rescues_402():
    """โดน 402 แต่แหล่งสำรองมีราคา → ได้ snapshot ไม่ raise"""
    class BlockedClient(FakeClient):
        def get_historical_prices(self, symbol, days=250):
            self.saw_402 = True
            return None

    calls = []

    def fallback(symbol, days):
        calls.append((symbol, days))
        return make_prices(30)

    s = lookup_symbol(BlockedClient(None), "HD", {}, today=TODAY,
                      fallback_prices_fn=fallback)
    assert calls == [("HD", 250)]
    assert s is not None and s["symbol"] == "HD" and s["price"] > 0


def test_lookup_symbol_raises_when_fallback_also_fails():
    class BlockedClient(FakeClient):
        def get_historical_prices(self, symbol, days=250):
            self.saw_402 = True
            return None

    with pytest.raises(SymbolNotCovered):
        lookup_symbol(BlockedClient(None), "HD", {}, today=TODAY,
                      fallback_prices_fn=lambda symbol, days: None)


def test_lookup_symbol_resets_saw_402_between_symbols():
    # client ตัวเดียวใช้หลาย symbol ในข้อความเดียว — ธง 402 ต้องไม่ค้างข้ามตัว
    bars = make_prices(30)
    client = FakeClient(bars)
    client.saw_402 = True  # ค้างจากตัวก่อนหน้า
    s = lookup_symbol(client, "NVDA", {}, today=TODAY)
    assert s is not None
    assert client.saw_402 is False


# ── format_lookup ────────────────────────────────────────────────

def make_snapshot(**over):
    s = {
        "symbol": "AAPL", "name": "Apple Inc.", "dr_symbols": "AAPL01",
        "last_date": "2026-08-19", "price": 316.83,
        "day_change_pct": 2.1, "gap_pct": 0.5, "intraday_pct": 1.6,
        "chg_5d_pct": 4.0, "chg_1m_pct": 9.9,
        "volume": 55_100_000, "vol_ratio": 2.3,
        "hi_5d": 318.0, "lo_5d": 305.0, "hi_3m": 325.0, "lo_3m": 280.0,
        "hi_52w": 340.0, "lo_52w": 210.0,
        "last_earnings": "2026-08-14", "next_earnings": "2026-11-05",
        "days_since_earnings": 5, "days_to_earnings": 77,
        "since_earnings_pct": 6.2, "reaction_pct": 5.1, "timing": "amc",
        "levels": {
            "reaction_date": "2026-08-17", "price": 316.83,
            "high_5d": 310.2, "pct_vs_high_5d": 2.1,
            "high_3m": 325.0, "pct_vs_high_3m": -2.6,
            "prev_week_high": 312.0, "broke_prev_week_high": True,
            "new_high_count_10d": 4, "sl": 302.5, "sl_pct": 4.5,
            "vol_ratio": 1.8,
        },
        "score": 88.0, "grade": "A", "pending_reaction": False,
    }
    s.update(over)
    return s


def test_format_lookup_full():
    text = format_lookup(make_snapshot())
    assert "Apple Inc." in text and "AAPL" in text
    assert "316.83" in text and "+2.1%" in text
    assert "2.3x" in text and "🔥" in text
    assert "งบล่าสุด" in text and "2026-08-14" in text
    assert "ตั้งแต่งบ" in text and "+6.2%" in text
    assert "งบถัดไป" in text and "77 วัน" in text
    assert "เกรด A" in text and "88" in text
    assert "High 5 วันก่อนงบ" in text and "✅" in text
    assert "SL" in text and "302.50" in text
    assert "52w" in text and "340.00" in text
    assert "DR: AAPL01" in text
    assert len(text) <= 3800


def test_format_lookup_no_earnings():
    text = format_lookup(make_snapshot(
        last_earnings=None, next_earnings=None, days_since_earnings=None,
        days_to_earnings=None, since_earnings_pct=None, reaction_pct=None,
        levels=None, score=None, grade=None))
    assert "งบล่าสุด" not in text
    assert "เกรด" not in text
    assert "316.83" in text


def test_format_lookup_pending_reaction():
    text = format_lookup(make_snapshot(
        levels=None, score=None, grade=None, pending_reaction=True,
        since_earnings_pct=None, reaction_pct=None))
    assert "รอวันตอบรับงบ" in text


def test_format_lookup_no_dr_line_when_absent():
    text = format_lookup(make_snapshot(dr_symbols=""))
    assert "DR:" not in text
