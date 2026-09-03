"""สถานะบอทสำหรับคำสั่ง /status (พิมพ์ "สถานะ" ก็ได้) — ดูสุขภาพจากมือถือไม่ต้องเปิด bot.log

รวมทุกแหล่งที่เคยต้องไล่ดูเองเวลาสงสัยว่าบอทโอเคไหม: process (PID/เริ่มเมื่อ),
โค้ดที่รันอยู่เทียบ HEAD (ต้อง restart ไหม), job เช้าวันนี้ (job_state.json),
รอตอบรับ (pending.json), watchlist, สัญญาณสะสม, FMP 402/เตือน/error วันนี้ใน bot.log,
เกณฑ์ไทย 14 วัน (rescore_state.json: ตามอยู่กี่ตัว + ตัวที่ข้ามติดกัน ≥2 วัน)
และผลสแกนล่าสุด (reports/scan_*.json) — ทุก path ฉีดได้เพื่อเทส
"""
import json
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from bot import rescore
from bot.config import PROJECT_ROOT
from bot.jobstate import JOB_STATE_PATH, SCHEDULE, _load as _load_job_state
from bot.pending import load_pending
from bot.signals import load_signals
from bot.watchlist import AUTO_WATCH_PATH, WATCHLIST_PATH, active_auto, load_watchlist

TZ = ZoneInfo("Asia/Bangkok")
LOG_PATH = PROJECT_ROOT / "bot.log"
REPORTS_DIR = PROJECT_ROOT / "reports"

_SYM_PARAM = re.compile(r"'symbol': '([A-Za-z0-9.\-^=]+)'")
_SYM_PATH = re.compile(r"https?://\S+/([A-Z][A-Z0-9.\-]{0,9})(?=\s|$)")
_LOG_LINE = re.compile(r"^\d{4}-\d{2}-\d{2} \S+ (\w+) (\S+) (.*)$")
_SCAN_STAMP = re.compile(r"scan_(\d{4}-\d{2}-\d{2}_\d{6})\.json$")


def read_head_commit(root=PROJECT_ROOT):
    """commit ย่อ 7 ตัวที่ HEAD ชี้ — อ่านไฟล์ .git ตรงๆ ไม่พึ่ง git CLI · None = อ่านไม่ได้"""
    git = Path(root) / ".git"
    try:
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref: "):
            return head[:7] or None
        ref = head[5:].strip()
        loose = git / ref
        if loose.exists():
            return loose.read_text(encoding="utf-8").strip()[:7] or None
        for line in (git / "packed-refs").read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1] == ref:
                return parts[0][:7]
    except OSError:
        pass
    return None


# บันทึกตอน import (≈ เริ่ม process) — โค้ดที่โหลดตอนนั้นคือโค้ดที่รันอยู่จริง
# แม้ HEAD จะขยับไปแล้วหลังจากนั้น (กรณีที่ถามบ่อย: commit แล้วลืม restart)
STARTED_AT = datetime.now(TZ)
STARTED_COMMIT = read_head_commit()


def job_states(now, state):
    """สถานะ job เช้าแต่ละตัว ณ เวลา now เทียบ job_state.json (dict {job: วัน ISO})

    done = รันวันนี้แล้ว · due = ถึงเวลาแล้วยังไม่รัน (catch-up จะเก็บ) ·
    pending = ยังไม่ถึงเวลา · off = ไม่มีรอบวันนี้ (เช่น weekly นอกวันอาทิตย์)
    """
    today = now.date().isoformat()
    out = []
    for name, t, days in SCHEDULE:
        last = state.get(name)
        if now.weekday() not in days:
            st = "off"
        elif last == today:
            st = "done"
        elif now.time() >= t:
            st = "due"
        else:
            st = "pending"
        out.append({"name": name, "time": t, "state": st, "last": last})
    return out


def scan_log_today(lines, today_iso):
    """นับจากบรรทัด log ของวันนี้: หุ้นที่ FMP ตอบ 402 (ไม่ซ้ำ), จำนวน WARNING/ERROR, error ล่าสุด"""
    symbols, warnings, errors, last_error = [], 0, 0, None
    for line in lines:
        if not line.startswith(today_iso):
            continue
        m = _LOG_LINE.match(line.rstrip())
        if not m:
            continue
        level, _name, msg = m.groups()
        if level == "WARNING":
            warnings += 1
        elif level == "ERROR":
            errors += 1
            last_error = msg
        if "FMP 402" in msg:
            sm = _SYM_PARAM.search(msg) or _SYM_PATH.search(msg)
            if sm and sm.group(1) not in symbols:
                symbols.append(sm.group(1))
    return {"fmp_402": symbols, "warnings": warnings, "errors": errors,
            "last_error": last_error}


def _read_log_lines(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def latest_scan(reports_dir=REPORTS_DIR):
    """สรุปไฟล์ scan_*.json ล่าสุด (ตาม stamp ในชื่อไฟล์) · None = ไม่มี/อ่านไม่ได้"""
    try:
        files = sorted(p for p in Path(reports_dir).iterdir() if _SCAN_STAMP.search(p.name))
    except OSError:
        return None
    if not files:
        return None
    path = files[-1]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        stamp = _SCAN_STAMP.search(path.name).group(1)
        api = data.get("api_stats") or {}
        return {
            "at": datetime.strptime(stamp, "%Y-%m-%d_%H%M%S"),
            "candidates": [(c.get("symbol"), c.get("grade"))
                           for c in data.get("candidates") or []],
            "skipped": data.get("skipped_counts") or {},
            "pending": len(data.get("pending") or []),
            "api_calls": (api.get("api_calls_made"), api.get("max_api_calls")),
        }
    except (OSError, ValueError, AttributeError):
        return None


def build_status(now, started_at=None, started_commit=None, head_commit=None, *,
                 job_state_path=JOB_STATE_PATH, pending_path=None,
                 watchlist_path=WATCHLIST_PATH, auto_watch_path=AUTO_WATCH_PATH,
                 signals_path=None, log_path=LOG_PATH, reports_dir=REPORTS_DIR,
                 rescore_state_path=None):
    """รวมสถานะทุกแหล่งเป็น dict เดียวให้ format_status — ไฟล์ไหนหาย/พังก็ได้ค่าว่าง"""
    signals = load_signals(signals_path) if signals_path else load_signals()
    # None = rescore.STATE_PATH ณ เวลาเรียก (ค่าปริยายของ load_state เอง)
    rescore_state = rescore.load_state(rescore_state_path)
    return {
        "now": now,
        "pid": os.getpid(),
        "started_at": started_at if started_at is not None else STARTED_AT,
        "started_commit": started_commit if started_commit is not None else STARTED_COMMIT,
        "head_commit": head_commit if head_commit is not None else read_head_commit(),
        "jobs": job_states(now, _load_job_state(job_state_path)),
        "pending": [p["symbol"] for p in load_pending(pending_path) if p.get("symbol")],
        "watch_manual": load_watchlist(watchlist_path),
        "watch_auto": list(active_auto(auto_watch_path, today=now.date())),
        "signals_total": len(signals),
        "last_signal": signals[-1] if signals else None,
        "log": scan_log_today(_read_log_lines(log_path), now.date().isoformat()),
        "rescore": {"tracked": len(rescore_state),
                    "stale": rescore.stale_entries(rescore_state)},
        "scan": latest_scan(reports_dir),
    }
