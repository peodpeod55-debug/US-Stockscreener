"""แหล่งราคาสำรอง (Yahoo v8 chart) — ใช้เมื่อ FMP แผนฟรีตอบ 402 กับหุ้นนอกแผน

endpoint เดียวกับที่ yfinance ใช้ข้างใต้ แต่เรียกตรงด้วย requests (ไม่ต้องลาก pandas)
ไม่ใช้ API key · คืนรูปเดียวกับ FMP: list[dict] most-recent-first
คีย์ date/open/high/low/close/volume · เป็นแหล่งเสริม: ล้มเหลวคืน None ห้าม raise
"""
from datetime import datetime, timezone

import requests

YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
# ไม่มี browser User-Agent Yahoo จะปฏิเสธ request
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
}


def fetch_yahoo_prices(symbol, days=250, get=requests.get, raw=False):
    """แท่งราคารายวันล่าสุด ≤ days แท่ง หรือ None ถ้าดึง/parse ไม่ได้

    raw=True: ใช้สัญลักษณ์ตามที่ให้มา (DR ไทย .BK / FX =X) — ไม่แปลงจุดเป็นขีด
    """
    ysym = symbol.upper() if raw else symbol.upper().replace(".", "-")  # BRK.B → BRK-B
    rng = "2y" if days > 250 else "1y"
    try:
        resp = get(YAHOO_URL.format(symbol=ysym),
                   params={"range": rng, "interval": "1d"},
                   headers=_HEADERS, timeout=15)
        if resp.status_code != 200:
            return None
        result = ((resp.json().get("chart") or {}).get("result")) or []
        if not result:
            return None
        r0 = result[0]
        ts = r0.get("timestamp") or []
        quote = ((r0.get("indicators") or {}).get("quote") or [{}])[0]
        series = [quote.get(k) or [] for k in
                  ("open", "high", "low", "close", "volume")]
        bars = []
        for i, t in enumerate(ts):
            vals = [s[i] if i < len(s) else None for s in series]
            if any(v is None for v in vals):
                continue  # วันหยุด/แท่งพัง Yahoo ใส่ null มา
            o, h, lo, c, v = vals
            # timestamp คือเวลาเปิดตลาด ET → วันที่ UTC ตรงกับวันซื้อขายเสมอ
            bars.append({
                "date": datetime.fromtimestamp(t, tz=timezone.utc)
                .date().isoformat(),
                "open": float(o), "high": float(h), "low": float(lo),
                "close": float(c), "volume": int(v),
            })
    except Exception:
        return None
    if not bars:
        return None
    bars.reverse()  # Yahoo ให้ oldest-first → กลับเป็น convention เดียวกับ FMP
    return bars[:days]
