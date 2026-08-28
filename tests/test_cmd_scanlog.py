"""คำสั่ง /scanlog · "สแกนล็อก" — สแกนย้อนหลัง N วันแล้วโชว์สองเกณฑ์คู่กัน (🇹🇭 SET 0-15 คิดสดจาก bars ใน cache + เดิม A/B)
+ ลง scan_log.csv (schema ไทย + grade) — job สแกน 08:30 ก็ลงไฟล์เดียวกันผ่าน _record_scan_csv (port จาก HK Stock Screener)"""
import asyncio
import inspect
from datetime import date, timedelta
from types import SimpleNamespace

from telegram.ext import CommandHandler

from bot import main
from bot.config import Config
from bot.main import build_app

DUMMY_CONFIG = Config(telegram_token="123:ABC", chat_id="1", fmp_api_key="k")
TODAY = date(2026, 8, 28)


def _row(symbol, name, d0, ret, vr, grade="D", score=44.0, skip="D", signal_type=None, set_hit=False, set_pts=None):
    return {"symbol": symbol, "name": name, "earnings_date": d0, "timing": "amc", "d0": d0, "ret_d0_pct": ret,
            "vol_ratio": vr, "score": score, "grade": grade, "skip_reason": skip, "signal_type": signal_type,
            "set_hit": set_hit, "set_pts": set_pts}


SET_ROW = _row("NVDA", "NVIDIA", "2026-08-27", 16.0, 2.9, set_hit=True, set_pts=9)
ORIG_ROW = _row("CRM", "Salesforce", "2026-08-28", -2.8, 2.1, grade="B", score=75.0, skip=None,
                signal_type="composite", set_hit=False, set_pts=3)
MISS_ROW = _row("INTC", "Intel", "2026-08-28", 1.0, 0.5, skip="D", set_pts=2)
SCAN = {"from_date": "2026-08-21", "to_date": "2026-08-28", "universe_size": 500, "reported_symbols": ["NVDA", "CRM", "INTC"],
        "candidates": [], "skipped_counts": {"C": 0, "D": 2, "down": 0}, "pending": [],
        "rows": [SET_ROW, ORIG_ROW, MISS_ROW], "api_stats": {}}


def _bars(d0_iso, today=TODAY):
    """30 แท่งก่อน D0 (high 100 low 95 close 98 vol 1M) · D0 ปิด 110 vol 4M · หลังจากนั้นถึง today นิ่งที่ 105 — most-recent-first"""
    d0 = date.fromisoformat(d0_iso)
    days, cur = [], d0
    while len(days) < 30:
        cur -= timedelta(days=1)
        if cur.weekday() < 5:
            days.append(cur)
    asc = [{"date": d.isoformat(), "open": 98.0, "high": 100.0, "low": 95.0, "close": 98.0, "volume": 1_000_000}
           for d in reversed(days)]
    asc.append({"date": d0_iso, "open": 100.0, "high": 112.0, "low": 99.0, "close": 110.0, "volume": 4_000_000})
    cur = d0
    while cur < today:
        cur += timedelta(days=1)
        if cur.weekday() < 5 and cur <= today:
            asc.append({"date": cur.isoformat(), "open": 105.0, "high": 105.0, "low": 103.0, "close": 104.0,
                        "volume": 1_000_000})
    return asc[::-1]


class FakeMessage:
    def __init__(self, text=""):
        self.text = text
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append(text)


def _update(text="", chat_id="1"):
    msg = FakeMessage(text)
    return SimpleNamespace(effective_chat=SimpleNamespace(id=chat_id), message=msg), msg


def _setup(monkeypatch, cached_symbols=("NVDA",)):
    calls, written = [], []
    monkeypatch.setattr(main, "CONFIG", DUMMY_CONFIG)

    def run_scan(config, lookback, secondary_cal_fn=None):
        calls.append(lookback)
        return {**SCAN, "rows": [dict(r) for r in SCAN["rows"]]}
    monkeypatch.setattr(main, "run_scan", run_scan)
    by = {r["symbol"]: r for r in SCAN["rows"]}
    monkeypatch.setattr(main, "fetch_cache", SimpleNamespace(
        get=lambda key: _bars(by[key[1]]["d0"]) if key[1] in cached_symbols else None))
    monkeypatch.setattr(main, "record_scan_csv",
                        lambda entries, scan_date, path=None: written.append((entries, scan_date)) or len(entries))
    return calls, written


def test_scanlog_command_registered():
    app = build_app(DUMMY_CONFIG)
    cmds = {c for h in app.handlers[0] if isinstance(h, CommandHandler) for c in h.commands}
    assert "scanlog" in cmds


def test_scanlog_sends_two_groups_and_records_csv(monkeypatch):
    calls, written = _setup(monkeypatch)
    bot = FakeBot()
    asyncio.run(main._scanlog(bot, "1", 7))
    assert calls == [7]
    text = "\n".join(bot.sent)
    assert text.startswith("🗂 สองเกณฑ์คู่กัน 2026-08-21 → 2026-08-28 · สแกน 3 ตัว · ทั้งสองเกณฑ์ 0 · เฉพาะ SET 1 · เฉพาะเดิม 1")
    assert "🇹🇭 เกณฑ์ SET (ปิด D0 ≥ +2% & vol ≥ 1.5×) · 1 ตัว" in text
    assert "• NVDA NVIDIA ⭐⭐ 11/15 · ปิด D0 +16.0% · vol 2.9x · H5d ✓ H3m ✓ · ไฮใหม่ล่าสุด 1 วัน" in text   # คะแนนสดจาก bars ใน cache
    assert "• CRM Salesforce ✅ B 75 · ปิด D0 -2.8% · vol 2.1x · 2026-08-28 · SET: ✗ ปิด < +2%" in text
    assert "INTC" not in text and "scan_log.csv" in text
    (entries, scan_date), = written
    assert scan_date == TODAY
    assert [(r["symbol"], s["pts"] if s else None) for r, s in entries] == [("NVDA", 11), ("CRM", None)]


def test_scanlog_falls_back_to_stored_score_when_bars_not_cached(monkeypatch):
    _setup(monkeypatch, cached_symbols=())
    bot = FakeBot()
    asyncio.run(main._scanlog(bot, "1", 2))
    assert "• NVDA NVIDIA ⭐⭐ 9/15 (ณ วันสแกน) · ปิด D0 +16.0%" in "\n".join(bot.sent)


def test_daily_scan_job_records_csv_through_same_helper(monkeypatch):
    """_do_scan_and_send ต้องเรียก _record_scan_csv(scan) — ไฟล์สะสมเองทุกวันโดยไม่ต้องกด /scanlog"""
    assert "_record_scan_csv(scan)" in inspect.getsource(main._do_scan_and_send)
    calls, written = _setup(monkeypatch)
    rows, scored = main._record_scan_csv({**SCAN, "rows": [dict(r) for r in SCAN["rows"]]})
    assert [r["symbol"] for r in rows] == ["NVDA", "CRM", "INTC"] and scored["NVDA"]["pts"] == 11 and scored["CRM"] is None
    assert written and [r["symbol"] for r, _ in written[0][0]] == ["NVDA", "CRM"]


def test_cmd_scanlog_bad_arg_replies_usage(monkeypatch):
    calls, _ = _setup(monkeypatch)
    update, msg = _update()
    asyncio.run(main.cmd_scanlog(update, SimpleNamespace(args=["x"], bot=FakeBot())))
    assert calls == [] and msg.replies == ["ใช้: /scanlog หรือ /scanlog <จำนวนวันย้อนหลัง 1-30>"]


def test_cmd_scanlog_default_lookback_and_clamp(monkeypatch):
    calls, _ = _setup(monkeypatch)
    update, msg = _update()
    asyncio.run(main.cmd_scanlog(update, SimpleNamespace(args=[], bot=FakeBot())))
    asyncio.run(main.cmd_scanlog(update, SimpleNamespace(args=["90"], bot=FakeBot())))
    assert calls == [DUMMY_CONFIG.lookback_days, 30]
    assert msg.replies[0].startswith("🔍 กำลังสแกน + คิดคะแนน SET ย้อนหลัง 2 วัน")


def test_cmd_scanlog_unauthorized_silent(monkeypatch):
    calls, _ = _setup(monkeypatch)
    update, msg = _update(chat_id="999")
    asyncio.run(main.cmd_scanlog(update, SimpleNamespace(args=[], bot=FakeBot())))
    assert calls == [] and msg.replies == []


def test_thai_keyword_routes_to_scanlog(monkeypatch):
    calls, _ = _setup(monkeypatch)
    update, msg = _update("สแกนล็อก 5")
    asyncio.run(main.on_text(update, SimpleNamespace(args=[], bot=FakeBot())))
    assert calls == [5]
