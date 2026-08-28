"""scan_log.csv — schema เดียวกับ Set screnner (scanner._append_log) + คอลัมน์ grade ท้ายสุด ให้ gem-lab อ่านไฟล์ต่อตลาด
(เทสชุดเดียวกับ HK Stock Screener — ต่างแค่ ticker US ไม่มีนามสกุล)
เขียนจาก /scanlog และสแกน 08:30 · หนึ่งแถวต่อ (scan_date, ticker) รอบหลังทับรอบก่อน · utf-8-sig เปิด Excel ได้ · เขียนไม่ได้ไม่ล้มสแกน"""
import csv
from datetime import date

from bot.scan_csv import CSV_COLUMNS, csv_row, csv_ticker, live_scores, pick_rows, record_scan_csv

THAI_HEADER = ["scan_date", "ticker", "earn_date", "reaction_pct", "reaction_vol_ratio", "since_earn_pct", "price",
               "broke_5d_high", "broke_3m_high", "days_since_new_high", "pre_earn_low", "above_pre_low", "score"]
TODAY = date(2026, 8, 28)


def _row(symbol="NVDA", earnings_date="2026-08-24", ret=5.9, vr=4.77, grade="D", skip="D", set_hit=True, set_pts=11):
    return {"symbol": symbol, "name": "X", "earnings_date": earnings_date, "d0": "2026-08-25", "ret_d0_pct": ret,
            "vol_ratio": vr, "grade": grade, "score": 47.0, "skip_reason": skip, "signal_type": None if skip else "composite",
            "set_hit": set_hit, "set_pts": set_pts}


def _scored(pts=11, **over):
    base = {"pts": pts, "stars": "⭐⭐", "ret_d0_pct": 5.9, "vol_ratio": 4.77, "since_pct": 7.12, "price": 184.52,
            "broke_5d": True, "broke_3m": True, "days_since_new_high": 0, "new_high_ratio": None,
            "weekly_hh_streak": 0, "pre_low": 170.1, "above_pre_low": True}
    return {**base, **over}


def _read(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.reader(f))


def test_columns_are_thai_schema_plus_grade_last():
    assert CSV_COLUMNS == THAI_HEADER + ["grade"]


def test_csv_ticker_is_plain_us_symbol():
    assert csv_ticker("NVDA") == "NVDA" and csv_ticker("brk.b") == "BRK.B"


def test_csv_row_values_and_formatting_match_thai():
    row = csv_row(_row(), _scored(), TODAY)
    assert row == ["2026-08-28", "NVDA", "2026-08-24", "5.90", "4.77", "7.12", "184.52", "1", "1", "0", "170.10", "1", "11", "D"]


def test_csv_row_without_live_score_falls_back_to_stored_pts_and_blanks():
    row = csv_row(_row(set_pts=9, vr=None), None, TODAY)
    assert row == ["2026-08-28", "NVDA", "2026-08-24", "5.90", "", "", "", "0", "0", "", "", "0", "9", "D"]
    assert csv_row(_row(set_pts=None), None, TODAY)[12] == ""


def test_pick_rows_set_hit_or_original_signal_only():
    rows = [_row("NVDA"),                                                    # SET เท่านั้น
            _row("CRM", grade="B", skip=None, set_hit=True, set_pts=10),     # ทั้งสอง
            _row("VEEV", grade="B", skip=None, set_hit=False, set_pts=3),    # เดิมเท่านั้น (แม้ SET ไม่ผ่านก็ลง — มี grade)
            _row("INTC", skip="down", set_hit=False, set_pts=2)]             # ไม่เข้าทั้งคู่
    assert [r["symbol"] for r in pick_rows(rows)] == ["NVDA", "CRM", "VEEV"]
    assert pick_rows([{"symbol": "AAPL", "skip_reason": "D"}]) == []          # แถวไม่มี set_hit → False


def test_live_scores_uses_bars_from_getter_and_none_when_missing():
    calls = []

    def get_bars(sym):
        calls.append(sym)
        return None
    assert live_scores([_row("NVDA"), _row("CRM")], get_bars) == {"NVDA": None, "CRM": None}
    assert calls == ["NVDA", "CRM"]


def test_record_creates_file_with_bom_header_and_rows(tmp_path):
    p = tmp_path / "scan_log.csv"
    n = record_scan_csv([(_row(), _scored()), (_row("CRM", grade="B", skip=None, set_pts=10), _scored(10))], TODAY, path=p)
    assert n == 2
    raw = p.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")                       # utf-8-sig เหมือนไทย — Excel เปิดแล้วไม่เพี้ยน
    assert b"\r\n" in raw and b"\r\r\n" not in raw               # csv.writer + newline="" → บรรทัดละ CRLF เดียว
    rows = _read(p)
    assert rows[0] == CSV_COLUMNS
    assert [r[1] for r in rows[1:]] == ["NVDA", "CRM"] and rows[2][13] == "B"


def test_record_appends_new_day_and_replaces_same_day_ticker(tmp_path):
    p = tmp_path / "scan_log.csv"
    record_scan_csv([(_row(), _scored(11))], date(2026, 8, 27), path=p)
    record_scan_csv([(_row(), _scored(9)), (_row("CRM", grade="B", skip=None), _scored(10))], TODAY, path=p)
    record_scan_csv([(_row(), _scored(10))], TODAY, path=p)         # /scanlog รอบสองวันเดียวกัน → ทับแถวของวันนั้น
    rows = _read(p)[1:]
    assert [(r[0], r[1], r[12]) for r in rows] == [("2026-08-27", "NVDA", "11"), ("2026-08-28", "CRM", "10"),
                                                   ("2026-08-28", "NVDA", "10")]


def test_record_keeps_foreign_rows_and_extra_columns_intact(tmp_path):
    """ไฟล์ที่มีแถวจากรอบก่อน (หรือแก้มือใน Excel) ต้องคงอยู่ทุกคอลัมน์ — เขียนทับเฉพาะ (scan_date, ticker) ที่ซ้ำ"""
    p = tmp_path / "scan_log.csv"
    p.write_text("﻿" + ",".join(CSV_COLUMNS) + "\r\n2026-08-20,AAPL,2026-08-13,3.00,2.00,1.00,230.00,1,0,2,220.00,1,7,C\r\n",
                 encoding="utf-8", newline="")
    record_scan_csv([(_row(), _scored())], TODAY, path=p)
    rows = _read(p)
    assert rows[1] == ["2026-08-20", "AAPL", "2026-08-13", "3.00", "2.00", "1.00", "230.00", "1", "0", "2", "220.00", "1", "7", "C"]
    assert rows[2][1] == "NVDA" and len(rows) == 3


def test_record_empty_entries_does_not_create_file(tmp_path):
    p = tmp_path / "scan_log.csv"
    assert record_scan_csv([], TODAY, path=p) == 0 and not p.exists()


def test_record_write_failure_is_swallowed(tmp_path, caplog):
    p = tmp_path / "no_such_dir" / "scan_log.csv"                  # โฟลเดอร์ไม่มี → OSError เหมือนไฟล์ถูก Excel ล็อก
    assert record_scan_csv([(_row(), _scored())], TODAY, path=p) == 0
    assert "scan_log.csv" in caplog.text
