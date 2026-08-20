"""Cache ผลดึงข้อมูลข้าม job ในโปรเซสเดียว (in-memory, TTL 60 นาที)

job เช้าวิ่งติดกัน (breakout 08:20 → reminder 08:25 → scan 08:30 → catch-up)
ดึงราคา EOD/วันงบชุดเดียวกันซ้ำ — ข้อมูลไม่เปลี่ยนระหว่างวัน cache ตัดงบ API เกินครึ่ง
คีย์ตามผู้ใช้กำหนด เช่น ("prices", symbol, days) / ("earnings", symbol)
ค่าว่าง (None/[]) ไม่ cache — fetch ที่ล้มชั่วคราวต้องลองใหม่ได้
"""
from datetime import datetime, timedelta

CACHE_TTL = timedelta(minutes=60)

_cache = {}  # key -> (fetched_at, value)


def get(key, now=None):
    """ค่าใน cache ที่ยังไม่หมดอายุ — list คืนสำเนา (กันผู้ใช้แก้แล้วสะเทือน cache)"""
    entry = _cache.get(key)
    if entry is None:
        return None
    fetched_at, value = entry
    now = now or datetime.now()
    if now - fetched_at >= CACHE_TTL:
        del _cache[key]
        return None
    return list(value) if isinstance(value, list) else value


def put(key, value, now=None):
    if not value:
        return
    _cache[key] = (now or datetime.now(), value)


def cached(key, fetch_fn, now=None):
    """get → ถ้าไม่มีเรียก fetch_fn แล้วเก็บ (เฉพาะค่าไม่ว่าง) — คืนค่าที่ได้"""
    value = get(key, now)
    if value is None:
        value = fetch_fn()
        put(key, value, now)
    return value


def clear():
    _cache.clear()
