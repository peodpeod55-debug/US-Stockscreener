"""คลังวันงบสะสม (earnings_calendar.json) — แหล่งวันงบรายตัวที่ไม่ต้องยิง FMP ต่อตัว

FMP stable/earnings?symbol= ตอบ 402 กับหุ้นเกือบทุกตัวในแผนฟรี → เตือนวันงบ / น่าสนใจ "งบใกล้"
/ next_earnings ใช้ไม่ได้ · ทางแก้: เก็บทุกแถวปฏิทิน (FMP รวม + NASDAQ + Finnhub) ที่บอทดึงอยู่แล้ว
ลงคลังต่อ symbol แล้วอ่านจากคลังก่อน — FMP รายตัวเหลือเป็นสำรองตอนคลังว่าง
"""
import json
from datetime import date

from bot import earnings_store as es
from bot.earnings_store import (
    KEEP_DAYS,
    SAME_EVENT_DAYS,
    backfill,
    canon,
    earnings_for,
    known_earnings,
    merge,
    refresh,
)

TODAY = date(2026, 8, 28)


def _store(tmp_path):
    return tmp_path / "earnings_calendar.json"


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


# ── canon ────────────────────────────────────────────────────────

def test_canon_unifies_share_class_separators():
    assert canon("BRK/B") == canon("BRK-B") == canon("BRK.B") == "BRK.B"
    assert canon("nvda") == "NVDA"


# ── merge ────────────────────────────────────────────────────────

def test_merge_adds_entries_keyed_by_canonical_symbol(tmp_path):
    p = _store(tmp_path)
    merge([{"symbol": "BRK/B", "date": "2026-11-02", "time": "bmo"},
           {"symbol": "nvda", "date": "2026-11-19", "time": "amc"}],
          source="nasdaq", today=TODAY, path=p)
    data = _read(p)
    assert set(data) == {"BRK.B", "NVDA"}
    assert data["BRK.B"] == [{"date": "2026-11-02", "time": "bmo",
                              "source": "nasdaq", "seen": "2026-08-28"}]


def test_merge_same_quarter_replaces_shifted_date(tmp_path):
    """วันงบเลื่อนได้ (ประมาณการ → ยืนยัน) — ห่างกัน ≤ SAME_EVENT_DAYS ถือเป็นงบเดียวกัน"""
    p = _store(tmp_path)
    merge([{"symbol": "CRM", "date": "2026-11-18", "time": None}],
          source="fmp", today=TODAY, path=p)
    merge([{"symbol": "CRM", "date": "2026-11-25", "time": None}],
          source="nasdaq", today=TODAY, path=p)
    assert [e["date"] for e in _read(p)["CRM"]] == ["2026-11-25"]
    assert SAME_EVENT_DAYS >= 7


def test_merge_keeps_known_timing_over_unknown(tmp_path):
    p = _store(tmp_path)
    merge([{"symbol": "CRM", "date": "2026-08-26", "time": "amc"}],
          source="nasdaq", today=TODAY, path=p)
    merge([{"symbol": "CRM", "date": "2026-08-26", "time": None}],
          source="fmp", today=TODAY, path=p)
    assert _read(p)["CRM"][0]["time"] == "amc"
    # ทางกลับ: unknown มาก่อน แล้ว bmo มาทีหลัง → เติมให้
    merge([{"symbol": "TGT", "date": "2026-11-18", "time": None}],
          source="fmp", today=TODAY, path=p)
    merge([{"symbol": "TGT", "date": "2026-11-18", "time": "bmo"}],
          source="finnhub", today=TODAY, path=p)
    assert _read(p)["TGT"][0]["time"] == "bmo"


def test_merge_keeps_separate_quarters(tmp_path):
    p = _store(tmp_path)
    merge([{"symbol": "TGT", "date": "2026-08-19", "time": "bmo"},
           {"symbol": "TGT", "date": "2026-11-18", "time": None}],
          source="nasdaq", today=TODAY, path=p)
    assert [e["date"] for e in _read(p)["TGT"]] == ["2026-08-19", "2026-11-18"]


def test_merge_prunes_entries_outside_keep_window(tmp_path):
    p = _store(tmp_path)
    merge([{"symbol": "OLD", "date": "2026-01-05", "time": "amc"},    # เก่าเกิน
           {"symbol": "FAR", "date": "2027-06-01", "time": "amc"},    # ไกลเกิน
           {"symbol": "OK", "date": "2026-08-19", "time": "amc"}],
          source="nasdaq", today=TODAY, path=p)
    assert set(_read(p)) == {"OK"}
    assert KEEP_DAYS >= 90


def test_merge_normalizes_timing_and_skips_bad_rows(tmp_path):
    p = _store(tmp_path)
    n = merge([{"symbol": "A", "date": "2026-09-01", "time": "AMC"},
               {"symbol": "B", "date": "2026-09-01", "time": "dmh"},   # Finnhub: ระหว่างวัน
               {"symbol": "", "date": "2026-09-01", "time": "amc"},
               {"symbol": "C", "date": None, "time": "amc"},
               {"symbol": "D"}],
              source="x", today=TODAY, path=p)
    data = _read(p)
    assert set(data) == {"A", "B"}
    assert data["A"][0]["time"] == "amc"
    assert data["B"][0]["time"] is None
    assert n == 2


def test_merge_survives_corrupt_file(tmp_path):
    p = _store(tmp_path)
    p.write_text("{not json", encoding="utf-8")
    merge([{"symbol": "A", "date": "2026-09-01", "time": "amc"}],
          source="x", today=TODAY, path=p)
    assert set(_read(p)) == {"A"}


# ── earnings_for / known_earnings ────────────────────────────────

def test_earnings_for_returns_fmp_shaped_rows_sorted(tmp_path):
    p = _store(tmp_path)
    merge([{"symbol": "TGT", "date": "2026-11-18", "time": None},
           {"symbol": "TGT", "date": "2026-08-19", "time": "bmo"}],
          source="nasdaq", today=TODAY, path=p)
    assert earnings_for("TGT", path=p) == [
        {"date": "2026-08-19", "time": "bmo"},
        {"date": "2026-11-18", "time": None},
    ]
    assert earnings_for("tgt", path=p) == earnings_for("TGT", path=p)


def test_earnings_for_unknown_symbol_or_missing_file_is_empty(tmp_path):
    p = _store(tmp_path)
    assert earnings_for("NVDA", path=p) == []
    merge([{"symbol": "TGT", "date": "2026-08-19", "time": "bmo"}],
          source="nasdaq", today=TODAY, path=p)
    assert earnings_for("NVDA", path=p) == []


def test_known_earnings_unions_store_and_signals(tmp_path):
    p = _store(tmp_path)
    merge([{"symbol": "EL", "date": "2026-11-05", "time": None}],
          source="nasdaq", today=TODAY, path=p)
    sig = [{"date": "2026-08-19", "time": "amc"}]
    assert known_earnings("EL", path=p, signals_fn=lambda s: sig) == [
        {"date": "2026-08-19", "time": "amc"},
        {"date": "2026-11-05", "time": None},
    ]


def test_known_earnings_same_event_keeps_store_date_but_takes_signal_timing(tmp_path):
    p = _store(tmp_path)
    merge([{"symbol": "EL", "date": "2026-08-19", "time": None}],
          source="fmp", today=TODAY, path=p)
    rows = known_earnings("EL", path=p,
                          signals_fn=lambda s: [{"date": "2026-08-20", "time": "amc"}])
    assert rows == [{"date": "2026-08-19", "time": "amc"}]


def test_known_earnings_default_signals_source_is_isolated_in_tests(tmp_path):
    # conftest ชี้ทั้ง STORE_PATH และ SIGNALS_PATH ไป tmp → ต้องว่าง ไม่เห็น EL/TGT จริง
    assert known_earnings("EL") == []
    assert es.STORE_PATH.parent == es.STORE_PATH.parent  # sanity: attribute มีอยู่


# ── default_sources ──────────────────────────────────────────────

def test_default_sources_without_finnhub_key():
    from bot.earnings_store import default_sources

    class Client:
        def get_earnings_calendar(self, f, t):
            return [{"symbol": "A", "date": f, "time": None}]

    src = default_sources(Client(), finnhub_key="")
    assert [name for name, _ in src] == ["nasdaq", "fmp"]
    assert dict(src)["fmp"]("2026-09-01", "2026-09-02") == \
        [{"symbol": "A", "date": "2026-09-01", "time": None}]


def test_default_sources_with_finnhub_key_passes_key():
    from bot.earnings_store import default_sources
    seen = []

    def finnhub(from_date, to_date, api_key):
        seen.append((from_date, to_date, api_key))
        return []

    src = default_sources(None, finnhub_key="fh", finnhub_fn=finnhub)
    assert [name for name, _ in src] == ["nasdaq", "finnhub"]   # client None → ไม่มี fmp
    dict(src)["finnhub"]("2026-09-01", "2026-09-02")
    assert seen == [("2026-09-01", "2026-09-02", "fh")]


# ── refresh / backfill ───────────────────────────────────────────

def test_refresh_pulls_every_source_and_survives_failure(tmp_path):
    p = _store(tmp_path)
    seen = []

    def nasdaq(from_date, to_date):
        seen.append(("nasdaq", from_date, to_date))
        return [{"symbol": "CRM", "date": "2026-09-02", "time": "amc"}]

    def fmp(from_date, to_date):
        seen.append(("fmp", from_date, to_date))
        raise ConnectionError("down")

    result = refresh([("nasdaq", nasdaq), ("fmp", fmp)],
                     "2026-08-28", "2026-09-04", today=TODAY, path=p)
    assert result == {"nasdaq": 1, "fmp": None}
    assert seen == [("nasdaq", "2026-08-28", "2026-09-04"),
                    ("fmp", "2026-08-28", "2026-09-04")]
    assert earnings_for("CRM", path=p) == [{"date": "2026-09-02", "time": "amc"}]


def test_backfill_pulls_past_window_once(tmp_path):
    p = _store(tmp_path)
    seen = []

    def nasdaq(from_date, to_date):
        seen.append((from_date, to_date))
        return [{"symbol": "EL", "date": "2026-08-19", "time": "bmo"}]

    n = backfill(30, fetch_fn=nasdaq, today=TODAY, path=p)
    assert seen == [("2026-07-29", "2026-08-28")]
    assert n == 1
    assert earnings_for("EL", path=p) == [{"date": "2026-08-19", "time": "bmo"}]
