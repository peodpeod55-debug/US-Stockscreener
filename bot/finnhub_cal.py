"""ปฏิทินงบ Finnhub (ตัวเลือก — ตั้ง FINNHUB_API_KEY ใน .env ถึงจะใช้)

จุดเด่น: field hour = bmo/amc ที่ NASDAQ มักไม่บอก (time-not-supplied) และ FMP stable
ไม่มีเลย → เติม timing ให้คลังวันงบ (bot/earnings_store.py) ลดเคส "UNKNOWN" ที่ต้อง
พึ่ง infer_bmo · ฟรีทีร์: 60 calls/นาที (ใช้ ≤2 call/วัน)
คืนรูปเดียวกับ FMP/NASDAQ: [{"symbol", "date", "time"}] · เป็นแหล่งเสริม: ไม่มี key /
ล้ม / JSON พัง → [] ห้าม raise · ส่ง key ทาง header ไม่ใช่ URL (กันหลุดลง log)
"""
import logging

import requests

FINNHUB_URL = "https://finnhub.io/api/v1/calendar/earnings"
_HOUR = {"bmo": "bmo", "amc": "amc"}     # dmh (ระหว่างวัน) / "" → ไม่ระบุ

logger = logging.getLogger("bot.finnhub")


def fetch_finnhub_earnings(from_date, to_date, api_key, get=requests.get):
    """หุ้นที่ออกงบช่วง from_date..to_date (ทุกตัวที่ Finnhub มี) หรือ [] ถ้าไม่มี key/ล้ม"""
    if not api_key:
        return []
    try:
        resp = get(FINNHUB_URL, params={"from": from_date, "to": to_date},
                   headers={"X-Finnhub-Token": api_key}, timeout=15)
        if resp.status_code != 200:
            logger.warning("finnhub calendar HTTP %s", resp.status_code)
            return []
        rows = (resp.json() or {}).get("earningsCalendar") or []
    except Exception:
        logger.warning("finnhub calendar failed", exc_info=True)
        return []
    out = []
    for r in rows:
        sym, d = (r.get("symbol") or "").strip(), r.get("date")
        if sym and d:
            out.append({"symbol": sym, "date": d,
                        "time": _HOUR.get((r.get("hour") or "").lower())})
    return out
