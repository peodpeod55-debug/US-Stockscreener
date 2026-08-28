"""ตั้งค่าผู้ใช้: ทุน (บาท) + % เสี่ยงต่อไม้ → settings.json (gitignored — ข้อมูลส่วนตัว)

พิมพ์ `เสี่ยง 1% ทุน 500000` (หรือ `/risk 1% ทุน 500000`) · `เสี่ยง` เฉย ๆ = ดูค่า
ค่าที่ไม่ได้พิมพ์คงเดิม · เงินเสี่ยงต่อไม้ = ทุน × % → /plan ใช้คำนวณจำนวนหน่วย DR
"""
import json
import re

from bot.config import PROJECT_ROOT
from bot.fileio import write_json_atomic

SETTINGS_PATH = PROJECT_ROOT / "settings.json"
DEFAULTS = {"capital_thb": None, "risk_pct": 1.0}
RISK_PCT_MAX = 10.0             # เสี่ยงเกินนี้ต่อไม้ = พิมพ์ผิดแน่ (กันสับสนกับตัวเลขทุน)

_CMD_WORDS = ("เสี่ยง", "risk", "/risk")
_CAPITAL_WORDS = ("ทุน", "capital")
_NUM = re.compile(r"^(\d[\d,]*(?:\.\d+)?)(%?)$")


def parse_risk_command(text):
    """"เสี่ยง 1% ทุน 500000" → {"risk_pct": 1.0, "capital_thb": 500000.0}

    เลขที่มี % หรือเลขแรกที่ ≤ RISK_PCT_MAX = % เสี่ยง · เลขหลัง "ทุน" หรือเลขใหญ่ = ทุน
    {} = ไม่มีค่าใหม่ (ขอดูค่า) · None = ไม่ใช่คำสั่งนี้
    """
    tokens = (text or "").split()
    if not tokens or tokens[0].lower() not in _CMD_WORDS:
        return None
    out, expect_capital = {}, False
    for tok in tokens[1:]:
        if tok.lower() in _CAPITAL_WORDS:
            expect_capital = True
            continue
        m = _NUM.match(tok)
        if not m:
            continue
        val = float(m.group(1).replace(",", ""))
        if expect_capital:
            out["capital_thb"], expect_capital = val, False
        elif m.group(2) == "%" or ("risk_pct" not in out and val <= RISK_PCT_MAX):
            out["risk_pct"] = val
        else:
            out["capital_thb"] = val
    return out


def load_settings(path=None):
    """ค่าปัจจุบัน (ไฟล์หาย/พัง → ค่าเริ่มต้น)"""
    path = path or SETTINGS_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    return {**DEFAULTS, **{k: data[k] for k in DEFAULTS if k in data}}


def update_settings(changes, path=None):
    """รวมค่าใหม่แล้วบันทึก — raise ValueError (ข้อความไทย) ถ้าค่าไม่สมเหตุสมผล"""
    path = path or SETTINGS_PATH
    current = load_settings(path)
    merged = {**current, **{k: v for k, v in changes.items() if k in DEFAULTS}}
    rp = merged.get("risk_pct")
    if rp is None or not 0 < rp <= RISK_PCT_MAX:
        raise ValueError(f"% เสี่ยงต้องอยู่ระหว่าง 0 ถึง {RISK_PCT_MAX:g} (ได้ {rp})")
    cap = merged.get("capital_thb")
    if cap is not None and cap <= 0:
        raise ValueError(f"ทุนต้องมากกว่า 0 (ได้ {cap})")
    write_json_atomic(path, merged)
    return merged


def risk_amount(settings):
    """เงินเสี่ยงต่อไม้ (บาท) = ทุน × % — None ถ้ายังไม่ตั้งทุน"""
    cap, rp = (settings or {}).get("capital_thb"), (settings or {}).get("risk_pct")
    if not cap or not rp:
        return None
    return cap * rp / 100
