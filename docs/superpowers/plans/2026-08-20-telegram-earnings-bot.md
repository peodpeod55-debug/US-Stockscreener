# Telegram Earnings Screener Bot — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Telegram bot ที่สแกนหุ้น US (DR ∪ S&P500 = 529 ตัว) หา "อาการหลังงบดี" ด้วย 5-factor score + levels แบบ SET screener เดิม ส่ง push อ–ส 08:30 ไทย และรับคำสั่ง /scan

**Architecture:** โปรเซสเดียวใช้ python-telegram-bot v22.7 (long polling + JobQueue) core scan เป็นฟังก์ชัน sync แชร์กันระหว่าง daily job กับ /scan, vendor โมดูล scoring จาก earnings-trade-analyzer skill เข้า `bot/vendor/eta/`

**Tech Stack:** Python 3.14, python-telegram-bot[job-queue] 22.7, python-dotenv, requests, pytest, FMP API

**Spec:** `docs/superpowers/specs/2026-08-20-telegram-earnings-bot-design.md`

## Global Constraints

- Universe: `us_stock_list.csv` แถวที่ `dr == "Y"` OR `"SP500" in index`
- แจ้งเตือนเฉพาะเกรด A (score ≥ 85) และ B (70–84); นับ C/D เป็นสรุปท้ายข้อความ
- Reaction day (D0): BMO → earnings_date, AMC/unknown → วันซื้อขายถัดไป (convention เดียวกับ gap_size_calculator)
- daily_prices ทุกที่ = list[dict] **most-recent-first** คีย์ `date,open,high,low,close,volume`
- FMP budget ≤ 200 calls/รอบ · Telegram message ≤ 3800 chars/ฉบับ (กัน limit 4096)
- Secrets อยู่ใน `.env` (gitignored) — ห้าม hardcode/print token
- ทุก path ในโค้ด resolve จาก project root (`Path(__file__).resolve().parents[1]`) ไม่พึ่ง cwd

---

### Task 1: Vendor eta modules + vendored tests เขียว

**Files:**
- Create: `bot/__init__.py`, `bot/vendor/__init__.py` (ว่าง)
- Create: `bot/vendor/eta/` (คัดลอกทั้ง scripts dir ของ skill)
- Create: `conftest.py` (project root)

**Interfaces:**
- Produces: import ได้หลังใส่ `bot/vendor/eta` ใน sys.path — `from analyze_earnings_trades import analyze_stock, normalize_timing`, `from fmp_client import FMPClient, ApiCallBudgetExceeded`, `from scorer import calculate_composite_score`

- [ ] **Step 1: คัดลอกไฟล์**

```powershell
$src = "C:\Users\LEVEL51PC\.claude\skills\earnings-trade-analyzer\scripts"
$dst = "C:\Users\LEVEL51PC\Desktop\US Stock Screener\bot\vendor\eta"
New-Item -ItemType Directory -Force $dst | Out-Null
Copy-Item "$src\*" $dst -Recurse -Exclude "__pycache__"
Get-ChildItem $dst -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
New-Item -ItemType File "C:\Users\LEVEL51PC\Desktop\US Stock Screener\bot\__init__.py" | Out-Null
New-Item -ItemType File "C:\Users\LEVEL51PC\Desktop\US Stock Screener\bot\vendor\__init__.py" | Out-Null
```

- [ ] **Step 2: conftest.py ที่ root**

```python
import sys
from pathlib import Path

ETA_DIR = Path(__file__).resolve().parent / "bot" / "vendor" / "eta"
sys.path.insert(0, str(ETA_DIR))
```

- [ ] **Step 3: รัน vendored tests**

Run: `python -m pytest "bot/vendor/eta/tests" -q`
Expected: PASS ทั้งหมด (ถ้าไฟล์ test เดิมพึ่ง conftest ภายใน ให้รันจาก root ที่มี conftest ใหม่)

- [ ] **Step 4: Commit**

`git add -A && git commit -m "chore: vendor earnings-trade-analyzer modules"`

---

### Task 2: config.py + .env.example + requirements.txt

**Files:**
- Create: `bot/config.py`, `.env.example`, `requirements.txt`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `load_config(env_path: Path | None = None) -> Config`; dataclass `Config(telegram_token: str, chat_id: str, fmp_api_key: str, lookback_days: int = 2, max_api_calls: int = 200)`; raise `ValueError` ระบุ key ที่ขาด

- [ ] **Step 1: Failing test** — `tests/test_config.py`

```python
import pytest
from bot.config import load_config


def test_load_config_from_env(tmp_path, monkeypatch):
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "FMP_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    env = tmp_path / ".env"
    env.write_text(
        "TELEGRAM_BOT_TOKEN=tok123\nTELEGRAM_CHAT_ID=111\nFMP_API_KEY=fmp456\n"
    )
    cfg = load_config(env)
    assert cfg.telegram_token == "tok123"
    assert cfg.chat_id == "111"
    assert cfg.fmp_api_key == "fmp456"
    assert cfg.lookback_days == 2


def test_load_config_missing_raises(tmp_path, monkeypatch):
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "FMP_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    env = tmp_path / ".env"
    env.write_text("TELEGRAM_BOT_TOKEN=tok\n")
    with pytest.raises(ValueError, match="TELEGRAM_CHAT_ID"):
        load_config(env)
```

- [ ] **Step 2: รันให้ fail** — `python -m pytest tests/test_config.py -q` → FAIL (module ไม่มี)

- [ ] **Step 3: Implement** — `bot/config.py`

```python
"""อ่าน config จาก .env / environment variables"""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Config:
    telegram_token: str
    chat_id: str
    fmp_api_key: str
    lookback_days: int = 2
    max_api_calls: int = 200


def load_config(env_path: Path | None = None) -> Config:
    load_dotenv(env_path or PROJECT_ROOT / ".env")
    required = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "FMP_API_KEY"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise ValueError(f"missing config keys: {', '.join(missing)}")
    return Config(
        telegram_token=os.environ["TELEGRAM_BOT_TOKEN"],
        chat_id=os.environ["TELEGRAM_CHAT_ID"],
        fmp_api_key=os.environ["FMP_API_KEY"],
        lookback_days=int(os.environ.get("SCAN_LOOKBACK_DAYS", "2")),
        max_api_calls=int(os.environ.get("MAX_API_CALLS", "200")),
    )
```

`.env.example`:

```
TELEGRAM_BOT_TOKEN=123456:ABC-your-token
TELEGRAM_CHAT_ID=123456789
FMP_API_KEY=your-fmp-key
```

`requirements.txt`:

```
python-telegram-bot[job-queue]>=22.7
python-dotenv>=1.0
requests>=2.31
pytest>=8.0
```

- [ ] **Step 4: รันให้ผ่าน** — `python -m pytest tests/test_config.py -q` → PASS

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: config loader"`

---

### Task 3: levels.py — ระดับราคาแบบ SET screener เดิม

**Files:**
- Create: `bot/levels.py`
- Test: `tests/test_levels.py`

**Interfaces:**
- Consumes: daily_prices most-recent-first (Global Constraints)
- Produces: `compute_levels(daily_prices: list[dict], earnings_date: str, timing: str) -> dict | None` คืน None ถ้าหา D0 ไม่เจอ; คืน dict คีย์: `reaction_date, price, high_5d, pct_vs_high_5d, high_3m, pct_vs_high_3m, prev_week_high, broke_prev_week_high, new_high_count_10d, sl, sl_pct, vol_ratio` (ค่า float/None; pct เป็น % บวก = ทะลุแล้ว/ลบ = ยังไม่ถึง; `sl_pct` = % ห่างลงไปจากราคา; `vol_ratio` = volume D0 / avg 20 วันก่อน D0)

- [ ] **Step 1: Failing tests** — `tests/test_levels.py` (สร้าง synthetic series วันจันทร์–ศุกร์ต่อเนื่อง)

```python
from datetime import date, timedelta

from bot.levels import compute_levels


def make_prices(n=120, start_price=100.0):
    """สร้าง daily bars ย้อนหลัง n วันทำการ (จบที่ 2026-08-19) ราคาขึ้นวันละ 0.1"""
    bars = []
    d = date(2026, 8, 19)
    price = start_price
    while len(bars) < n:
        if d.weekday() < 5:
            bars.append({
                "date": d.isoformat(),
                "open": price, "high": price + 1.0, "low": price - 1.0,
                "close": price, "volume": 1_000_000,
            })
            price -= 0.1  # ย้อนหลัง = ราคาลดลง (มองไปข้างหน้าคือขึ้น)
        d -= timedelta(days=1)
    return bars  # most-recent-first


def test_compute_levels_basic():
    bars = make_prices()
    # งบ AMC วันที่ index 3 → D0 = index 2
    earnings_date = bars[3]["date"]
    lv = compute_levels(bars, earnings_date, "amc")
    assert lv is not None
    assert lv["reaction_date"] == bars[2]["date"]
    assert lv["price"] == bars[0]["close"]
    # high 5 วันก่อน D0 = max high ของ index 3..7
    assert lv["high_5d"] == max(b["high"] for b in bars[3:8])
    # high 3 เดือน (63 วัน) ก่อน D0 = max high ของ index 3..65
    assert lv["high_3m"] == max(b["high"] for b in bars[3:66])
    # SL = low ของ D0
    assert lv["sl"] == bars[2]["low"]
    assert lv["sl_pct"] > 0
    assert lv["vol_ratio"] == 1.0


def test_compute_levels_bmo_reaction_is_earnings_date():
    bars = make_prices()
    earnings_date = bars[2]["date"]
    lv = compute_levels(bars, earnings_date, "bmo")
    assert lv["reaction_date"] == earnings_date


def test_compute_levels_missing_date_returns_none():
    bars = make_prices()
    assert compute_levels(bars, "1999-01-01", "amc") is None


def test_new_high_count_uptrend():
    # ซีรีส์ราคาขึ้นตลอด → ทุกวันใน 10 วันล่าสุดเป็น new 3M high
    bars = make_prices()
    earnings_date = bars[5]["date"]
    lv = compute_levels(bars, earnings_date, "amc")
    assert lv["new_high_count_10d"] == 10


def test_prev_week_high_present():
    bars = make_prices()
    lv = compute_levels(bars, bars[3]["date"], "amc")
    # 2026-08-19 คือวันพุธ → สัปดาห์ก่อน = 10–14 ส.ค.
    assert lv["prev_week_high"] is not None
    assert isinstance(lv["broke_prev_week_high"], bool)
```

- [ ] **Step 2: รันให้ fail** — `python -m pytest tests/test_levels.py -q` → FAIL

- [ ] **Step 3: Implement** — `bot/levels.py`

```python
"""คำนวณระดับราคา (levels) สืบทอดจาก SET Earnings Breakout Screener"""
from datetime import date, timedelta


def _find_index(daily_prices, target_date):
    for i, bar in enumerate(daily_prices):
        if bar.get("date") == target_date:
            return i
    return -1


def _pct_vs(price, level):
    if not level:
        return None
    return round((price - level) / level * 100, 2)


def compute_levels(daily_prices, earnings_date, timing):
    earn_idx = _find_index(daily_prices, earnings_date)
    if earn_idx == -1:
        return None

    # D0: bmo → วันงบ, amc/unknown → วันซื้อขายถัดไป (index - 1)
    d0 = earn_idx if (timing or "").lower() == "bmo" else earn_idx - 1
    if d0 < 0:
        return None  # งบ AMC เพิ่งออก ยังไม่มีวันตอบรับ

    price = daily_prices[0]["close"]
    pre = daily_prices[d0 + 1:]  # วันก่อน D0 ทั้งหมด

    high_5d = max((b["high"] for b in pre[:5]), default=None)
    high_3m = max((b["high"] for b in pre[:63]), default=None)

    # สัปดาห์ (จ–ศ) ที่จบล่าสุดก่อนสัปดาห์ของ bar ล่าสุด
    last_d = date.fromisoformat(daily_prices[0]["date"])
    prev_week = (last_d - timedelta(days=7)).isocalendar()[:2]
    prev_week_high = max(
        (b["high"] for b in daily_prices
         if date.fromisoformat(b["date"]).isocalendar()[:2] == prev_week),
        default=None,
    )

    # ความถี่ทำไฮใหม่: วันใน 10 วันล่าสุดที่ close > max high ของ 63 วันก่อนหน้า
    new_high_count = 0
    for i in range(min(10, len(daily_prices))):
        prior = daily_prices[i + 1: i + 64]
        if len(prior) >= 20 and daily_prices[i]["close"] > max(b["high"] for b in prior):
            new_high_count += 1

    sl = daily_prices[d0]["low"]
    sl_pct = round((price - sl) / price * 100, 2) if price else None

    vols = [b["volume"] for b in pre[:20]]
    avg20 = sum(vols) / len(vols) if vols else 0
    vol_ratio = round(daily_prices[d0]["volume"] / avg20, 2) if avg20 else None

    return {
        "reaction_date": daily_prices[d0]["date"],
        "price": round(price, 2),
        "high_5d": high_5d,
        "pct_vs_high_5d": _pct_vs(price, high_5d),
        "high_3m": high_3m,
        "pct_vs_high_3m": _pct_vs(price, high_3m),
        "prev_week_high": prev_week_high,
        "broke_prev_week_high": (price > prev_week_high) if prev_week_high else None,
        "new_high_count_10d": new_high_count,
        "sl": sl,
        "sl_pct": sl_pct,
        "vol_ratio": vol_ratio,
    }
```

- [ ] **Step 4: รันให้ผ่าน** — `python -m pytest tests/test_levels.py -q` → PASS

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: price levels calculator"`

---

### Task 4: screener.py — universe + orchestration

**Files:**
- Create: `bot/screener.py`
- Test: `tests/test_screener.py`

**Interfaces:**
- Consumes: `compute_levels` (Task 3), `Config` (Task 2), vendored `FMPClient`, `analyze_stock`, `normalize_timing`
- Produces:
  - `load_universe(csv_path: Path) -> dict[str, dict]` — ticker → `{"name": str, "sector": str, "dr_symbols": str}`
  - `run_scan(config: Config, lookback_days: int | None = None, client=None) -> dict` — คืน `{"from_date", "to_date", "universe_size", "reported_symbols": list[str], "candidates": list[dict], "skipped_counts": {"C": int, "D": int}, "api_stats": dict}` โดย candidates เรียง score มาก→น้อย แต่ละตัวมีคีย์ `symbol, name, dr_symbols, sector, earnings_date, timing, gap_pct, score, grade, levels`
  - `save_reports(scan: dict, messages: list[str], out_dir: Path) -> tuple[Path, Path]` — เขียน JSON + .md

- [ ] **Step 1: Failing tests** — `tests/test_screener.py` (mock FMPClient)

```python
from datetime import date, timedelta
from pathlib import Path

from bot.config import Config
from bot.screener import load_universe, run_scan

ROOT = Path(__file__).resolve().parents[1]


def test_load_universe_dr_or_sp500():
    uni = load_universe(ROOT / "us_stock_list.csv")
    assert "AAPL" in uni                       # DR + SP500
    assert "ABT" in uni                        # SP500 เท่านั้น (dr=N)
    assert "AAOI" not in uni                   # ไม่มี DR ไม่อยู่ SP500
    assert uni["AAPL"]["dr_symbols"].startswith("AAPL01")
    assert 400 < len(uni) < 700


class FakeClient:
    """FMPClient ปลอม: มีหุ้น 2 ตัวออกงบ — ตัวหนึ่งใน universe อีกตัวไม่อยู่"""

    def __init__(self, calendar, prices):
        self._calendar = calendar
        self._prices = prices
        self.api_calls_made = 0

    def get_earnings_calendar(self, from_date, to_date):
        return self._calendar

    def get_historical_prices(self, symbol, days=250):
        return self._prices.get(symbol)

    def get_api_stats(self):
        return {"api_calls_made": 1}


def _uptrend_prices(n=250):
    bars, d, p = [], date(2026, 8, 19), 500.0
    while len(bars) < n:
        if d.weekday() < 5:
            bars.append({"date": d.isoformat(), "open": p, "high": p + 2,
                         "low": p - 2, "close": p, "volume": 2_000_000})
            p -= 1.5
        d -= timedelta(days=1)
    return bars


def test_run_scan_filters_to_universe_and_grades():
    bars = _uptrend_prices()
    earn_date = bars[2]["date"]
    calendar = [
        {"symbol": "AAPL", "date": earn_date, "time": "amc"},
        {"symbol": "ZZZZ", "date": earn_date, "time": "amc"},  # นอก universe
    ]
    cfg = Config(telegram_token="t", chat_id="1", fmp_api_key="k")
    scan = run_scan(cfg, lookback_days=3,
                    client=FakeClient(calendar, {"AAPL": bars}))
    assert scan["reported_symbols"] == ["AAPL"]
    all_syms = [c["symbol"] for c in scan["candidates"]]
    total = len(all_syms) + scan["skipped_counts"]["C"] + scan["skipped_counts"]["D"]
    assert total == 1
    for c in scan["candidates"]:
        assert c["grade"] in ("A", "B")
        assert c["levels"]["price"] > 0
        assert c["dr_symbols"]
```

- [ ] **Step 2: รันให้ fail** — `python -m pytest tests/test_screener.py -q` → FAIL

- [ ] **Step 3: Implement** — `bot/screener.py`

```python
"""Core scan: universe → earnings calendar → 5-factor score → levels"""
import csv
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ETA_DIR = Path(__file__).resolve().parent / "vendor" / "eta"
if str(ETA_DIR) not in sys.path:
    sys.path.insert(0, str(ETA_DIR))

from analyze_earnings_trades import analyze_stock, normalize_timing  # noqa: E402
from fmp_client import ApiCallBudgetExceeded, FMPClient  # noqa: E402

from bot.levels import compute_levels  # noqa: E402

UNIVERSE_CSV = PROJECT_ROOT / "us_stock_list.csv"
REPORTS_DIR = PROJECT_ROOT / "reports"


def load_universe(csv_path=UNIVERSE_CSV):
    universe = {}
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row.get("dr") == "Y" or "SP500" in (row.get("index") or ""):
                universe[row["ticker"]] = {
                    "name": row.get("name", row["ticker"]),
                    "sector": row.get("sector", ""),
                    "dr_symbols": (row.get("dr_symbols") or "").strip(),
                }
    return universe


def run_scan(config, lookback_days=None, client=None):
    lookback = lookback_days or config.lookback_days
    client = client or FMPClient(api_key=config.fmp_api_key,
                                 max_api_calls=config.max_api_calls)
    universe = load_universe()

    today = datetime.now()
    from_date = (today - timedelta(days=lookback)).strftime("%Y-%m-%d")
    to_date = today.strftime("%Y-%m-%d")

    calendar = client.get_earnings_calendar(from_date, to_date) or []
    seen, reported = set(), []
    for e in calendar:
        sym = e.get("symbol")
        if sym and sym in universe and sym not in seen:
            seen.add(sym)
            reported.append({"symbol": sym,
                             "date": e.get("date"),
                             "timing": normalize_timing(e.get("time"))})

    candidates, skipped = [], {"C": 0, "D": 0}
    for item in reported:
        sym = item["symbol"]
        try:
            prices = client.get_historical_prices(sym, days=250)
        except ApiCallBudgetExceeded:
            break
        if not prices or len(prices) < 70:
            continue
        analysis = analyze_stock(prices, item["date"], item["timing"])
        levels = compute_levels(prices, item["date"], item["timing"])
        if levels is None:
            continue
        grade = analysis["composite"]["grade"]
        if grade in ("C", "D"):
            skipped[grade] += 1
            continue
        candidates.append({
            "symbol": sym,
            "name": universe[sym]["name"],
            "dr_symbols": universe[sym]["dr_symbols"],
            "sector": universe[sym]["sector"],
            "earnings_date": item["date"],
            "timing": item["timing"],
            "gap_pct": analysis["gap"]["gap_pct"],
            "score": analysis["composite"]["composite_score"],
            "grade": grade,
            "levels": levels,
        })

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return {
        "from_date": from_date,
        "to_date": to_date,
        "universe_size": len(universe),
        "reported_symbols": [r["symbol"] for r in reported],
        "candidates": candidates,
        "skipped_counts": skipped,
        "api_stats": client.get_api_stats(),
    }


def save_reports(scan, messages, out_dir=REPORTS_DIR):
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    json_path = out_dir / f"scan_{stamp}.json"
    md_path = out_dir / f"scan_{stamp}.md"
    json_path.write_text(json.dumps(scan, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    md_path.write_text("\n\n---\n\n".join(messages), encoding="utf-8")
    return json_path, md_path
```

- [ ] **Step 4: รันให้ผ่าน** — `python -m pytest tests/test_screener.py -q` → PASS

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: scan orchestration over DR+SP500 universe"`

---

### Task 5: formatter.py — ข้อความ Telegram ภาษาไทย

**Files:**
- Create: `bot/formatter.py`
- Test: `tests/test_formatter.py`

**Interfaces:**
- Consumes: scan dict จาก `run_scan` (Task 4)
- Produces: `format_scan(scan: dict) -> list[str]` — อย่างน้อย 1 ข้อความ แต่ละฉบับ ≤ 3800 chars; plain text (ไม่ใช้ parse_mode)

- [ ] **Step 1: Failing tests** — `tests/test_formatter.py`

```python
from bot.formatter import format_scan


def make_candidate(symbol="AAPL", grade="A", dr="AAPL01 AAPL03"):
    return {
        "symbol": symbol, "name": "Apple Inc.", "dr_symbols": dr,
        "sector": "Technology", "earnings_date": "2026-08-17", "timing": "amc",
        "gap_pct": 4.2, "score": 88.0, "grade": grade,
        "levels": {
            "reaction_date": "2026-08-18", "price": 316.83,
            "high_5d": 310.2, "pct_vs_high_5d": 2.1,
            "high_3m": 325.0, "pct_vs_high_3m": -2.6,
            "prev_week_high": 312.0, "broke_prev_week_high": True,
            "new_high_count_10d": 4, "sl": 302.5, "sl_pct": 4.5,
            "vol_ratio": 1.8,
        },
    }


def base_scan(candidates, skipped=None):
    return {"from_date": "2026-08-18", "to_date": "2026-08-20",
            "universe_size": 529, "reported_symbols": ["AAPL"],
            "candidates": candidates,
            "skipped_counts": skipped or {"C": 0, "D": 0},
            "api_stats": {}}


def test_format_full_candidate():
    msgs = format_scan(base_scan([make_candidate()]))
    text = "\n".join(msgs)
    assert "AAPL" in text and "เกรด A" in text and "88" in text
    assert "High 5 วันก่อนงบ" in text and "✅" in text
    assert "High 3 เดือนก่อนงบ" in text and "ห่างอีก 2.6%" in text
    assert "ทำไฮใหม่" in text and "4 ครั้ง" in text
    assert "SL" in text and "302.5" in text
    assert "DR: AAPL01" in text


def test_no_dr_line_when_absent():
    msgs = format_scan(base_scan([make_candidate(dr="")]))
    assert "DR:" not in "\n".join(msgs)


def test_no_candidates_message():
    msgs = format_scan(base_scan([], skipped={"C": 2, "D": 1}))
    assert len(msgs) == 1
    assert "ไม่มีหุ้น" in msgs[0]
    assert "C=2" in msgs[0] and "D=1" in msgs[0]


def test_split_long_messages():
    many = [make_candidate(symbol=f"SYM{i}") for i in range(40)]
    msgs = format_scan(base_scan(many))
    assert all(len(m) <= 3800 for m in msgs)
    assert len(msgs) >= 2
```

- [ ] **Step 2: รันให้ fail** — `python -m pytest tests/test_formatter.py -q` → FAIL

- [ ] **Step 3: Implement** — `bot/formatter.py`

```python
"""จัดข้อความ Telegram (plain text ภาษาไทย)"""
MAX_LEN = 3800

GRADE_ICON = {"A": "🔵", "B": "🟡"}


def _level_line(label, value, pct):
    if value is None:
        return f"{label}: n/a"
    if pct is None:
        return f"{label}: {value:,.2f}"
    if pct >= 0:
        return f"{label}: {value:,.2f}  ✅ ทะลุ (+{pct}%)"
    return f"{label}: {value:,.2f}  ⬆️ ห่างอีก {abs(pct)}%"


def _format_candidate(c):
    lv = c["levels"]
    icon = GRADE_ICON.get(c["grade"], "⚪")
    lines = [
        f"{icon} {c['symbol']} — {c['name']}   [เกรด {c['grade']} · {c['score']:.0f}/100]",
        f"💰 ราคา: {lv['price']:,.2f}  (gap {c['gap_pct']:+.1f}%)",
        "📈 " + _level_line("High 5 วันก่อนงบ", lv["high_5d"], lv["pct_vs_high_5d"]),
        "🏔️ " + _level_line("High 3 เดือนก่อนงบ", lv["high_3m"], lv["pct_vs_high_3m"]),
    ]
    if lv["broke_prev_week_high"] is not None:
        mark = "✅ ทะลุแล้ว" if lv["broke_prev_week_high"] else "❌ ยังไม่ทะลุ"
        lines.append(f"🗓️ High สัปดาห์ก่อน: {lv['prev_week_high']:,.2f}  {mark}")
    lines.append(f"🔁 ทำไฮใหม่ 3M: {lv['new_high_count_10d']} ครั้งใน 10 วันล่าสุด")
    if lv["sl"] is not None:
        lines.append(f"🛑 SL (low วันงบ): {lv['sl']:,.2f}  (-{lv['sl_pct']}%)")
    if lv["vol_ratio"] is not None:
        lines.append(f"📊 Volume วันงบ: {lv['vol_ratio']}x avg 20d")
    if c["dr_symbols"]:
        lines.append(f"🇹🇭 DR: {c['dr_symbols']}")
    lines.append(f"📅 งบ: {c['earnings_date']} ({c['timing'].upper()})")
    return "\n".join(lines)


def format_scan(scan):
    skipped = scan["skipped_counts"]
    header = (
        f"📊 Earnings Screener {scan['from_date']} → {scan['to_date']}\n"
        f"Universe {scan['universe_size']} ตัว · ออกงบ {len(scan['reported_symbols'])} ตัว"
    )
    footer = f"ตกเกณฑ์: C={skipped['C']}, D={skipped['D']}"

    if not scan["candidates"]:
        return [f"{header}\n\n😴 ไม่มีหุ้นเข้าเกณฑ์เกรด A/B\n{footer}"]

    blocks = [_format_candidate(c) for c in scan["candidates"]]
    sep = "\n" + "─" * 28 + "\n"

    messages, current = [], header
    for block in blocks:
        if len(current) + len(sep) + len(block) > MAX_LEN:
            messages.append(current)
            current = block
        else:
            current = current + sep + block
    current = current + sep + footer if len(current) + len(sep) + len(footer) <= MAX_LEN else current
    messages.append(current)
    if footer not in messages[-1]:
        messages.append(footer)
    return messages
```

- [ ] **Step 4: รันให้ผ่าน** — `python -m pytest tests/test_formatter.py -q` → PASS

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: Thai Telegram message formatter"`

---

### Task 6: main.py + get_chat_id.py + deployment files

**Files:**
- Create: `bot/main.py`, `bot/get_chat_id.py`, `run_bot.bat`, `setup_task.ps1`, `README.md`

**Interfaces:**
- Consumes: `load_config`, `run_scan`, `format_scan`, `save_reports`
- Produces: process ที่รันด้วย `python -m bot.main`

- [ ] **Step 1: Implement** — `bot/main.py`

```python
"""Telegram bot entry: /scan /help + daily push อ–ส 08:30 Asia/Bangkok"""
import asyncio
import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import (Application, CommandHandler, ContextTypes)

from bot.config import PROJECT_ROOT, load_config
from bot.formatter import format_scan
from bot.screener import run_scan, save_reports

TZ = ZoneInfo("Asia/Bangkok")
PUSH_WEEKDAYS = {1, 2, 3, 4, 5}  # อังคาร(1)–เสาร์(5) ตาม date.weekday(): จ=0

logging.basicConfig(
    filename=PROJECT_ROOT / "bot.log", level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("bot")
CONFIG = load_config()


def _authorized(update: Update) -> bool:
    return str(update.effective_chat.id) == str(CONFIG.chat_id)


async def _do_scan_and_send(bot, chat_id, lookback):
    scan = await asyncio.to_thread(run_scan, CONFIG, lookback)
    messages = format_scan(scan)
    save_reports(scan, messages)
    for msg in messages:
        await bot.send_message(chat_id=chat_id, text=msg)


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    lookback = CONFIG.lookback_days
    if context.args:
        try:
            lookback = max(1, min(30, int(context.args[0])))
        except ValueError:
            await update.message.reply_text("ใช้: /scan หรือ /scan <จำนวนวันย้อนหลัง 1-30>")
            return
    await update.message.reply_text(f"🔍 กำลังสแกนย้อนหลัง {lookback} วัน...")
    try:
        await _do_scan_and_send(context.bot, update.effective_chat.id, lookback)
    except Exception:
        logger.exception("scan failed")
        await update.message.reply_text("⚠️ สแกนล้มเหลว ดูรายละเอียดใน bot.log")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await update.message.reply_text(
        "คำสั่ง:\n"
        "/scan — สแกนย้อนหลัง 2 วัน\n"
        "/scan 7 — สแกนย้อนหลัง 7 วัน\n"
        "/help — วิธีใช้\n\n"
        "Push อัตโนมัติ: อังคาร–เสาร์ 08:30 น."
    )


async def daily_job(context: ContextTypes.DEFAULT_TYPE):
    if datetime.now(TZ).weekday() not in PUSH_WEEKDAYS:
        return
    try:
        await _do_scan_and_send(context.bot, CONFIG.chat_id, CONFIG.lookback_days)
    except Exception as e:
        logger.exception("daily job failed")
        try:
            await context.bot.send_message(
                chat_id=CONFIG.chat_id, text=f"⚠️ Daily scan ล้มเหลว: {e}")
        except Exception:
            logger.exception("error notify failed")


def main():
    app = Application.builder().token(CONFIG.telegram_token).build()
    app.add_handler(CommandHandler(["start", "help"], cmd_help))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.job_queue.run_daily(daily_job, time=time(8, 30, tzinfo=TZ))
    logger.info("bot starting")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Implement** — `bot/get_chat_id.py`

```python
"""หา chat_id: ทักหา bot ก่อน 1 ข้อความ แล้วรัน python -m bot.get_chat_id"""
import os

import requests
from dotenv import load_dotenv

from bot.config import PROJECT_ROOT

load_dotenv(PROJECT_ROOT / ".env")
token = os.environ.get("TELEGRAM_BOT_TOKEN")
if not token:
    raise SystemExit("ยังไม่ได้ใส่ TELEGRAM_BOT_TOKEN ใน .env")

resp = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=10)
updates = resp.json().get("result", [])
if not updates:
    raise SystemExit("ไม่พบข้อความ — ทักหา bot ใน Telegram ก่อน 1 ข้อความแล้วรันใหม่")
for u in updates:
    chat = (u.get("message") or {}).get("chat", {})
    if chat:
        print(f"chat_id: {chat['id']}  ({chat.get('first_name', '')} @{chat.get('username', '')})")
```

- [ ] **Step 3: deployment files**

`run_bot.bat`:

```bat
@echo off
cd /d "%~dp0"
python -m bot.main
```

`setup_task.ps1`:

```powershell
$action = New-ScheduledTaskAction -Execute "$PSScriptRoot\run_bot.bat" -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)
Register-ScheduledTask -TaskName "USEarningsScreenerBot" -Action $action -Trigger $trigger -Settings $settings -Force
Write-Host "ลงทะเบียน Task 'USEarningsScreenerBot' แล้ว — จะรันอัตโนมัติตอน logon"
```

`README.md`: วิธีติดตั้ง (pip install -r requirements.txt), สร้าง bot ผ่าน @BotFather, หา chat_id ด้วย `python -m bot.get_chat_id`, ใส่ `.env`, ทดสอบ `/scan`, ตั้ง Task Scheduler ด้วย `setup_task.ps1` — เขียนภาษาไทยตาม README ของ SET screener เดิม

- [ ] **Step 4: Sanity check** — `python -c "import bot.main"` ต้อง fail ด้วย ValueError เรื่อง missing config (ถ้ายังไม่มี .env) ถือว่า import chain ถูก; ถ้ามี .env ต้อง import ผ่าน
  จากนั้นรัน `python -m pytest -q` ทั้งหมด → PASS

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: telegram bot entry + deployment files"`

---

### Task 7: Integration — สแกนจริงด้วย FMP

**Files:**
- Modify: ไม่มี (รันทดสอบ + สร้าง `.env` ฝั่ง local)

- [ ] **Step 1: สร้าง .env จาก session env (ไม่ print ค่า)**

```powershell
$root = "C:\Users\LEVEL51PC\Desktop\US Stock Screener"
Set-Content -Path "$root\.env" -Encoding utf8 -Value @(
  "TELEGRAM_BOT_TOKEN=PENDING",
  "TELEGRAM_CHAT_ID=PENDING",
  "FMP_API_KEY=$env:FMP_API_KEY"
)
```

- [ ] **Step 2: รัน scan จริงย้อนหลัง 7 วัน (ไม่ส่ง Telegram)**

```powershell
python -c "from bot.config import Config; import os; from dotenv import load_dotenv; load_dotenv('.env'); from bot.screener import run_scan, save_reports; from bot.formatter import format_scan; cfg = Config(telegram_token='x', chat_id='x', fmp_api_key=os.environ['FMP_API_KEY']); scan = run_scan(cfg, lookback_days=7); msgs = format_scan(scan); save_reports(scan, msgs); print(msgs[0][:2000])"
```

Expected: ข้อความ header + รายการหุ้น (หรือ "ไม่มีหุ้นเข้าเกณฑ์" ถ้าช่วงนี้ไม่มีงบ) — ตรวจด้วยตาว่าตัวเลข levels สมเหตุสมผล

- [ ] **Step 3: ตรวจ reports/** — มีไฟล์ scan_*.json + scan_*.md เนื้อหาตรงกัน

- [ ] **Step 4: Commit สุดท้าย** — `git add -A && git commit -m "chore: integration verified"` (reports/ ถูก gitignore อยู่แล้ว)

---

## หลังส่งมอบ (รอ user)

1. User สร้าง bot @BotFather → ใส่ token ใน `.env`
2. ทักหา bot → `python -m bot.get_chat_id` → ใส่ chat_id ใน `.env`
3. ทดสอบ: `python -m bot.main` แล้วสั่ง `/scan` ใน Telegram
4. ตั้งรันถาวร: เปิด PowerShell ที่โฟลเดอร์โปรเจค → `.\setup_task.ps1`
