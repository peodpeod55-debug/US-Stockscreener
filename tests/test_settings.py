"""ตั้งค่าเงินเสี่ยง/ทุน (settings.json) สำหรับคำนวณจำนวนหน่วยใน /plan

พิมพ์ `เสี่ยง 1% ทุน 500000` (หรือ /risk ...) · `เสี่ยง` เฉย ๆ = ดูค่า · ค่าที่ไม่ได้พิมพ์คงเดิม
"""
import pytest

from bot.settings import (
    load_settings,
    parse_risk_command,
    risk_amount,
    update_settings,
)


def test_parse_full_command_percent_and_capital():
    assert parse_risk_command("เสี่ยง 1% ทุน 500000") == \
        {"risk_pct": 1.0, "capital_thb": 500000.0}
    assert parse_risk_command("risk 0.5 300,000") == \
        {"risk_pct": 0.5, "capital_thb": 300000.0}


def test_parse_partial_commands():
    assert parse_risk_command("เสี่ยง ทุน 300000") == {"capital_thb": 300000.0}
    assert parse_risk_command("เสี่ยง 2%") == {"risk_pct": 2.0}
    assert parse_risk_command("เสี่ยง") == {}          # = ขอดูค่า
    assert parse_risk_command("/risk") == {}


def test_parse_not_this_command():
    assert parse_risk_command("NVDA") is None
    assert parse_risk_command("เสี่ยงมาก") is None    # ต้องตรงคำ ไม่ใช่ prefix
    assert parse_risk_command("") is None
    assert parse_risk_command(None) is None


def test_parse_junk_number_ignored():
    assert parse_risk_command("เสี่ยง abc") == {}


def test_load_defaults_when_missing(tmp_path):
    p = tmp_path / "settings.json"
    assert load_settings(p) == {"capital_thb": None, "risk_pct": 1.0}


def test_update_merges_and_persists(tmp_path):
    p = tmp_path / "settings.json"
    s = update_settings({"capital_thb": 500000.0}, path=p)
    assert s == {"capital_thb": 500000.0, "risk_pct": 1.0}
    s = update_settings({"risk_pct": 0.5}, path=p)
    assert s == {"capital_thb": 500000.0, "risk_pct": 0.5}
    assert load_settings(p) == s


def test_update_rejects_out_of_range(tmp_path):
    p = tmp_path / "settings.json"
    with pytest.raises(ValueError):
        update_settings({"risk_pct": 50}, path=p)       # เสี่ยง 50%/ไม้ = พิมพ์ผิดแน่
    with pytest.raises(ValueError):
        update_settings({"risk_pct": 0}, path=p)
    with pytest.raises(ValueError):
        update_settings({"capital_thb": -1}, path=p)
    assert load_settings(p) == {"capital_thb": None, "risk_pct": 1.0}


def test_risk_amount():
    assert risk_amount({"capital_thb": 500000.0, "risk_pct": 1.0}) == 5000.0
    assert risk_amount({"capital_thb": None, "risk_pct": 1.0}) is None
    assert risk_amount({}) is None
