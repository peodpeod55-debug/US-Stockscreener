"""breakouts.json — บันทึกถาวรของเหตุการณ์ทะลุแนว (ป้อน gem-lab)"""
from bot.breakouts import load_breakouts, record_breakouts


def _snap(**over):
    base = {
        "symbol": "NVDA", "name": "NVIDIA Corp", "price": 183.2,
        "last_date": "2026-08-21", "new_breaks": ["high_5d"], "grade": "A",
    }
    base.update(over)
    return base


def test_record_new_breakout(tmp_path):
    path = tmp_path / "breakouts.json"
    new = record_breakouts([_snap()], path=path)
    assert len(new) == 1
    saved = load_breakouts(path)
    assert saved == [{"symbol": "NVDA", "date": "2026-08-21",
                      "breaks": ["high_5d"], "close": 183.2, "grade": "A"}]


def test_dedup_same_symbol_and_date(tmp_path):
    path = tmp_path / "breakouts.json"
    record_breakouts([_snap()], path=path)
    new = record_breakouts([_snap(new_breaks=["high_3m"])], path=path)
    assert new == []                       # ครั้งแรกที่บันทึกชนะ
    assert len(load_breakouts(path)) == 1


def test_new_date_is_new_event(tmp_path):
    path = tmp_path / "breakouts.json"
    record_breakouts([_snap()], path=path)
    new = record_breakouts([_snap(last_date="2026-08-22",
                                  new_breaks=["high_3m"])], path=path)
    assert len(new) == 1
    assert len(load_breakouts(path)) == 2


def test_skips_snap_without_breaks(tmp_path):
    path = tmp_path / "breakouts.json"
    new = record_breakouts([_snap(new_breaks=[])], path=path)
    assert new == []
    assert load_breakouts(path) == []


def test_load_missing_or_corrupt_file(tmp_path):
    assert load_breakouts(tmp_path / "nope.json") == []
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load_breakouts(bad) == []
