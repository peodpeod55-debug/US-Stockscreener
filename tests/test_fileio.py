"""Atomic write ของไฟล์ state (bot/fileio.py)

เดิมทุก writer ใช้ path.write_text ทับตรงๆ — ไฟดับ/crash กลางคันไฟล์พังทั้งไฟล์
(signals.json คือประวัติสัญญาณถาวร เสียแล้วสถิติหายหมด) → เขียนลง .tmp
ข้างๆ ก่อนแล้ว os.replace ซึ่ง atomic บน Windows/POSIX

จำลอง crash ด้วย os.replace ที่พัง: writer ต้อง raise และไฟล์เดิมต้องไม่ถูกแตะ
"""
import json

import pytest

from bot import fileio
from bot.breakouts import record_breakouts
from bot.jobstate import claim
from bot.signals import record_signals
from bot.watchlist import save_auto_watch, save_watchlist


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


# ── write_json_atomic ───────────────────────────────────────────


def test_roundtrip_and_no_tmp_left(tmp_path):
    p = tmp_path / "data.json"
    fileio.write_json_atomic(p, {"ไทย": [1, 2]})
    assert _read(p) == {"ไทย": [1, 2]}
    assert list(tmp_path.glob("*.tmp")) == []


def test_overwrites_existing_file(tmp_path):
    p = tmp_path / "data.json"
    p.write_text("[1]", encoding="utf-8")
    fileio.write_json_atomic(p, [2])
    assert _read(p) == [2]


def _break_replace(monkeypatch):
    def boom(src, dst):
        raise OSError("simulated crash")

    monkeypatch.setattr(fileio.os, "replace", boom)


def test_broken_replace_keeps_original(tmp_path, monkeypatch):
    p = tmp_path / "data.json"
    p.write_text('["old"]', encoding="utf-8")
    _break_replace(monkeypatch)
    with pytest.raises(OSError):
        fileio.write_json_atomic(p, ["new"])
    assert _read(p) == ["old"]


# ── writer ของ state ทุกตัวต้อง crash-safe ──────────────────────


def test_record_signals_crash_safe(tmp_path, monkeypatch):
    p = tmp_path / "signals.json"
    p.write_text('[{"symbol": "OLD", "earnings_date": "2026-01-01"}]',
                 encoding="utf-8")
    _break_replace(monkeypatch)
    cand = {"symbol": "NVDA", "name": "NVIDIA", "grade": "A", "score": 90,
            "earnings_date": "2026-08-20", "timing": "amc", "dr_symbols": "",
            "levels": {"price": 100.0, "sl": 90.0}}
    with pytest.raises(OSError):
        record_signals([cand], "2026-08-21", path=p)
    assert _read(p) == [{"symbol": "OLD", "earnings_date": "2026-01-01"}]


def test_record_breakouts_crash_safe(tmp_path, monkeypatch):
    p = tmp_path / "breakouts.json"
    p.write_text('[{"symbol": "OLD", "date": "2026-01-01"}]', encoding="utf-8")
    _break_replace(monkeypatch)
    snap = {"symbol": "NVDA", "last_date": "2026-08-20",
            "new_breaks": ["high_5d"], "price": 100.0, "grade": "A"}
    with pytest.raises(OSError):
        record_breakouts([snap], path=p)
    assert _read(p) == [{"symbol": "OLD", "date": "2026-01-01"}]


def test_save_watchlist_crash_safe(tmp_path, monkeypatch):
    p = tmp_path / "watchlist.json"
    p.write_text('["OLD"]', encoding="utf-8")
    _break_replace(monkeypatch)
    with pytest.raises(OSError):
        save_watchlist(["NVDA"], path=p)
    assert _read(p) == ["OLD"]


def test_save_auto_watch_crash_safe(tmp_path, monkeypatch):
    p = tmp_path / "auto_watch.json"
    p.write_text('{"OLD": "2026-01-01"}', encoding="utf-8")
    _break_replace(monkeypatch)
    with pytest.raises(OSError):
        save_auto_watch({"NVDA": "2026-08-21"}, path=p)
    assert _read(p) == {"OLD": "2026-01-01"}


def test_claim_crash_safe(tmp_path, monkeypatch):
    p = tmp_path / "job_state.json"
    p.write_text('{"scan": "2026-08-20"}', encoding="utf-8")
    _break_replace(monkeypatch)
    with pytest.raises(OSError):
        claim("breakout", path=p)
    assert _read(p) == {"scan": "2026-08-20"}
