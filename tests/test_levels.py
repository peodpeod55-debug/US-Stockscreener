from datetime import date, timedelta

from bot.levels import compute_levels, positive_reaction


def make_prices(n=120, start_price=100.0):
    """สร้าง daily bars ย้อนหลัง n วันทำการ (จบที่ 2026-08-19) ราคาขึ้นวันละ 2.0

    step 2.0 > high offset 1.0 เพื่อให้ close ของแต่ละวันสูงกว่า high ของทุกวันก่อนหน้า
    (ซีรีส์ new-high ต่อเนื่อง ใช้ทดสอบ new_high_count)
    """
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
            price -= 2.0  # ย้อนหลัง = ราคาลดลง (มองไปข้างหน้าคือขึ้น)
        d -= timedelta(days=1)
    return bars  # most-recent-first


def test_compute_levels_basic():
    bars = make_prices()
    # งบ AMC วันที่ index 3 → D0 = index 2
    earnings_date = bars[3]["date"]
    lv = compute_levels(bars, earnings_date, "amc")
    assert lv is not None
    assert lv["reaction_date"] == bars[2]["date"]
    assert lv["price"] == bars[0]["close"]
    # high 5 วันก่อน D0 = max high ของ index 3..7
    assert lv["high_5d"] == max(b["high"] for b in bars[3:8])
    # high 3 เดือน (63 วัน) ก่อน D0 = max high ของ index 3..65
    assert lv["high_3m"] == max(b["high"] for b in bars[3:66])
    # SL = low ของ D0
    assert lv["sl"] == bars[2]["low"]
    assert lv["sl_pct"] > 0
    assert lv["vol_ratio"] == 1.0


def test_compute_levels_bmo_reaction_is_earnings_date():
    bars = make_prices()
    earnings_date = bars[2]["date"]
    lv = compute_levels(bars, earnings_date, "bmo")
    assert lv["reaction_date"] == earnings_date


def test_compute_levels_missing_date_returns_none():
    bars = make_prices()
    assert compute_levels(bars, "1999-01-01", "amc") is None


# ── ยาม D0: แท่งวันตอบรับหายจากซีรีส์ ห้ามเลื่อนไปใช้วันถัดไปเงียบ ๆ ──
# เคสจริง 2026-08-28: Yahoo ส่งแท่งศุกร์ close=null ทั้งตลาด ถ้าแท่งหายถาวร
# งบ พฤ AMC จะได้ D0 = จันทร์ → reaction/vol/SL ผิดหมดโดยไม่มีใครรู้

def test_compute_levels_weekend_gap_still_ok():
    # ศุกร์ 2026-08-14 AMC → D0 = จันทร์ 17 ห่าง 3 วันปฏิทิน (ขอบบนที่ต้องผ่าน)
    lv = compute_levels(make_prices(), "2026-08-14", "amc")
    assert lv is not None
    assert lv["reaction_date"] == "2026-08-17"


def test_compute_levels_rejects_d0_when_reaction_bar_missing():
    # งบ พฤ 2026-08-13 AMC แต่แท่งศุกร์ 14 หาย → D0 ที่หาได้คือจันทร์ (ห่าง 4 วัน)
    # ต้องคืน None (ไปเข้า pending "waiting" ให้มองเห็น) ไม่ใช่คำนวณจากวันผิด
    bars = [b for b in make_prices() if b["date"] != "2026-08-14"]
    assert compute_levels(bars, "2026-08-13", "amc") is None


def test_new_high_count_uptrend():
    # ซีรีส์ราคาขึ้นตลอด → ทุกวันใน 10 วันล่าสุดเป็น new 3M high
    bars = make_prices()
    earnings_date = bars[5]["date"]
    lv = compute_levels(bars, earnings_date, "amc")
    assert lv["new_high_count_10d"] == 10


def test_prev_week_high_present():
    bars = make_prices()
    lv = compute_levels(bars, bars[3]["date"], "amc")
    # 2026-08-19 คือวันพุธ → สัปดาห์ก่อน = 10–14 ส.ค.
    assert lv["prev_week_high"] is not None
    assert isinstance(lv["broke_prev_week_high"], bool)


def test_compute_levels_reaction_pct_and_direction():
    """reaction_pct = ปิด D0 เทียบปิดวันก่อน · positive_reaction ใช้กรองทิศทาง"""
    bars = make_prices()
    lv = compute_levels(bars, bars[3]["date"], "amc")    # D0 = index 2
    assert lv["reaction_pct"] == round((96 - 94) / 94 * 100, 2)
    assert positive_reaction(lv) is True
    bars[2]["close"] = 90.0                               # ปิด D0 ต่ำกว่าวันก่อน
    lv = compute_levels(bars, bars[3]["date"], "amc")
    assert lv["reaction_pct"] < 0
    assert positive_reaction(lv) is False
    assert positive_reaction(None) is False
    assert positive_reaction({"reaction_pct": None}) is False
    assert positive_reaction({"reaction_pct": 0.0}) is False
