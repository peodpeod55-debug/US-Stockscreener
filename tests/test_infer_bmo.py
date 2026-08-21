"""infer_bmo: เดา BMO จากแท่งวันงบ (gap แรง AND วอลุ่มพุ่ง) เมื่อปฏิทินตอบ unknown"""
from datetime import date, timedelta

from bot.levels import infer_bmo


def make_prices(n=60, start_price=100.0):
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


def test_infer_bmo_gap_and_volume_spike():
    bars = make_prices()
    prev_close = bars[1]["close"]
    bars[0]["open"] = prev_close * 0.92     # gap -8%
    bars[0]["volume"] = 3_000_000           # 3x avg
    assert infer_bmo(bars, bars[0]["date"]) is True


def test_infer_bmo_quiet_bar():
    bars = make_prices()                    # gap ~2% วอลุ่มปกติ
    assert infer_bmo(bars, bars[0]["date"]) is False


def test_infer_bmo_gap_without_volume():
    bars = make_prices()
    bars[0]["open"] = bars[1]["close"] * 0.92
    assert infer_bmo(bars, bars[0]["date"]) is False


def test_infer_bmo_volume_without_gap():
    bars = make_prices()
    bars[0]["open"] = bars[1]["close"]      # ไม่มี gap
    bars[0]["volume"] = 5_000_000
    assert infer_bmo(bars, bars[0]["date"]) is False


def test_infer_bmo_date_not_in_prices():
    bars = make_prices()
    assert infer_bmo(bars, "2020-01-01") is False


def test_infer_bmo_no_previous_bar():
    bars = make_prices()
    assert infer_bmo(bars, bars[-1]["date"]) is False


def test_infer_bmo_insufficient_volume_history():
    """แท่งก่อนวันงบน้อยกว่า 10 แท่ง — ฐานวอลุ่มไม่พอ ห้ามเดา"""
    bars = make_prices(n=8)
    bars[0]["open"] = bars[1]["close"] * 0.92
    bars[0]["volume"] = 5_000_000
    assert infer_bmo(bars, bars[0]["date"]) is False
