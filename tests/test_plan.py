"""แผนเทรดรายตัว (/plan, พิมพ์ "แผน CRM"): 3 ทางเข้าในราคา US + แปลงเป็นบาทต่อ DR
+ จำนวนหน่วยจากเงินเสี่ยง — pure ทั้งหมด (ข้อมูลราคาส่งเข้ามา)

SL = D0 Low (เหมือนทั้งระบบ) · เป้า 1R/2R/3R · DR: ราคาบาท = US × FX × implied ratio
หน่วยปัดลงเป็น lot 100 · ยังไม่ตั้ง /risk → มีราคาบาทแต่ไม่มีจำนวนหน่วย
"""
from bot.formatter import format_plan, format_settings
from bot.plan import (
    LOT,
    PLAN_MAX,
    build_plan,
    parse_plan_command,
    plan_unavailable_reason,
    rank_drs,
)


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


# ── parse_plan_command ───────────────────────────────────────────

def test_parse_plan_command():
    assert parse_plan_command("แผน CRM") == ["CRM"]
    assert parse_plan_command("plan crm nvda") == ["CRM", "NVDA"]
    assert parse_plan_command("แผนCRM") == ["CRM"]
    assert parse_plan_command("แผน") == []
    assert parse_plan_command("NVDA") is None
    assert parse_plan_command("แผนการ") is None
    assert PLAN_MAX <= 3


def test_parse_plan_command_caps_symbols():
    assert len(parse_plan_command("แผน A B C D E")) == PLAN_MAX


# ── build_plan: ราคา US ──────────────────────────────────────────

def test_plan_entries_in_fixed_order_with_r_and_targets():
    plan = build_plan(_snap(), risk_amount=None, drs=[])
    kinds = [e["kind"] for e in plan["entries"]]
    assert kinds == ["now", "breakout", "pullback"]
    now, brk, pull = plan["entries"]
    assert now["entry"] == 233.0 and brk["entry"] == 240.0 and pull["entry"] == 231.0
    assert plan["sl"] == 230.05
    assert round(now["risk"], 2) == 2.95
    assert round(now["risk_pct"], 2) == round(2.95 / 233.0 * 100, 2)
    assert [round(t, 2) for t in now["targets"]] == [235.95, 238.9, 241.85]
    assert [round(t, 2) for t in brk["targets"]] == [249.95, 259.9, 269.85]


def test_plan_entry_states_reflect_current_price():
    plan = build_plan(_snap(), risk_amount=None, drs=[])
    now, brk, pull = plan["entries"]
    assert now["state"] == "ok"
    assert brk["state"] == "pending"        # ราคายังต่ำกว่า High วันงบ
    assert pull["state"] == "waiting"       # ราคายังสูงกว่า D0 Open
    plan = build_plan(_snap(price=241.0), risk_amount=None, drs=[])
    assert plan["entries"][1]["state"] == "above"
    plan = build_plan(_snap(price=230.8), risk_amount=None, drs=[])
    assert plan["entries"][2]["state"] == "in_zone"


def test_plan_now_entry_invalid_when_price_below_sl():
    plan = build_plan(_snap(price=229.0), risk_amount=5000.0, drs=[DR])
    now = plan["entries"][0]
    assert now["state"] == "below_sl" and now["risk"] is None
    assert plan["drs"][0]["rows"][0]["units"] is None


# ── build_plan: DR ───────────────────────────────────────────────

def test_plan_converts_to_dr_baht_and_sizes_position():
    plan = build_plan(_snap(), risk_amount=5000.0, drs=[DR])
    assert plan["risk_amount"] == 5000.0
    d = plan["drs"][0]
    assert d["dr"] == "CRM19" and d["ratio"] == 0.031 and d["fx"] == 32.5
    row = d["rows"][0]                      # เข้าตอนนี้
    assert round(row["entry_thb"], 4) == round(233.0 * 32.5 * 0.031, 4)
    assert round(row["sl_thb"], 4) == round(230.05 * 32.5 * 0.031, 4)
    assert row["units"] == 1600             # 5000 / 2.9725 = 1682 → lot 100
    assert round(row["cost_thb"]) == round(1600 * 233.0 * 32.5 * 0.031)
    assert [round(t, 2) for t in row["targets_thb"]] == \
        [round(t * 32.5 * 0.031, 2) for t in plan["entries"][0]["targets"]]
    assert LOT == 100


def test_plan_without_risk_setting_has_baht_but_no_units():
    plan = build_plan(_snap(), risk_amount=None, drs=[DR])
    row = plan["drs"][0]["rows"][1]
    assert row["entry_thb"] > 0 and row["units"] is None and row["cost_thb"] is None


def test_plan_units_none_when_risk_too_small_for_one_lot():
    plan = build_plan(_snap(), risk_amount=100.0, drs=[DR])   # 100/2.97 = 33 หน่วย < lot
    assert plan["drs"][0]["rows"][0]["units"] is None


def test_rank_drs_by_volume_and_cap():
    drs = [dict(DR, dr="A", avg_volume=10), dict(DR, dr="B", avg_volume=500),
           dict(DR, dr="C", avg_volume=None), dict(DR, dr="D", avg_volume=50)]
    top, hidden = rank_drs(drs, max_n=2)
    assert [d["dr"] for d in top] == ["B", "D"]
    assert hidden == 2


# ── plan_unavailable_reason ──────────────────────────────────────

def test_unavailable_reasons():
    assert plan_unavailable_reason(_snap()) is None
    assert "รอ" in plan_unavailable_reason(_snap(levels=None, pending_reaction=True))
    assert "60 วัน" in plan_unavailable_reason(_snap(levels=None))
    neg = _snap(grade=None, score=None)
    neg["levels"]["reaction_pct"] = -2.0
    assert "ตอบรับลบ" in plan_unavailable_reason(neg)


# ── format_plan / format_settings ────────────────────────────────

def test_format_plan_message_us_and_dr_sections():
    plan = build_plan(_snap(), risk_amount=5000.0, drs=[DR])
    msg = format_plan(plan, _snap(), hidden=1)
    assert msg.startswith("📋 แผนเทรด CRM")
    assert "SL 230.05" in msg or "SL = D0 Low 230.05" in msg
    assert "① เข้าตอนนี้ 233.00" in msg
    assert "② ทะลุ High วันงบ 240.00" in msg and "ยังไม่ทะลุ" in msg
    assert "③ ย่อถึง D0 Open 231.00" in msg
    assert "235.95 / 238.90 / 241.85" in msg
    assert "CRM19" in msg and "1,600 หน่วย" in msg
    assert "เสี่ยง 5,000" in msg
    assert "+1 DR" in msg                   # ตัดเพราะเกินเพดาน ไม่ตัดเงียบ


def test_format_plan_without_risk_tells_how_to_set():
    plan = build_plan(_snap(), risk_amount=None, drs=[DR])
    msg = format_plan(plan, _snap())
    assert "/risk" in msg and "หน่วย" not in msg.split("🇹🇭")[1].split("\n")[1]


def test_format_plan_without_dr():
    plan = build_plan(_snap(dr_symbols=""), risk_amount=5000.0, drs=[])
    msg = format_plan(plan, _snap(dr_symbols=""))
    assert "🇹🇭" not in msg and "① เข้าตอนนี้" in msg


def test_format_settings():
    assert "500,000" in format_settings({"capital_thb": 500000.0, "risk_pct": 1.0})
    assert "5,000" in format_settings({"capital_thb": 500000.0, "risk_pct": 1.0})
    assert "/risk" in format_settings({"capital_thb": None, "risk_pct": 1.0})
