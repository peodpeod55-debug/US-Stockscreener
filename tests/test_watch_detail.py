from bot.formatter import format_watch_detail


def _snap(**over):
    base = {
        "symbol": "NVDA", "name": "NVIDIA Corp", "price": 183.2,
        "day_change_pct": 1.2, "grade": "A", "pending_reaction": False,
        "levels": {
            "price": 183.2,
            "high_5d": 176.1, "pct_vs_high_5d": 4.03,
            "high_3m": 181.4, "pct_vs_high_3m": 0.99,
            "sl": 171.4, "sl_pct": 6.44,
            "low_5d": 168.2, "pct_vs_low_5d": 8.92,
        },
    }
    base.update(over)
    return base


def test_manual_stock_levels_rendered():
    msg = format_watch_detail([("NVDA", _snap())])
    assert "👀" in msg and "1 ตัว" in msg
    assert "NVDA" in msg and "183.20" in msg
    assert "H5d 176.10 ✅" in msg and "H3m 181.40 ✅" in msg
    assert "SL 171.40" in msg
    assert "Low ก่อนงบ 168.20" in msg and "🛑" not in msg


def test_high_not_broken_shows_distance():
    lv = dict(_snap()["levels"], pct_vs_high_5d=-3.7, pct_vs_high_3m=-8.1)
    msg = format_watch_detail([("NVDA", _snap(levels=lv))])
    assert "อีก 3.7%" in msg and "อีก 8.1%" in msg


def test_low_broken_flagged():
    lv = dict(_snap()["levels"], price=160.0, pct_vs_low_5d=-4.88)
    msg = format_watch_detail([("NVDA", _snap(price=160.0, levels=lv))])
    assert "🛑" in msg and "หลุดแล้ว" in msg


def test_fetch_failed_shows_warning():
    msg = format_watch_detail([("HD", None)])
    assert "HD" in msg and "⚠️" in msg


def test_pending_reaction_shown():
    msg = format_watch_detail(
        [("WMT", _snap(symbol="WMT", levels=None, pending_reaction=True))])
    assert "⏳" in msg and "รอวันตอบรับงบ" in msg


def test_no_recent_earnings_note():
    msg = format_watch_detail(
        [("KO", _snap(symbol="KO", grade=None, levels=None))])
    assert "KO" in msg and "ไม่มีงบใน 60 วัน" in msg


def test_auto_section_with_date():
    msg = format_watch_detail(
        [("NVDA", _snap()), ("ABEO", _snap(symbol="ABEO", grade="B"))],
        auto_dates={"ABEO": "2026-08-15"})
    assert "🤖" in msg and "2026-08-15" in msg
    # manual อยู่ก่อน auto
    assert msg.index("NVDA") < msg.index("🤖") < msg.index("ABEO")


def test_empty_returns_none():
    assert format_watch_detail([]) is None
