from bot.watchlist import (
    WATCHLIST_MAX,
    add_symbols,
    load_watchlist,
    parse_watch_command,
    remove_symbols,
    save_watchlist,
)


# ── parse_watch_command ──────────────────────────────────────────

def test_parse_show():
    assert parse_watch_command("ติดตาม") == ("show", [])
    assert parse_watch_command("  ติดตาม  ") == ("show", [])


def test_parse_add():
    assert parse_watch_command("ติดตาม NVDA") == ("add", ["NVDA"])
    assert parse_watch_command("ติดตาม nvda tsla") == ("add", ["NVDA", "TSLA"])


def test_parse_add_no_space():
    # ผู้ใช้ไทยมักพิมพ์ติดกัน
    assert parse_watch_command("ติดตามNVDA") == ("add", ["NVDA"])


def test_parse_remove():
    assert parse_watch_command("เลิกติดตาม NVDA") == ("remove", ["NVDA"])
    assert parse_watch_command("เลิกติดตาม") == ("remove", [])


def test_parse_not_a_command():
    assert parse_watch_command("NVDA TSLA") is None
    assert parse_watch_command("สวัสดีครับ") is None
    assert parse_watch_command("") is None


# ── load / save ──────────────────────────────────────────────────

def test_load_missing_file(tmp_path):
    assert load_watchlist(tmp_path / "watchlist.json") == []


def test_save_load_roundtrip(tmp_path):
    p = tmp_path / "watchlist.json"
    save_watchlist(["NVDA", "TSLA"], p)
    assert load_watchlist(p) == ["NVDA", "TSLA"]


def test_load_corrupt_file(tmp_path):
    p = tmp_path / "watchlist.json"
    p.write_text("ไม่ใช่ json", encoding="utf-8")
    assert load_watchlist(p) == []


# ── add_symbols ──────────────────────────────────────────────────

def test_add_new_symbols(tmp_path):
    p = tmp_path / "watchlist.json"
    result = add_symbols(["NVDA", "TSLA"], p)
    assert result == {"added": ["NVDA", "TSLA"], "already": [], "full": []}
    assert load_watchlist(p) == ["NVDA", "TSLA"]


def test_add_duplicate_reports_already(tmp_path):
    p = tmp_path / "watchlist.json"
    add_symbols(["NVDA"], p)
    result = add_symbols(["NVDA", "AAPL"], p)
    assert result == {"added": ["AAPL"], "already": ["NVDA"], "full": []}
    assert load_watchlist(p) == ["NVDA", "AAPL"]


def test_add_respects_cap(tmp_path):
    p = tmp_path / "watchlist.json"
    add_symbols([f"S{i}" for i in range(WATCHLIST_MAX)], p)
    result = add_symbols(["OVER"], p)
    assert result == {"added": [], "already": [], "full": ["OVER"]}
    assert len(load_watchlist(p)) == WATCHLIST_MAX


# ── remove_symbols ───────────────────────────────────────────────

def test_remove_symbols(tmp_path):
    p = tmp_path / "watchlist.json"
    add_symbols(["NVDA", "TSLA"], p)
    result = remove_symbols(["NVDA", "AAPL"], p)
    assert result == {"removed": ["NVDA"], "missing": ["AAPL"]}
    assert load_watchlist(p) == ["TSLA"]
