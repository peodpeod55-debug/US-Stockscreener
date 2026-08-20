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


def base_scan(candidates, skipped=None, pending=None):
    return {"from_date": "2026-08-18", "to_date": "2026-08-20",
            "universe_size": 529, "reported_symbols": ["AAPL"],
            "candidates": candidates,
            "skipped_counts": skipped or {"C": 0, "D": 0},
            "pending": pending or [],
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


def test_pending_shown():
    pending = [{"symbol": "WMT", "date": "2026-08-20", "timing": "bmo"},
               {"symbol": "TGT", "date": "2026-08-19", "timing": "unknown"}]
    msgs = format_scan(base_scan([], pending=pending))
    text = "\n".join(msgs)
    assert "รอวันตอบรับ" in text
    assert "WMT" in text and "TGT" in text


def test_split_long_messages():
    many = [make_candidate(symbol=f"SYM{i}") for i in range(40)]
    msgs = format_scan(base_scan(many))
    assert all(len(m) <= 3800 for m in msgs)
    assert len(msgs) >= 2
