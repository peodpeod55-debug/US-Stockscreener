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
        indicators = r0.get("indicators") or {}
        quote = (indicators.get("quote") or [{}])[0]
        series = [quote.get(k) or [] for k in
                  ("open", "high", "low", "close", "volume")]
        adj = (indicators.get("adjclose") or [{}])[0].get("adjclose") or []
        # ราคา meta ใช้กู้ close ได้เฉพาะแท่งของวันเดียวกับ regularMarketTime
        # (ระหว่างตลาดเปิดมันคือราคาสด ไม่ใช่ราคาปิด — ห้ามแช่ให้วันอื่น)
        meta = r0.get("meta") or {}
        mt = meta.get("regularMarketTime")
        meta_date = (datetime.fromtimestamp(mt, tz=timezone.utc).date().isoformat()
                     if isinstance(mt, (int, float)) else None)
        meta_price = meta.get("regularMarketPrice")
        bars = []
        for i, t in enumerate(ts):
            o, h, lo, c, v = [s[i] if i < len(s) else None for s in series]
            # timestamp คือเวลาเปิดตลาด ET → วันที่ UTC ตรงกับวันซื้อขายเสมอ
            bar_date = datetime.fromtimestamp(t, tz=timezone.utc).date().isoformat()
            if c is None and None not in (o, h, lo, v):
                # Yahoo บางวันส่งแท่งที่ o/h/l/v ครบแต่ close=null (เจอจริงทั้งตลาด
                # 2026-08-28) — กู้จาก adjclose ก่อน ไม่มีก็ใช้ราคา meta วันเดียวกัน
                # ค่าที่กู้ต้องอยู่ในช่วง [low, high] ของแท่งนั้น ไม่งั้นทิ้งตามเดิม
                cand = adj[i] if i < len(adj) else None
                if cand is None and bar_date == meta_date:
                    cand = meta_price
                if cand is not None and lo <= cand <= h:
                    c = cand
            if None in (o, h, lo, c, v):
                continue  # วันหยุด/แท่งพัง Yahoo ใส่ null มา
            bars.append({
                "date": bar_date,
                "open": float(o), "high": float(h), "low": float(lo),
                "close": float(c), "volume": int(v),
            })
    except Exception:
        return None
    if not bars:
        return None
    bars.reverse()  # Yahoo ให้ oldest-first → กลับเป็น convention เดียวกับ FMP
    return bars[:days]
