from datetime import date

from bot.watchlist import (
    AUTO_WATCH_DAYS,
    AUTO_WATCH_MAX,
    WATCHLIST_MAX,
    active_auto,
    add_symbols,
    all_watched,
    auto_add,
    auto_remove,
    load_auto_watch,
    load_watchlist,
    parse_watch_command,
    remove_symbols,
    save_auto_watch,
    save_watchlist,
)

TODAY = date(2026, 8, 20)


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


# ── auto-watch (หุ้น A/B จากสแกน ติดตามอัตโนมัติ 30 วัน) ──────────

def _paths(tmp_path):
    return tmp_path / "auto_watch.json", tmp_path / "watchlist.json"


def test_auto_add_records_date(tmp_path):
    auto_p, manual_p = _paths(tmp_path)
    added = auto_add(["WMT", "TGT"], auto_p, manual_p, today=TODAY)
    assert added == ["WMT", "TGT"]
    assert load_auto_watch(auto_p) == {"WMT": "2026-08-20", "TGT": "2026-08-20"}


def test_auto_add_skips_manual_and_refreshes_existing(tmp_path):
    auto_p, manual_p = _paths(tmp_path)
    add_symbols(["NVDA"], manual_p)                       # ติดตามเองอยู่แล้ว
    save_auto_watch({"WMT": "2026-08-01"}, auto_p)        # auto อยู่แล้ว
    added = auto_add(["NVDA", "WMT", "TGT"], auto_p, manual_p, today=TODAY)
    assert added == ["TGT"]                               # ตัวใหม่จริงตัวเดียว
    data = load_auto_watch(auto_p)
    assert data["WMT"] == "2026-08-20"                    # ติด A/B ซ้ำ → ต่ออายุ
    assert "NVDA" not in data


def test_active_auto_drops_expired(tmp_path):
    auto_p, _ = _paths(tmp_path)
    save_auto_watch({
        "OLD": (TODAY.fromordinal(TODAY.toordinal() - AUTO_WATCH_DAYS - 1)).isoformat(),
        "KEEP": (TODAY.fromordinal(TODAY.toordinal() - AUTO_WATCH_DAYS)).isoformat(),
    }, auto_p)
    assert list(active_auto(auto_p, today=TODAY)) == ["KEEP"]


def test_auto_add_cap_evicts_oldest(tmp_path):
    auto_p, manual_p = _paths(tmp_path)
    # ทุกตัวยังไม่หมดอายุ (ภายใน 30 วัน) — เช็คเรื่องเพดานล้วนๆ
    data = {f"S{i}": f"2026-08-{i + 1:02d}" for i in range(AUTO_WATCH_MAX)}
    save_auto_watch(data, auto_p)
    auto_add(["NEW"], auto_p, manual_p, today=TODAY)
    result = load_auto_watch(auto_p)
    assert len(result) == AUTO_WATCH_MAX
    assert "NEW" in result and "S0" not in result         # ตัวเก่าสุดหลุด


def test_auto_remove(tmp_path):
    auto_p, _ = _paths(tmp_path)
    save_auto_watch({"WMT": "2026-08-20"}, auto_p)
    assert auto_remove(["WMT", "XXX"], auto_p) == ["WMT"]
    assert load_auto_watch(auto_p) == {}


def test_all_watched_union_dedup(tmp_path):
    auto_p, manual_p = _paths(tmp_path)
    add_symbols(["NVDA", "WMT"], manual_p)
    save_auto_watch({
        "WMT": "2026-08-20",                              # ซ้ำกับ manual
        "TGT": "2026-08-20",
        "OLD": "2026-01-01",                              # หมดอายุ
    }, auto_p)
    assert all_watched(manual_p, auto_p, today=TODAY) == ["NVDA", "WMT", "TGT"]
