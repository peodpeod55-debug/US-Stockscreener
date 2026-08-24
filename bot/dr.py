"""DR premium/discount: ราคา DR ไทยแพง/ถูกแค่ไหนเทียบหุ้นแม่ × USDTHB

ไม่ต้องรู้ ratio ทางการของ DR — ใช้ implied ratio: k(t) = DR / (US × FX)
premium = k ล่าสุด เทียบ median ของ k ย้อนหลัง (baseline) → ตอบว่า
"แพง/ถูกกว่าปกติของตัวมันเอง" ซึ่ง baseline ดูดซับ premium ถาวรของ DR นั้นไปแล้ว

การจับคู่วัน: DR ซื้อขายวันไทย D ตอบรับ US close ของคืนก่อน (session ที่จบ
เช้าวัน D เวลาไทย) → คู่ = US close ล่าสุดที่ date < D, FX ล่าสุดที่ date <= D
"""
from statistics import median

from bot.lookup import parse_tickers

BASELINE_DAYS = 60              # จำนวนคู่มากสุดที่ใช้หา ratio ปกติ
BASELINE_MIN_PAIRS = 10         # คู่ขั้นต่ำ (ไม่นับวันล่าสุด) ถึงคำนวณ premium
DR_MAX = 6                      # DR ต่อหุ้นแม่มากสุดที่รายงาน (คุมความยาว/เวลา)

_CMD_WORDS = ("dr", "ดีอาร์")


def parse_dr_command(text):
    """"dr NVDA" / "ดีอาร์ NVDA TSLA" → list ticker หุ้นแม่ · None = ไม่ใช่คำสั่งนี้"""
    tokens = (text or "").split()
    if not tokens or tokens[0].lower() not in _CMD_WORDS:
        return None
    return parse_tickers(" ".join(tokens[1:]))


def parse_dr_symbols(dr_symbols):
    """คอลัมน์ dr_symbols ใน universe (คั่นช่องว่าง) → list สัญลักษณ์ DR"""
    return (dr_symbols or "").split()


def _latest_before(prices, date_str, inclusive=False):
    """แท่งล่าสุดที่ date < date_str (หรือ <= ถ้า inclusive) — prices most-recent-first"""
    for bar in prices:
        d = bar.get("date")
        if d and (d <= date_str if inclusive else d < date_str):
            return bar
    return None


def pair_ratios(dr_prices, us_prices, fx_prices):
    """implied ratio ต่อวัน DR ที่จับคู่ได้ — คืน list เก่า→ใหม่"""
    ratios = []
    for bar in reversed(dr_prices or []):           # เก่า → ใหม่
        d = bar.get("date")
        us = _latest_before(us_prices or [], d)
        fx = _latest_before(fx_prices or [], d, inclusive=True)
        if not d or us is None or fx is None:
            continue
        base = us["close"] * fx["close"]
        if base:
            ratios.append(bar["close"] / base)
    return ratios


def compute_premium(dr_prices, us_prices, fx_prices, dr_quote=None,
                    fx_quote=None):
    """premium ของ DR ล่าสุดเทียบ ratio ปกติ — None ถ้าคู่ข้อมูลไม่พอ

    dr_quote/fx_quote: quote สด (dict price/previousClose) — มีแล้วใช้แทน
    close แท่งล่าสุด → premium สะท้อนราคาปัจจุบัน (baseline ยังจากรายวันเดิม)
    คืน dict: dr_price, dr_date, volume, us_price, us_date, fx,
    baseline (median ratio ไม่รวมวันล่าสุด), fair (us×fx×baseline),
    premium_pct, live (ใช้ quote สดไหม), day_pct (%วันนี้ — เฉพาะ live),
    fx_live (FX จาก quote สดไหม)
    """
    if not dr_prices:
        return None
    recent = dr_prices[:BASELINE_DAYS + 1]
    ratios = pair_ratios(recent, us_prices, fx_prices)
    if len(ratios) < BASELINE_MIN_PAIRS + 1:
        return None
    baseline = median(ratios[:-1])
    if not baseline:
        return None
    last = dr_prices[0]
    us = _latest_before(us_prices, last["date"])
    fx = _latest_before(fx_prices, last["date"], inclusive=True)
    if us is None or fx is None:      # แท่ง DR ล่าสุดจับคู่ไม่ได้ (ข้อมูลขาดช่วง)
        return None
    dr_live = (dr_quote or {}).get("price")
    fx_live = (fx_quote or {}).get("price")
    dr_price = dr_live if dr_live is not None else last["close"]
    fx_val = fx_live if fx_live is not None else fx["close"]
    base = us["close"] * fx_val
    if not base:
        return None
    day_pct = None
    prev = (dr_quote or {}).get("previousClose")
    if dr_live is not None and prev:
        day_pct = (dr_live - prev) / prev * 100
    return {
        "dr_price": dr_price,
        "dr_date": last["date"],
        "volume": last.get("volume"),
        "us_price": us["close"],
        "us_date": us["date"],
        "fx": fx_val,
        "baseline": baseline,
        "fair": base * baseline,
        "premium_pct": (dr_price / base / baseline - 1) * 100,
        "live": dr_live is not None,
        "day_pct": day_pct,
        "fx_live": fx_live is not None,
    }
