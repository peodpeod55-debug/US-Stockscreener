"""wiring ใน main ของ /plan · "แผน CRM" · ปุ่ม 📋 และ /risk · "เสี่ยง 1% ทุน 500000"
(logic ล้วน ๆ อยู่ใน test_plan.py / test_settings.py — ที่นี่เช็ค dispatcher, ประกอบข้อมูล DR
จาก Yahoo, DR ล้มแล้วยังได้แผนราคา US, บันทึก settings แล้วตอบกลับ)"""
import asyncio
from datetime import date, timedelta
from types import SimpleNamespace

import bot.main as m
import bot.settings as settings_mod
from bot.config import Config

DUMMY_CONFIG = Config(telegram_token="123:ABC", chat_id="1", fmp_api_key="k")


def _snap(**over):
    s = {"symbol": "CRM", "name": "Salesforce", "grade": "B", "score": 75.0,
         "price": 233.0, "day_change_pct": 1.2, "last_earnings": "2026-08-26",
         "timing": "amc", "dr_symbols": "CRM19 CRM80", "pending_reaction": False,
         "levels": {"sl": 230.05, "sl_pct": 1.27, "d0_high": 240.0, "d0_open": 231.0,
                    "pct_vs_d0_high": -2.92, "reaction_pct": 3.0, "high_5d": 213.17,
                    "high_3m": 260.0}}
    s.update(over)
    return s


DR = {"dr": "CRM19", "ratio": 0.031, "fx": 32.5, "dr_price": 236.0, "avg_volume": 50_000}


class FakeMessage:
    def __init__(self, text=""):
        self.text = text
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


def _update(text=""):
    msg = FakeMessage(text)
    return SimpleNamespace(effective_chat=SimpleNamespace(id=1), message=msg), msg


# ── dispatcher ───────────────────────────────────────────────────

def test_dispatch_plan_and_risk_commands(monkeypatch):
    monkeypatch.setattr(m, "CONFIG", DUMMY_CONFIG)
    calls = []

    async def fake_plan(update, context, tickers):
        calls.append(("plan", tickers))

    async def fake_risk(update, changes):
        calls.append(("risk", changes))
    monkeypatch.setattr(m, "_handle_plan", fake_plan)
    monkeypatch.setattr(m, "_handle_risk", fake_risk)
    ctx = SimpleNamespace(bot=None)
    for text in ("แผน CRM", "plan crm nvda", "เสี่ยง 1% ทุน 500000", "เสี่ยง"):
        update, _ = _update(text)
        asyncio.run(m._dispatch_text(update, ctx, text))
    assert calls == [("plan", ["CRM"]), ("plan", ["CRM", "NVDA"]),
                     ("risk", {"risk_pct": 1.0, "capital_thb": 500000.0}),
                     ("risk", {})]


def test_handle_plan_usage_then_send(monkeypatch):
    sent = []

    async def fake_send(bot, chat_id, tickers):
        sent.append((bot, chat_id, tickers))
    monkeypatch.setattr(m, "_send_plans", fake_send)
    update, msg = _update("แผน")
    asyncio.run(m._handle_plan(update, SimpleNamespace(bot="B"), []))
    assert sent == [] and "แผน CRM" in msg.replies[0]
    asyncio.run(m._handle_plan(update, SimpleNamespace(bot="B"), ["CRM"]))
    assert sent == [("B", 1, ["CRM"])]


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append(text)


def test_send_plans_waits_only_when_fetch_needed(monkeypatch):
    """⏳ เฉพาะตอนราคา/แท่ง DR ยังไม่อยู่ใน cache · ตัวที่ล้มได้ข้อความ ⚠️ ตัวอื่นยังได้แผน"""
    from bot import fetch_cache
    monkeypatch.setattr(m, "CONFIG", DUMMY_CONFIG)
    monkeypatch.setattr(m, "load_universe",
                        lambda: {"CRM": {"name": "Salesforce", "dr_symbols": "CRM19"}})
    monkeypatch.setattr(m, "FMPClient", lambda **kw: object())
    monkeypatch.setattr(m, "prefetch", lambda syms, days, client: None)

    def fake_build(client, sym, universe, risk):
        assert risk is None                   # settings.json ใน tmp (conftest) → ยังไม่ตั้งทุน
        if sym == "BAD":
            raise RuntimeError("boom")
        return f"📋 แผนเทรด {sym}"
    monkeypatch.setattr(m, "_build_plan_message", fake_build)
    bot = FakeBot()
    asyncio.run(m._send_plans(bot, 1, ["CRM", "BAD"]))
    assert bot.sent[0].startswith("⏳") and bot.sent[1] == "📋 แผนเทรด CRM"
    assert bot.sent[2].startswith("⚠️") and "BAD" in bot.sent[2]
    # cache ครบ (ราคาหุ้นแม่ + แท่ง DR) → ไม่มี ⏳
    fetch_cache.put(("prices", "CRM", 250), [{"close": 1}])
    fetch_cache.put(("dr", "CRM19"), [{"close": 1}])
    bot = FakeBot()
    asyncio.run(m._send_plans(bot, 1, ["CRM"]))
    assert bot.sent == ["📋 แผนเทรด CRM"]


# ── /risk ────────────────────────────────────────────────────────

def test_handle_risk_set_show_and_reject(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", tmp_path / "settings.json")
    update, msg = _update()
    asyncio.run(m._handle_risk(update, {"capital_thb": 500000.0}))
    assert msg.replies[0].startswith("✅")
    assert "500,000" in msg.replies[0] and "5,000" in msg.replies[0]
    asyncio.run(m._handle_risk(update, {}))
    assert "500,000" in msg.replies[1] and "/risk" in msg.replies[1]
    asyncio.run(m._handle_risk(update, {"risk_pct": 50}))
    assert msg.replies[2].startswith("⚠️")
    assert settings_mod.load_settings()["risk_pct"] == 1.0    # ค่าผิดไม่ถูกบันทึก


# ── _build_plan_message ──────────────────────────────────────────

def _patch_lookup(monkeypatch, snap):
    monkeypatch.setattr(m, "lookup_symbol", lambda client, sym, universe: snap)


def test_build_plan_message_with_dr_and_skipped(monkeypatch):
    _patch_lookup(monkeypatch, _snap())
    monkeypatch.setattr(m, "_plan_dr_items", lambda sym, drs: ([DR], ["CRM80"]))
    msg = m._build_plan_message(None, "CRM", {}, 5000.0)
    assert msg.startswith("📋 แผนเทรด CRM")
    assert "CRM19" in msg and "1,600 หน่วย" in msg and "เสี่ยง 5,000" in msg
    assert "CRM80" in msg                     # DR ที่ข้ามเพราะข้อมูลไม่พอ ไม่หายเงียบ


def test_build_plan_message_dr_failure_keeps_us_plan(monkeypatch):
    _patch_lookup(monkeypatch, _snap())

    def boom(sym, drs):
        raise RuntimeError("yahoo down")
    monkeypatch.setattr(m, "_plan_dr_items", boom)
    msg = m._build_plan_message(None, "CRM", {}, None)
    assert "① เข้าตอนนี้ 233.00" in msg and "🇹🇭" not in msg
    assert "⚠️" in msg and "/risk" in msg


def test_build_plan_message_no_dr_symbols_skips_fetch(monkeypatch):
    _patch_lookup(monkeypatch, _snap(dr_symbols=""))

    def boom(sym, drs):
        raise AssertionError("ต้องไม่ดึง DR")
    monkeypatch.setattr(m, "_plan_dr_items", boom)
    msg = m._build_plan_message(None, "CRM", {}, 5000.0)
    assert "① เข้าตอนนี้ 233.00" in msg and "🇹🇭" not in msg


def test_build_plan_message_unavailable(monkeypatch):
    _patch_lookup(monkeypatch, None)
    assert m._build_plan_message(None, "XXXX", {}, None).startswith("❌")
    _patch_lookup(monkeypatch, _snap(levels=None))
    assert "60 วัน" in m._build_plan_message(None, "CRM", {}, None)
    _patch_lookup(monkeypatch, _snap(levels=None, pending_reaction=True))
    assert "รอ" in m._build_plan_message(None, "CRM", {}, None)


# ── _plan_dr_items: ประกอบข้อมูล DR จาก Yahoo ────────────────────

def _weekdays(start, n):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _bars(pairs, volume=1_000):
    return [{"date": d, "open": c, "high": c, "low": c, "close": c, "volume": volume}
            for d, c in reversed(pairs)]


def test_plan_dr_items_from_yahoo(monkeypatch):
    days = _weekdays(date(2026, 7, 1), 16)
    us = _bars([(d, 100.0) for d in days])
    fx = _bars([(d, 32.0) for d in days])
    dr = _bars([(d, 96.0) for d in days[1:]], volume=2_000)   # k = 96 / (100 × 32) = 0.03
    feeds = {"USDTHB=X": fx, "CRM19.BK": dr, "CRM80.BK": None}
    seen = []

    def fake_prices(symbol, days=250, raw=False, **kw):
        assert raw, symbol                    # .BK / =X ห้ามแปลงจุด
        seen.append(symbol)
        return feeds[symbol]
    monkeypatch.setattr(m, "fetch_yahoo_prices", fake_prices)
    monkeypatch.setattr(m, "fetch_yahoo_quote", lambda symbol, raw=False: {"price": 33.0})
    monkeypatch.setattr(m, "get_prices", lambda sym, days: us)
    items, skipped = m._plan_dr_items("CRM", ["CRM19", "CRM80"])
    assert skipped == ["CRM80"]
    assert [i["dr"] for i in items] == ["CRM19"]
    it = items[0]
    assert round(it["ratio"], 6) == 0.03 and it["fx"] == 33.0    # FX จาก quote สด
    assert it["dr_price"] == 96.0 and it["avg_volume"] == 2_000
    # quote FX ล้ม → ถอยไปใช้ close แท่งล่าสุด (แท่ง DR/FX มาจาก cache ไม่ดึงซ้ำ)
    monkeypatch.setattr(m, "fetch_yahoo_quote", lambda symbol, raw=False: None)
    n = len(seen)
    items, _ = m._plan_dr_items("CRM", ["CRM19"])
    assert items[0]["fx"] == 32.0 and len(seen) == n
