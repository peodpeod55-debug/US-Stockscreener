import json
from datetime import date

from bot.formatter import format_weekly
from bot.weekly import build_weekly_items, collect_signals, evaluate_signal

TODAY = date(2026, 8, 20)


def _write_report(dirpath, stamp, to_date, candidates):
    data = {"to_date": to_date, "candidates": candidates}
    (dirpath / f"scan_{stamp}.json").write_text(
        json.dumps(data), encoding="utf-8")


def _cand(symbol, price, sl=95.0, earnings_date="2026-08-01", **over):
    c = {"symbol": symbol, "name": f"{symbol} Corp", "grade": "A",
         "score": 88.0, "earnings_date": earnings_date, "dr_symbols": "",
         "levels": {"price": price, "sl": sl}}
    c.update(over)
    return c


# ── collect_signals ──────────────────────────────────────────────

def test_collect_dedup_keeps_earliest_flag(tmp_path):
    # หุ้นเดิมโผล่สองสแกน (lookback ทับกัน) → นับครั้งแรกที่แจ้ง
    _write_report(tmp_path, "2026-08-05_083000", "2026-08-05", [_cand("NVDA", 100.0)])
    _write_report(tmp_path, "2026-08-06_083000", "2026-08-06", [_cand("NVDA", 104.0)])
    sigs = collect_signals(tmp_path, today=TODAY)
    assert len(sigs) == 1
    assert sigs[0]["flag_date"] == "2026-08-05"
    assert sigs[0]["flag_price"] == 100.0
    assert sigs[0]["sl"] == 95.0
    assert sigs[0]["grade"] == "A"


def test_collect_same_symbol_new_earnings_round_is_new_signal(tmp_path):
    _write_report(tmp_path, "2026-08-01_083000", "2026-08-01",
                  [_cand("NVDA", 100.0, earnings_date="2026-07-30")])
    _write_report(tmp_path, "2026-08-15_083000", "2026-08-15",
                  [_cand("NVDA", 120.0, earnings_date="2026-08-14")])
    assert len(collect_signals(tmp_path, today=TODAY)) == 2


def test_collect_skips_scans_older_than_window(tmp_path):
    _write_report(tmp_path, "2026-07-01_083000", "2026-07-01", [_cand("OLD", 50.0)])
    _write_report(tmp_path, "2026-08-10_083000", "2026-08-10", [_cand("NEW", 60.0)])
    sigs = collect_signals(tmp_path, today=TODAY)
    assert [s["symbol"] for s in sigs] == ["NEW"]


def test_collect_tolerates_bad_file_and_empty_dir(tmp_path):
    (tmp_path / "scan_2026-08-10_083000.json").write_text("พัง", encoding="utf-8")
    assert collect_signals(tmp_path, today=TODAY) == []
    assert collect_signals(tmp_path / "ไม่มีจริง", today=TODAY) == []


# ── evaluate_signal ──────────────────────────────────────────────

def _sig(**over):
    s = {"symbol": "NVDA", "name": "NVDA Corp", "grade": "A", "score": 88.0,
         "earnings_date": "2026-08-01", "flag_date": "2026-08-05",
         "flag_price": 100.0, "sl": 95.0, "dr_symbols": ""}
    s.update(over)
    return s


def _bar(d, close, low=None):
    return {"date": d, "open": close, "high": close + 1,
            "low": low if low is not None else close - 1,
            "close": close, "volume": 1_000_000}


def test_evaluate_pct_and_days():
    prices = [_bar("2026-08-19", 110.0), _bar("2026-08-18", 108.0),
              _bar("2026-08-05", 100.0)]
    ev = evaluate_signal(_sig(), prices)
    assert ev["price_now"] == 110.0
    assert round(ev["pct"], 2) == 10.0
    assert ev["days"] == 14          # 2026-08-05 → 2026-08-19
    assert ev["sl_hit"] is None


def test_evaluate_sl_hit_reports_first_date():
    prices = [_bar("2026-08-19", 110.0),
              _bar("2026-08-12", 96.0, low=94.0),   # หลุดอีกวัน (ทีหลัง)
              _bar("2026-08-08", 97.0, low=94.5),   # หลุดครั้งแรก
              _bar("2026-08-05", 100.0, low=99.0)]  # วันแจ้ง — ไม่นับ
    ev = evaluate_signal(_sig(sl=95.0), prices)
    assert ev["sl_hit"] == "2026-08-08"


def test_evaluate_no_prices_returns_none():
    assert evaluate_signal(_sig(), None) is None
    assert evaluate_signal(_sig(), []) is None


# ── build_weekly_items ───────────────────────────────────────────

def test_build_weekly_items_end_to_end(tmp_path):
    _write_report(tmp_path, "2026-08-05_083000", "2026-08-05", [_cand("NVDA", 100.0)])
    prices = {"NVDA": [_bar("2026-08-19", 110.0), _bar("2026-08-05", 100.0)]}

    def get_prices(sym):
        if sym == "BAD":
            raise RuntimeError("boom")
        return prices.get(sym)

    items = build_weekly_items(tmp_path, get_prices, today=TODAY)
    assert len(items) == 1
    assert items[0]["symbol"] == "NVDA"
    assert round(items[0]["pct"], 2) == 10.0


# ── format_weekly ────────────────────────────────────────────────

def _item(**over):
    it = {**_sig(), "price_now": 110.0, "pct": 10.0, "days": 14, "sl_hit": None}
    it.update(over)
    return it


def test_format_weekly_message():
    msg = format_weekly([
        _item(),
        _item(symbol="WMT", grade="B", flag_price=50.0, price_now=49.0, pct=-2.0),
    ])
    assert "สรุปผล" in msg
    assert "NVDA" in msg and "+10.0%" in msg and "110.00" in msg
    assert "WMT" in msg and "-2.0%" in msg
    assert "เฉลี่ย +4.0%" in msg      # (10 - 2) / 2
    assert "บวก 1/2" in msg


def test_format_weekly_sl_marker():
    msg = format_weekly([_item(sl_hit="2026-08-08", sl=95.0)])
    assert "🛑" in msg and "2026-08-08" in msg


def test_format_weekly_empty_returns_none():
    assert format_weekly([]) is None
