"""run_scan คืน rows = ทุกตัวที่มีแท่ง D0 (แจ้ง + ตกเกณฑ์ down/C/D) พร้อมเกณฑ์ SET (set_hit/set_pts) — ฐานของ scan_log.csv / /scanlog
(แนวเดียวกับ scan_log ของ HK Stock Screener แต่ไม่เก็บไฟล์ JSON — rows อยู่ในผลสแกนรอบนั้น)"""
from datetime import date, datetime, timedelta

from bot.config import Config
from bot.screener import run_scan
from tests.test_screener import FakeClient

CFG = Config(telegram_token="t", chat_id="1", fmp_api_key="k")
END = date(2026, 8, 19)


def _bars(n=250, end=END, d0_close_pct=None, d0_volume=2_000_000):
    """แท่ง most-recent-first ปิดคงที่ 100 · แท่ง D0 (= end) ปิด +d0_close_pct% ถ้าให้"""
    bars, d = [], end
    while len(bars) < n:
        if d.weekday() < 5:
            bars.append({"date": d.isoformat(), "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
                         "volume": 2_000_000})
        d -= timedelta(days=1)
    if d0_close_pct is not None:
        c = 100.0 * (1 + d0_close_pct / 100)
        bars[0] = {**bars[0], "open": 100.5, "high": max(101.0, c + 0.5), "low": 99.5, "close": c, "volume": d0_volume}
    return bars


def _scan(bars_by_symbol, calendar):
    return run_scan(CFG, lookback_days=3, client=FakeClient(calendar, bars_by_symbol), today=datetime(2026, 8, 19, 9, 0))


def test_rows_cover_skipped_and_candidates_with_set_fields():
    """AAPL ปิด D0 +5% vol 3× (SET ✓ แต่เกรดอาจ C/D) · ABT ปิด -3% (down) — ทั้งคู่ต้องมีแถว"""
    earn = _bars()[1]["date"]                                                  # amc วันก่อน → D0 = แท่งล่าสุด
    scan = _scan({"AAPL": _bars(d0_close_pct=5.0, d0_volume=6_000_000), "ABT": _bars(d0_close_pct=-3.0)},
                 [{"symbol": "AAPL", "date": earn, "time": "amc"}, {"symbol": "ABT", "date": earn, "time": "amc"}])
    rows = {r["symbol"]: r for r in scan["rows"]}
    assert set(rows) == {"AAPL", "ABT"}
    a = rows["AAPL"]
    assert a["d0"] == END.isoformat() and a["earnings_date"] == earn
    assert a["ret_d0_pct"] == 5.0 and a["vol_ratio"] == 3.0
    assert a["set_hit"] is True and isinstance(a["set_pts"], int) and a["set_pts"] >= 5
    assert a["grade"] in ("A", "B", "C", "D") and a["score"] is not None
    assert a["skip_reason"] in (None, "C", "D")
    assert (a["skip_reason"] is None) == (a["signal_type"] == "composite") == ("AAPL" in [c["symbol"] for c in scan["candidates"]])
    b = rows["ABT"]
    assert b["skip_reason"] == "down" and b["signal_type"] is None and b["set_hit"] is False
    assert b["ret_d0_pct"] == -3.0 and b["grade"] in ("A", "B", "C", "D")   # เกรดคิดให้ทุกแถวแม้ตัดเพราะปิดลบ
    assert scan["skipped_counts"]["down"] == 1


def test_pending_symbols_have_no_row():
    earn = END.isoformat()                                                     # amc วันนี้ → ยังไม่มีแท่ง D0
    scan = _scan({"AAPL": _bars()}, [{"symbol": "AAPL", "date": earn, "time": "amc"}])
    assert scan["rows"] == [] and scan["pending"] and scan["pending"][0]["reason"] == "waiting"


def test_set_hit_requires_both_thresholds():
    earn = _bars()[1]["date"]
    weak = _scan({"AAPL": _bars(d0_close_pct=1.0, d0_volume=6_000_000)}, [{"symbol": "AAPL", "date": earn, "time": "amc"}])
    assert weak["rows"][0]["set_hit"] is False                                 # +1% < 2%
    thin = _scan({"AAPL": _bars(d0_close_pct=5.0, d0_volume=2_000_000)}, [{"symbol": "AAPL", "date": earn, "time": "amc"}])
    assert thin["rows"][0]["set_hit"] is False                                 # vol 1× < 1.5×
