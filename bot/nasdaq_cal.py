"""ปฏิทินงบแหล่งที่สอง (NASDAQ) — เทียบ/เติมปฏิทิน FMP ที่แผนฟรีกรองหุ้นออกเงียบ ๆ

ไม่ใช้ API key · คืนรูปเดียวกับ FMP earnings calendar: {"symbol","date","time"}
เป็นแหล่งเสริม: ล้มเหลววันไหนข้ามวันนั้น ห้ามทำสแกนหลักพัง
"""
from datetime import date, timedelta

import requests

NASDAQ_URL = "https://api.nasdaq.com/api/calendar/earnings"
# ไม่มี browser headers แล้ว NASDAQ จะแขวน request ทิ้งไว้เฉย ๆ
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json, text/plain, */*",
}
_TIMING = {"time-pre-market": "bmo", "time-after-hours": "amc"}


def fetch_nasdaq_earnings(from_date, to_date, get=requests.get):
    """หุ้นออกงบช่วง from_date..to_date (inclusive, ข้ามเสาร์-อาทิตย์)"""
    out = []
    d = date.fromisoformat(from_date)
    end = date.fromisoformat(to_date)
    while d <= end:
        if d.weekday() < 5:
            ds = d.isoformat()
            try:
                resp = get(NASDAQ_URL, params={"date": ds},
                           headers=_HEADERS, timeout=10)
                rows = (resp.json().get("data") or {}).get("rows") or []
            except Exception:
                rows = []
            for r in rows:
                sym = (r.get("symbol") or "").strip()
                if sym:
                    out.append({"symbol": sym, "date": ds,
                                "time": _TIMING.get(r.get("time"))})
        d += timedelta(days=1)
    return out
