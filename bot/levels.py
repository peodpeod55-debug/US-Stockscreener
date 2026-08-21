"""คำนวณระดับราคา (levels) สืบทอดจาก SET Earnings Breakout Screener

daily_prices ทุกฟังก์ชัน = list[dict] most-recent-first
คีย์: date, open, high, low, close, volume
"""
from datetime import date, timedelta


def _find_index(daily_prices, target_date):
    for i, bar in enumerate(daily_prices):
        if bar.get("date") == target_date:
            return i
    return -1


def _pct_vs(price, level):
    if not level:
        return None
    return round((price - level) / level * 100, 2)


def detect_new_breaks(daily_prices, levels):
    """level ที่ "เพิ่งทะลุ": ปิดล่าสุดเหนือแนว แต่ปิดวันก่อนหน้ายังไม่เหนือ

    คืน list จาก ("high_5d", "high_3m") — นิยามนี้กันเตือนซ้ำทุกวันที่ยืนเหนือแนว
    """
    if not levels or not daily_prices or len(daily_prices) < 2:
        return []
    close = daily_prices[0]["close"]
    prev = daily_prices[1]["close"]
    return [k for k in ("high_5d", "high_3m")
            if levels.get(k) is not None and prev <= levels[k] < close]


def detect_sl_break(daily_prices, levels):
    """SL ที่ "เพิ่งหลุด": low ล่าสุดต่ำกว่า SL แต่ low วันก่อนหน้ายังไม่หลุด

    นิยาม low < sl เดียวกับ sl_hit ใน weekly — self-dedup ไม่เตือนซ้ำทุกวันที่อยู่ใต้แนว
    """
    if not levels or not daily_prices or len(daily_prices) < 2:
        return False
    sl = levels.get("sl")
    if sl is None:
        return False
    return daily_prices[0]["low"] < sl <= daily_prices[1]["low"]


def detect_low_break(daily_prices, levels):
    """Low 5 วันก่อนงบที่ "เพิ่งหลุด" — หลุดแนวนี้ = คายการตอบรับงบทั้งก้อน setup จบ

    self-dedup แบบเดียวกับ detect_sl_break (low ข้ามแนวลงเฉพาะวันแรก)
    """
    if not levels or not daily_prices or len(daily_prices) < 2:
        return False
    low = levels.get("low_5d")
    if low is None:
        return False
    return daily_prices[0]["low"] < low <= daily_prices[1]["low"]


def below_low_5d(levels):
    """สถานะ "ปิดต่ำกว่า low 5 วันก่อนงบ" — ใช้ตัดสินเอาหุ้นออกจาก auto-watch

    เทียบ close ตรงๆ (ไม่ใช่ pct ที่ปัดเศษ) และเป็น state ไม่ใช่ edge:
    หุ้นที่หลุดไปแล้วหลายวัน (บอทไม่ได้เห็นวันข้าม) ก็ยังถูกเก็บกวาดออก
    """
    if not levels:
        return False
    low = levels.get("low_5d")
    price = levels.get("price")
    if low is None or price is None:
        return False
    return price < low


def compute_levels(daily_prices, earnings_date, timing):
    """คืน dict ระดับราคา หรือ None ถ้าหา reaction day (D0) ไม่ได้

    D0: bmo → วันประกาศงบ, amc/unknown → วันซื้อขายถัดไป
    (convention เดียวกับ gap_size_calculator)
    """
    earn_idx = _find_index(daily_prices, earnings_date)
    if earn_idx == -1:
        return None

    d0 = earn_idx if (timing or "").lower() == "bmo" else earn_idx - 1
    if d0 < 0:
        return None  # งบ AMC เพิ่งออก ยังไม่มีวันตอบรับในข้อมูล

    price = daily_prices[0]["close"]
    pre = daily_prices[d0 + 1:]  # ทุกวันก่อน D0

    high_5d = max((b["high"] for b in pre[:5]), default=None)
    high_3m = max((b["high"] for b in pre[:63]), default=None)
    low_5d = min((b["low"] for b in pre[:5]), default=None)

    # สัปดาห์ (จ–ศ) ที่จบล่าสุดก่อนสัปดาห์ของ bar ล่าสุด
    last_d = date.fromisoformat(daily_prices[0]["date"])
    prev_week = (last_d - timedelta(days=7)).isocalendar()[:2]
    prev_week_high = max(
        (b["high"] for b in daily_prices
         if date.fromisoformat(b["date"]).isocalendar()[:2] == prev_week),
        default=None,
    )

    # ความถี่ทำไฮใหม่: วันใน 10 วันล่าสุดที่ close > max high ของ 63 วันก่อนหน้าวันนั้น
    new_high_count = 0
    for i in range(min(10, len(daily_prices))):
        prior = daily_prices[i + 1: i + 64]
        if len(prior) >= 20 and daily_prices[i]["close"] > max(b["high"] for b in prior):
            new_high_count += 1

    sl = daily_prices[d0]["low"]
    sl_pct = round((price - sl) / price * 100, 2) if price else None

    vols = [b["volume"] for b in pre[:20]]
    avg20 = sum(vols) / len(vols) if vols else 0
    vol_ratio = round(daily_prices[d0]["volume"] / avg20, 2) if avg20 else None

    return {
        "reaction_date": daily_prices[d0]["date"],
        "price": round(price, 2),
        "high_5d": high_5d,
        "pct_vs_high_5d": _pct_vs(price, high_5d),
        "high_3m": high_3m,
        "pct_vs_high_3m": _pct_vs(price, high_3m),
        "low_5d": low_5d,
        "pct_vs_low_5d": _pct_vs(price, low_5d),
        "prev_week_high": prev_week_high,
        "broke_prev_week_high": (price > prev_week_high) if prev_week_high else None,
        "new_high_count_10d": new_high_count,
        "sl": sl,
        "sl_pct": sl_pct,
        "vol_ratio": vol_ratio,
    }
