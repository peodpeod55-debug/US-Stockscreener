from datetime import date

from bot.signals import load_signals, record_signals, signals_since

TODAY = date(2026, 8, 20)


def _cand(symbol, price, sl=95.0, earnings_date="2026-08-01", **over):
    c = {"symbol": symbol, "name": f"{symbol} Corp", "grade": "A",
         "score": 88.0, "earnings_date": earnings_date, "timing": "amc",
         "dr_symbols": "", "levels": {"price": price, "sl": sl}}
    c.update(over)
    return c


# ── record_signals ───────────────────────────────────────────────

def test_record_appends_and_persists(tmp_path):
    p = tmp_path / "signals.json"
    new = record_signals([_cand("NVDA", 100.0)], "2026-08-05", path=p)
    assert [s["symbol"] for s in new] == ["NVDA"]
    sigs = load_signals(p)
    assert len(sigs) == 1
    assert sigs[0]["flag_date"] == "2026-08-05"
    assert sigs[0]["flag_price"] == 100.0
    assert sigs[0]["sl"] == 95.0
    assert sigs[0]["grade"] == "A"
    assert sigs[0]["earnings_date"] == "2026-08-01"


def test_record_dedup_keeps_first_flag(tmp_path):
    # หุ้นเดิมรอบงบเดิมโผล่สแกนซ้ำ (lookback ทับกัน) → นับครั้งแรกที่แจ้ง
    p = tmp_path / "signals.json"
    record_signals([_cand("NVDA", 100.0)], "2026-08-05", path=p)
    new = record_signals([_cand("NVDA", 104.0)], "2026-08-06", path=p)
    assert new == []
    sigs = load_signals(p)
    assert len(sigs) == 1
    assert sigs[0]["flag_date"] == "2026-08-05"
    assert sigs[0]["flag_price"] == 100.0


def test_record_same_symbol_new_earnings_round_is_new_signal(tmp_path):
    p = tmp_path / "signals.json"
    record_signals([_cand("NVDA", 100.0, earnings_date="2026-05-01")],
                   "2026-05-05", path=p)
    new = record_signals([_cand("NVDA", 120.0, earnings_date="2026-08-01")],
                         "2026-08-05", path=p)
    assert [s["symbol"] for s in new] == ["NVDA"]
    assert len(load_signals(p)) == 2


def test_record_skips_candidate_without_price(tmp_path):
    p = tmp_path / "signals.json"
    bad = _cand("XXX", None)
    bad["levels"] = {"price": None, "sl": None}
    assert record_signals([bad], "2026-08-05", path=p) == []
    assert load_signals(p) == []


# ── load_signals ─────────────────────────────────────────────────

def test_load_missing_or_corrupt_file(tmp_path):
    assert load_signals(tmp_path / "ไม่มี.json") == []
    p = tmp_path / "signals.json"
    p.write_text("พัง", encoding="utf-8")
    assert load_signals(p) == []


# ── signals_since ────────────────────────────────────────────────

def test_signals_since_filters_old_flags(tmp_path):
    p = tmp_path / "signals.json"
    record_signals([_cand("OLD", 50.0, earnings_date="2026-06-25")],
                   "2026-07-01", path=p)
    record_signals([_cand("NEW", 60.0, earnings_date="2026-08-08")],
                   "2026-08-10", path=p)
    sigs = signals_since(30, path=p, today=TODAY)
    assert [s["symbol"] for s in sigs] == ["NEW"]
