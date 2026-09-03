"""quote สดจาก Yahoo v8 (range 1d) สำหรับ /plan และ /dr — ราคา DR ไทย (.BK) และ USDTHB=X

เดิมอยู่ใน bot/openbell.py (ถอด job ยืนยันเปิดตลาด US ออกแล้วแพ็ค B — 3 ก.ย.)
ฟังก์ชันนี้ยังใช้อยู่จริงเลยแยกมาไว้โมดูลของตัวเอง ไม่ต้องพ่วง yahoo_prices ให้ drift จาก HK
"""
import requests

from bot.yahoo_prices import YAHOO_URL, _HEADERS


def fetch_yahoo_quote(symbol, get=requests.get, raw=False):
    """quote สำรองจาก Yahoo v8 (range 1d) — คืนรูปเดียวกับ FMP หรือ None

    raw=True: ใช้สัญลักษณ์ตามที่ให้มา (DR ไทย .BK / FX =X) — ไม่แปลงจุดเป็นขีด
    """
    ysym = symbol.upper() if raw else symbol.upper().replace(".", "-")
    try:
        resp = get(YAHOO_URL.format(symbol=ysym),
                   params={"range": "1d", "interval": "1d"},
                   headers=_HEADERS, timeout=15)
        if resp.status_code != 200:
            return None
        result = ((resp.json().get("chart") or {}).get("result")) or []
        if not result:
            return None
        meta = result[0].get("meta") or {}
        quote = ((result[0].get("indicators") or {}).get("quote") or [{}])[0]
        opens = quote.get("open") or []
        return {
            "price": meta.get("regularMarketPrice"),
            "open": opens[0] if opens else None,
            "previousClose": (meta.get("chartPreviousClose")
                              or meta.get("previousClose")),
        }
    except Exception:
        return None
