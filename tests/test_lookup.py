from datetime import date, timedelta

from bot.formatter import format_lookup
from bot.lookup import (
    LOOKUP_MAX,
    SET_RULE,
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


def test_lookup_symbol_no_price_source_returns_none():
    """Yahoo (ปิดในเทส) ว่าง + FMP 402 → None เหมือน "ไม่พบข้อมูล" (ไม่มี exception แยกแล้ว)"""
    class BlockedClient(FakeClient):
        def get_historical_prices(self, symbol, days=250):
            self.saw_402 = True
            return None

    assert lookup_symbol(BlockedClient(None), "HD", {}, today=TODAY) is None


def test_lookup_symbol_uses_injected_price_source():
    """get_prices_fn มีราคา → ได้ snapshot แม้ FMP 402 · ไม่แตะ client"""
    class BlockedClient(FakeClient):
        def get_historical_prices(self, symbol, days=250):
            raise AssertionError("must not call FMP when source has data")

    calls = []

    def source(symbol, days):
        calls.append((symbol, days))
        return make_prices(30)

    s = lookup_symbol(BlockedClient(None), "HD", {}, today=TODAY,
                      get_prices_fn=source)
    assert calls == [("HD", 250)]
    assert s is not None and s["symbol"] == "HD" and s["price"] > 0


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


def test_build_snapshot_infers_bmo_from_reaction_bar():
    """FMP ไม่มี field time → timing unknown แต่แท่งวันงบ gap แรง+วอลุ่มพุ่ง
    → อนุมาน BMO: ได้ levels ทันที (D0 = วันงบ) ป้าย bmo* ไม่ค้างรอ"""
    prices = make_prices()
    prev_close = prices[1]["close"]
    prices[0]["open"] = prev_close * 0.93     # gap -7%
    prices[0]["close"] = prev_close * 0.91
    prices[0]["low"] = prev_close * 0.90
    prices[0]["volume"] = 4_000_000
    last_date = prices[0]["date"]
    earnings = [{"date": last_date}]          # ไม่มี time (เหมือน stable API จริง)
    snap = build_snapshot("WMT", prices, earnings=earnings,
                          today=date.fromisoformat(last_date))
    assert snap["timing"] == "bmo*"
    assert snap["pending_reaction"] is False
    assert snap["levels"] is not None
    assert snap["levels"]["reaction_date"] == last_date
    assert snap["reaction_pct"] is not None


def test_build_snapshot_quiet_unknown_still_waits():
    """timing unknown + แท่งวันงบเงียบ → ห้ามเดา ยังคงรอวันตอบรับตาม convention เดิม"""
    prices = make_prices()
    last_date = prices[0]["date"]
    earnings = [{"date": last_date}]
    snap = build_snapshot("AAPL", prices, earnings=earnings,
                          today=date.fromisoformat(last_date))
    assert snap["timing"] == "unknown"
    assert snap["pending_reaction"] is True
    assert snap["levels"] is None


def test_snapshot_negative_reaction_not_graded():
    """วันตอบรับปิดลบ → มี levels (แนว/SL ยังมีประโยชน์) แต่ไม่ให้เกรด
    (เกณฑ์เดียวกับ screener — 5-factor ให้คะแนน |gap| ไม่สนทิศ) + formatter บอกเหตุผล"""
    bars = make_prices(120)
    earn_date = bars[5]["date"]                    # AMC → D0 = index 4
    bars[4].update({"open": 89.0, "high": 89.5, "low": 87.0, "close": 88.0})
    s = build_snapshot("TEST", bars, earnings=[{"date": earn_date, "time": "amc"}],
                       today=TODAY)
    assert s["levels"] is not None
    assert s["levels"]["reaction_pct"] < 0
    assert s["grade"] is None and s["score"] is None
    text = format_lookup(s)
    assert "ตอบรับลบ" in text and "เกรด" not in text


# ── เกณฑ์ SET ใน snapshot (คะแนน 0-15 ⭐ แบบบอทไทย — bot.set_score, สูตรไม่แตะ) ──

def _d0_pop(bars, close=99.0, high=101.0, low=95.0, volume=3_000_000):
    """งบ AMC ที่ bars[5] → D0 = bars[4]: ปิด +10% (90 → 99) · vol 3× ฐาน 1M · หลังจากนั้น 94/96/98/100 ตามซีรีส์"""
    bars[4] = {**bars[4], "close": close, "high": high, "low": low, "volume": volume}
    return bars


def _amc_at(bars, i=5):
    return [{"date": bars[i]["date"], "time": "amc"}]


def test_snapshot_set_score_for_recent_earnings():
    bars = _d0_pop(make_prices(120))
    s = build_snapshot("TEST", bars, earnings=_amc_at(bars), today=TODAY)
    st = s["set"]
    # ปฏิกิริยา +10%/3× = 4 · H5d 1 + H3m 3 · ไฮใหม่วันล่าสุด 2 · ความถี่ยังวัดไม่ได้ (4 วัน) · สัปดาห์ไม่ยก · เหนือ low 1 = 11
    assert st["pts"] == 11 and st["stars"] == "⭐⭐" and st["post_days"] == 4
    assert st["ret_d0_pct"] == 10.0 and st["vol_ratio"] == 3.0 and st["hit"] is True
    assert st["turnover_d0"] == 99.0 * 3_000_000
    assert st["pre5d_high"] == 91.0 and st["pre_low"] == 81.0 and st["weeks_observed"] == 2
    assert s["set_rule"] == SET_RULE == {"min_ret_pct": 2.0, "min_vol_ratio": 1.5}


def test_snapshot_set_gate_miss_keeps_score():
    """ปิด +2.2% แต่ vol 1.0× → ตกด่านเข้า (hit False) แต่คะแนนยังโชว์เหมือน lookup ของบอทไทย"""
    bars = make_prices(120)
    s = build_snapshot("TEST", bars, earnings=_amc_at(bars), today=TODAY)
    st = s["set"]
    assert st["hit"] is False and round(st["ret_d0_pct"], 2) == 2.22 and st["vol_ratio"] == 1.0
    assert st["pts"] == 8 and st["stars"] == "⭐"       # H5d 1 + H3m 3 + ไฮใหม่สด 2 + สัปดาห์↑1 1 + เหนือ low 1
    assert st["weekly_hh_streak"] == 1 and st["above_pre_low"] is True


def test_snapshot_set_none_without_levels():
    assert build_snapshot("TEST", flat_prices(30), earnings=None, today=TODAY)["set"] is None
    bars = make_prices(250)
    old = build_snapshot("TEST", bars, earnings=[{"date": bars[80]["date"]}], today=TODAY)
    assert old["levels"] is None and old["set"] is None and old["set_rule"] is None
    bars = make_prices(120)
    pending = build_snapshot("TEST", bars, earnings=_amc_at(bars, 0), today=TODAY)
    assert pending["pending_reaction"] and pending["set"] is None


# ── format_lookup: บล็อก 🇹🇭 เกณฑ์ SET (หน้าตาเดียวกับบอทไทย / HK) ─────────

def _set_block(**over):
    s = {"pts": 11, "stars": "⭐⭐", "ret_d0_pct": 5.9, "vol_ratio": 4.77, "since_pct": 8.17, "price": 316.83,
         "broke_5d": True, "broke_3m": True, "days_since_new_high": 0, "new_high_ratio": None, "new_high_days": 2,
         "post_days": 3, "weekly_hh_streak": 0, "weeks_observed": 1, "pre_low": 302.5, "above_pre_low": True,
         "pct_above_pre_low": 4.74, "pre5d_high": 310.2, "pre3m_high": 325.0, "hit": True, "turnover_d0": 2.0e9}
    s.update(over)
    return s


def test_format_lookup_set_block_thai_style():
    msg = format_lookup(make_snapshot(reaction_pct=5.9, set=_set_block(), set_rule=SET_RULE))
    assert "วันตอบรับงบ: +5.9% (วอลุ่ม 4.8x 🔥)" in msg
    assert "🇹🇭 เกณฑ์ SET   [⭐⭐ 11/15 · D+3 · ผ่านด่านเข้า ✅]" in msg
    assert "• ไฮ 5 วันก่อนงบ: 310.20  ✅ ผ่านแล้ว" in msg and "• ไฮ 3 ด. ก่อนงบ: 325.00  ✅ ทะลุแล้ว" in msg
    assert "• ไฮใหม่ล่าสุด: วันนี้ 🔥" in msg
    assert "• ความถี่ไฮใหม่: ยังวัดไม่ได้ (มี 3 วันหลังงบ ต้อง ≥5)" in msg
    assert "ไฮรายสัปดาห์" not in msg                                    # weeks_observed < 2 → ไม่โชว์ (เหมือนบอทไทย)
    assert "• Low ก่อนงบ: 302.50  ✅ ยังเหนือ (+4.7%)" in msg
    assert msg.index("📌 สัญญาณหลังงบ") < msg.index("🇹🇭 เกณฑ์ SET") < msg.index("📅 High/Low 5 วัน")


def test_format_lookup_set_block_continuity_and_miss():
    st = _set_block(pts=4, stars="", ret_d0_pct=1.2, vol_ratio=1.1, broke_5d=False, broke_3m=False,
                    days_since_new_high=3, new_high_ratio=0.4, new_high_days=4, post_days=10,
                    weekly_hh_streak=2, weeks_observed=3, above_pre_low=False, pct_above_pre_low=-2.1, hit=False)
    msg = format_lookup(make_snapshot(reaction_pct=1.2, set=st, set_rule=SET_RULE))
    assert "วันตอบรับงบ: +1.2% (วอลุ่ม 1.1x)" in msg
    assert "🇹🇭 เกณฑ์ SET   [4/15 · D+10 · ด่านเข้า ✗ ปิด < +2%]" in msg
    assert "• ไฮ 5 วันก่อนงบ: 310.20  ยังไม่ผ่าน" in msg and "• ไฮ 3 ด. ก่อนงบ: 325.00  ยังไม่ผ่าน" in msg
    assert "• ไฮใหม่ล่าสุด: 3 วันทำการก่อน" in msg
    assert "• ความถี่ไฮใหม่: 4/10 วันหลังงบ (40%)" in msg
    assert "• ไฮรายสัปดาห์: ยกขึ้น 2 สัปดาห์ติด 🔥" in msg
    assert "• Low ก่อนงบ: 302.50  ⛔ หลุดแล้ว (-2.1%)" in msg
    no_streak = format_lookup(make_snapshot(set=_set_block(weekly_hh_streak=0, weeks_observed=2), set_rule=SET_RULE))
    assert "• ไฮรายสัปดาห์: สัปดาห์นี้ยังไม่ยกขึ้น" in no_streak
    vol_miss = format_lookup(make_snapshot(set=_set_block(ret_d0_pct=3.0, vol_ratio=1.1, hit=False), set_rule=SET_RULE))
    assert "ด่านเข้า ✗ vol < 1.5×" in vol_miss


def test_format_lookup_set_block_after_signals_before_highs():
    msg = format_lookup(make_snapshot(set=_set_block(), set_rule=SET_RULE))
    i_sig, i_set, i_hi = msg.index("📌 สัญญาณหลังงบ"), msg.index("🇹🇭 เกณฑ์ SET"), msg.index("📅 High/Low 5 วัน")
    assert i_sig < msg.index("🛑 SL") < i_set < i_hi


def test_format_lookup_without_set_block():
    msg = format_lookup(make_snapshot())
    assert "เกณฑ์ SET" not in msg and "วันตอบรับงบ: +5.1%" in msg
    assert "เกณฑ์ SET" not in format_lookup(make_snapshot(set=None, set_rule=None))


def test_format_lookup_sl_line_when_price_below_sl():
    """ราคาต่ำกว่า SL → sl_pct ติดลบ — เดิมพิมพ์ "(--4.07%)" """
    s = make_snapshot()
    s["levels"] = {**s["levels"], "sl": 320.0, "sl_pct": -4.07}
    msg = format_lookup(s)
    assert "🛑 SL (low วันงบ): 320.00  (⛔ ต่ำกว่า SL 4.07%)" in msg and "--" not in msg
    assert "🛑 SL (low วันงบ): 302.50  (-4.5%)" in format_lookup(make_snapshot())
