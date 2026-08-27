"""มุมมอง "น่าสนใจตอนนี้" (พิมพ์ น่าสนใจ / /hot) — จัดกลุ่มหุ้นที่ติดตามจาก snapshot เดิม

ไม่ดึงข้อมูลใหม่ ไม่มี state ใหม่: 🔥 ใกล้แนว/เพิ่งทะลุ/งบใกล้/รอตอบรับ ·
⚠️ หลุด SL / ปิดใต้ Low ก่อนงบ (อันตรายชนะ) · 😴 ที่เหลือยุบบรรทัดเดียว
"""
import asyncio
from datetime import date
from types import SimpleNamespace

from telegram.ext import CommandHandler

import bot.main as m
from bot.config import Config
from bot.formatter import format_hot
from bot.hot import EARNINGS_SOON_DAYS, HOT_PCT, classify_watch

DUMMY_CONFIG = Config(telegram_token="123:ABC", chat_id="1", fmp_api_key="k")


def snap(symbol="EL", price=98.2, grade="B", high_5d=95.0, high_3m=99.6, sl=93.5,
         low_5d=92.0, new_breaks=(), sl_break=False, pending=False,
         days_to_earnings=None, timing="unknown", levels=True, vol_ratio=1.2):
    def pct(level):
        return round((price - level) / level * 100, 2) if level else None
    lv = None
    if levels:
        lv = {"price": price, "high_5d": high_5d, "pct_vs_high_5d": pct(high_5d),
              "high_3m": high_3m, "pct_vs_high_3m": pct(high_3m),
              "low_5d": low_5d, "pct_vs_low_5d": pct(low_5d),
              "sl": sl, "sl_pct": round((price - sl) / price * 100, 1) if sl else None}
    return {"symbol": symbol, "name": symbol, "price": price, "day_change_pct": 1.2,
            "grade": grade, "levels": lv, "new_breaks": list(new_breaks),
            "sl_break": sl_break, "low_break": False, "pending_reaction": pending,
            "days_to_earnings": days_to_earnings, "timing": timing,
            "vol_ratio": vol_ratio, "dr_symbols": ""}


def _hot(groups):
    return [(e["symbol"], e["reasons"]) for e in groups["hot"]]


# ── กลุ่ม 🔥 ─────────────────────────────────────────────────────


def test_just_broke_level_is_hot_with_break_reason():
    g = classify_watch([("NVDA", snap("NVDA", price=101.0, high_5d=100.0,
                                       new_breaks=["high_5d"]))])
    assert _hot(g) == [("NVDA", [("break", ["high_5d"])])]


def test_within_hot_pct_below_level_is_near():
    # 98.2 vs H3m 99.6 = -1.41% → ใกล้ · vs H5d 95 = +3.4% (เหนือแนวแล้ว) ไม่ใช่ "ใกล้"
    g = classify_watch([("EL", snap())])
    assert _hot(g) == [("EL", [("near", "high_3m", 1.41, 99.6)])]


def test_farther_than_hot_pct_is_idle():
    g = classify_watch([("EL", snap(price=96.0, high_5d=90.0, high_3m=99.6))])   # -3.6%
    assert g["hot"] == [] and g["idle"] == ["EL"]


def test_exactly_hot_pct_counts_as_near():
    level = 100.0
    price = round(level * (1 - HOT_PCT / 100), 2)
    g = classify_watch([("X", snap("X", price=price, high_5d=90.0, high_3m=level))])
    assert _hot(g)[0][1] == [("near", "high_3m", HOT_PCT, level)]


def test_near_both_levels_lists_both_nearest_first():
    g = classify_watch([("X", snap("X", price=98.0, high_5d=99.0, high_3m=100.0))])
    assert _hot(g)[0][1] == [("near", "high_5d", 1.01, 99.0),
                             ("near", "high_3m", 2.0, 100.0)]


def test_earnings_within_soon_days_is_hot():
    g = classify_watch([("AAPL", snap("AAPL", levels=False, days_to_earnings=1,
                                       timing="amc"))])
    assert _hot(g) == [("AAPL", [("earnings", 1, "amc")])]


def test_earnings_beyond_soon_days_is_idle():
    g = classify_watch([("AAPL", snap("AAPL", levels=False,
                                       days_to_earnings=EARNINGS_SOON_DAYS + 1))])
    assert g["idle"] == ["AAPL"]


def test_pending_reaction_is_hot():
    g = classify_watch([("ROST", snap("ROST", levels=False, pending=True))])
    assert _hot(g) == [("ROST", [("pending",)])]


def test_no_levels_no_earnings_is_idle():
    g = classify_watch([("CRM", snap("CRM", levels=False))])
    assert g["hot"] == [] and g["risk"] == [] and g["idle"] == ["CRM"]


# ── กลุ่ม ⚠️ ─────────────────────────────────────────────────────


def test_sl_break_edge_is_risk():
    g = classify_watch([("TGT", snap("TGT", price=145.1, sl=146.21, sl_break=True))])
    assert [(e["symbol"], e["reasons"]) for e in g["risk"]] == [("TGT", [("sl", 146.21)])]


def test_closing_below_sl_state_is_risk_even_without_edge():
    g = classify_watch([("TGT", snap("TGT", price=145.1, sl=146.21, low_5d=140.0))])
    assert [e["reasons"] for e in g["risk"]] == [[("sl", 146.21)]]


def test_closing_below_pre_earnings_low_is_risk():
    g = classify_watch([("X", snap("X", price=91.0, sl=None, low_5d=92.0))])
    assert [e["reasons"] for e in g["risk"]] == [[("low", 92.0)]]


def test_risk_wins_over_hot():
    # ใกล้ H3m แต่ปิดใต้ SL — ไปกลุ่มอันตรายอย่างเดียว
    g = classify_watch([("X", snap("X", price=98.0, high_3m=99.0, sl=99.5, low_5d=90.0))])
    assert g["hot"] == [] and [e["symbol"] for e in g["risk"]] == ["X"]


# ── ลำดับ / กลุ่มอื่น ─────────────────────────────────────────────


def test_hot_ordered_break_then_nearest_then_pending_then_earnings():
    items = [
        ("E", snap("E", levels=False, days_to_earnings=2)),
        ("N2", snap("N2", price=97.2, high_5d=90.0, high_3m=100.0)),   # -2.8%
        ("P", snap("P", levels=False, pending=True)),
        ("N1", snap("N1", price=98.6, high_5d=90.0, high_3m=100.0)),   # -1.4%
        ("B", snap("B", price=101.0, high_5d=100.0, new_breaks=["high_5d"])),
    ]
    assert [e["symbol"] for e in classify_watch(items)["hot"]] == ["B", "N1", "N2", "P", "E"]


def test_failed_snapshot_listed_separately_and_total_counts_everything():
    g = classify_watch([("A", None), ("EL", snap()), ("CRM", snap("CRM", levels=False))])
    assert g["failed"] == ["A"]
    assert g["total"] == 3
    assert g["idle"] == ["CRM"]


def test_idle_keeps_input_order():
    items = [(s, snap(s, levels=False)) for s in ("Z", "A", "M")]
    assert classify_watch(items)["idle"] == ["Z", "A", "M"]


# ── format_hot ───────────────────────────────────────────────────


def _groups():
    return classify_watch([
        ("EL", snap()),
        ("NVDA", snap("NVDA", price=182.0, grade="A", high_5d=180.0, high_3m=175.0,
                      new_breaks=["high_5d"], vol_ratio=2.1)),
        ("AAPL", snap("AAPL", grade=None, levels=False, days_to_earnings=1, timing="amc")),
        ("TGT", snap("TGT", price=145.1, sl=146.21, sl_break=True)),
        ("CRM", snap("CRM", levels=False)), ("SNPS", snap("SNPS", levels=False)),
        ("HPQ", None),
    ])


def test_format_hot_header_counts_hot_over_total():
    assert format_hot(_groups()).startswith("🔥 น่าสนใจตอนนี้ 3/7")


def test_format_hot_lines_show_price_change_and_reason():
    msg = format_hot(_groups())
    assert "🟡 EL 98.20 (+1.2%) — อีก 1.41% ถึง H3m 99.60 · SL 93.50" in msg
    assert "🔵 NVDA 182.00 (+1.2%) — เพิ่งทะลุ H5d ✅ · vol 2.1x" in msg
    assert "⚪ AAPL 98.20 (+1.2%) — งบพรุ่งนี้ หลังปิดตลาด US" in msg   # ป้าย timing ตาม _TIMING_TH เดิม


def test_format_hot_risk_section():
    msg = format_hot(_groups())
    assert "⚠️ ต้องตัดสินใจ 1" in msg
    assert "⛔ TGT 145.10" in msg and "หลุด SL 146.21" in msg


def test_format_hot_idle_and_failed_lines():
    msg = format_hot(_groups())
    assert "😴 ยังไม่ถึงจุด 2: CRM SNPS" in msg
    assert "⚠️ ดึงข้อมูลไม่ได้: HPQ" in msg
    assert msg.rstrip().endswith("หลุด SL/Low ก่อนงบ")     # บรรทัดเกณฑ์ท้ายข้อความ


def test_format_hot_low_break_reason():
    g = classify_watch([("X", snap("X", price=91.0, sl=None, low_5d=92.0))])
    assert "🛑 ปิดใต้ Low ก่อนงบ 92.00" in format_hot(g)


def test_format_hot_nothing_interesting():
    g = classify_watch([("CRM", snap("CRM", levels=False)), ("SNPS", snap("SNPS", levels=False))])
    msg = format_hot(g)
    assert msg.startswith("😴 ยังไม่มีตัวไหนถึงจุดน่าสนใจ (2 ตัว)")
    assert "ติดตาม" in msg                                   # ชี้ไปดูตารางเต็ม


def test_format_hot_sections_absent_when_empty():
    g = classify_watch([("EL", snap())])
    msg = format_hot(g)
    assert "ต้องตัดสินใจ" not in msg and "ยังไม่ถึงจุด" not in msg and "ดึงข้อมูลไม่ได้" not in msg


# ── wiring ใน main ───────────────────────────────────────────────


def _fake_update(text, chat_id=1):
    replies = []

    async def reply_text(t, **kw):
        replies.append((t, kw))
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id),
        message=SimpleNamespace(text=text, reply_text=reply_text)), replies


def test_hot_command_registered():
    app = m.build_app(DUMMY_CONFIG)
    cmds = {c for h in app.handlers[0] if isinstance(h, CommandHandler) for c in h.commands}
    assert "hot" in cmds


def test_thai_alias_routes_to_hot_handler(monkeypatch):
    monkeypatch.setattr(m, "CONFIG", DUMMY_CONFIG)
    calls = []

    async def fake(update):
        calls.append(update.message.text)
    monkeypatch.setattr(m, "_handle_hot", fake)
    for text in ("น่าสนใจ", " น่าสนใจ ", "hot", "HOT"):
        update, _ = _fake_update(text)
        asyncio.run(m.on_text(update, SimpleNamespace(bot=None)))
    assert len(calls) == 4


def test_handle_hot_replies_classified_view_from_shared_snapshots(monkeypatch):
    monkeypatch.setattr(m, "CONFIG", DUMMY_CONFIG)
    monkeypatch.setattr(m, "load_watchlist", lambda: ["EL"])
    monkeypatch.setattr(m, "active_auto", lambda: {"TGT": "2026-08-22"})
    seen = []

    async def fake_snapshots(update, symbols):
        seen.append(list(symbols))
        return [("EL", snap()), ("TGT", snap("TGT", price=145.1, sl=146.21, sl_break=True))]
    monkeypatch.setattr(m, "_watch_snapshots", fake_snapshots)
    update, replies = _fake_update("น่าสนใจ")
    asyncio.run(m._handle_hot(update))
    assert seen == [["EL", "TGT"]]
    assert replies[0][0].startswith("🔥 น่าสนใจตอนนี้ 1/2")
    assert "⛔ TGT" in replies[0][0]


def test_handle_hot_empty_watchlist_points_to_add_command(monkeypatch):
    monkeypatch.setattr(m, "CONFIG", DUMMY_CONFIG)
    monkeypatch.setattr(m, "load_watchlist", lambda: [])
    monkeypatch.setattr(m, "active_auto", lambda: {})
    update, replies = _fake_update("น่าสนใจ")
    asyncio.run(m._handle_hot(update))
    assert "ติดตาม NVDA" in replies[0][0]


def test_watch_show_uses_shared_snapshots_helper(monkeypatch):
    # ติดตาม (ตารางเต็ม) กับ น่าสนใจ ต้องดึง snapshot ทางเดียวกัน — ไม่มี loop ซ้ำสองชุด
    monkeypatch.setattr(m, "CONFIG", DUMMY_CONFIG)
    monkeypatch.setattr(m, "load_watchlist", lambda: ["EL"])
    monkeypatch.setattr(m, "active_auto", lambda: {})
    seen = []

    async def fake_snapshots(update, symbols):
        seen.append(list(symbols))
        return [("EL", snap())]
    monkeypatch.setattr(m, "_watch_snapshots", fake_snapshots)
    update, replies = _fake_update("ติดตาม")
    asyncio.run(m._handle_watch_command(update, "show", []))
    assert seen == [["EL"]]
    assert "👀 ติดตามอยู่ 1 ตัว" in replies[0][0]
