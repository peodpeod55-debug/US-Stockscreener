"""Telegram bot entry: /scan /help + daily push อังคาร–เสาร์ 08:30 Asia/Bangkok"""
import asyncio
import logging
from datetime import date, datetime, time, timedelta
from logging.handlers import RotatingFileHandler
from zoneinfo import ZoneInfo

from telegram import BotCommand, Update
from telegram.error import Conflict, NetworkError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot import fetch_cache, instance_lock, rescore
from bot.breakouts import record_breakouts
from bot.buttons import (
    add_plan_button,
    build_unwatch_markup,
    build_watch_all_markup,
    build_watch_markup,
    drop_button,
    mark_pressed,
    parse_callback,
)
from bot.calendar_preview import build_calendar, parse_calendar_command
from bot.chart import build_chart_png
from bot.config import PROJECT_ROOT, load_config
from bot.dr import (DR_MAX, avg_volume, compute_premium, implied_ratio,
                    parse_dr_command, parse_dr_symbols)
from bot.formatter import (
    format_breakouts,
    format_calendar,
    format_dr,
    format_gap_pullbacks,
    format_hot,
    format_lookup,
    format_low_breaks,
    format_open_report,
    format_plan,
    format_reminders,
    format_scan,
    format_scanlog,
    format_settings,
    format_sl_breaks,
    format_stats,
    format_status,
    format_watch_detail,
    format_weekly,
)
from bot.hot import classify_watch
from bot.levels import below_low_5d
from bot.jobstate import (PUSH_WEEKDAYS, already_ran, claim, due_catchup,
                          last_breakout_bar, last_run, release,
                          set_breakout_bar, widen_lookback)
from bot.openbell import build_open_report, fetch_quote, fetch_yahoo_quote, in_open_window
from bot.lookup import LOOKUP_MAX, SET_RULE, lookup_symbol, parse_tickers
from bot.nasdaq_cal import fetch_nasdaq_earnings
from bot.plan import (PLAN_MAX, build_plan, parse_plan_command,
                      plan_unavailable_reason, rank_drs)
from bot.reminders import build_reminders
from bot.scan_csv import live_scores, pick_rows, record_scan_csv
from bot.screener import load_universe, run_scan, save_reports
from bot.settings import load_settings, parse_risk_command, risk_amount, update_settings
from bot.signals import load_signals, record_signals, signals_since
from bot.stats import build_stats, summarize
from bot.status import build_status
from bot.weekly import SIGNAL_LOOKBACK_DAYS, build_weekly_items
from bot.earnings_store import default_sources, known_earnings, refresh
from bot.prices import get_prices, prefetch
from bot.yahoo_prices import fetch_yahoo_prices
from bot.set_score import SET_SCORE_MAX
from bot.watchlist import (
    AUTO_WATCH_DAYS,
    AUTO_WATCH_MAX,
    WATCHLIST_MAX,
    active_auto,
    add_symbols,
    all_watched,
    auto_add,
    auto_remove,
    load_watchlist,
    parse_watch_command,
    remove_everywhere,
)
from fmp_client import FMPClient  # sys.path ถูกตั้งโดย bot.screener/bot.lookup แล้ว

TZ = ZoneInfo("Asia/Bangkok")

LOG_PATH = PROJECT_ROOT / "bot.log"
LOG_MAX_BYTES = 5_000_000       # เกินแล้วหมุนเป็น bot.log.1 … .N (เดิมโตไม่จำกัด)
LOG_BACKUPS = 3

logger = logging.getLogger("bot")
CONFIG = None                   # ตั้งใน main() — import โมดูลนี้ได้โดยไม่มี .env (เทส/CI)


def setup_logging(path=LOG_PATH):
    """log ลงไฟล์แบบหมุน — คืน handler (เทสใช้ปิด/ตรวจค่า)"""
    handler = RotatingFileHandler(path, maxBytes=LOG_MAX_BYTES,
                                  backupCount=LOG_BACKUPS, encoding="utf-8")
    logging.basicConfig(handlers=[handler], level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # httpx log URL เต็มของ Telegram API ซึ่งมี bot token — ห้ามให้ลง log
    logging.getLogger("httpx").setLevel(logging.WARNING)
    # apscheduler log ทุกรอบ job ที่ระดับ INFO — เสียงรบกวนหลักของไฟล์เดิม
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    return handler


CHART_MAX = 6                   # เพดานรูปต่อหนึ่งรอบแจ้ง กันสแปม
EXIT_ALREADY_RUNNING = 3        # exit code เฉพาะ instance ซ้อน — run_bot.bat เห็นแล้วเลิกวน restart


def _authorized(update: Update) -> bool:
    return str(update.effective_chat.id) == str(CONFIG.chat_id)


async def _send_chart(bot, chat_id, symbol, levels=None, caption=None,
                      reply_markup=None):
    """แนบกราฟจากราคาใน cache (เพิ่งดึงตอนสร้างข้อความ — ไม่มี API call เพิ่ม)

    cache หมดอายุ/วาดพัง → ข้ามเงียบๆ ไม่ล้มข้อความหลักที่ส่งไปแล้ว
    """
    try:
        prices = fetch_cache.get(("prices", symbol, 250))
        png = await asyncio.to_thread(build_chart_png, symbol, prices, levels)
        if png:
            await bot.send_photo(chat_id=chat_id, photo=png,
                                 caption=caption or symbol,
                                 reply_markup=reply_markup)
    except Exception:
        logger.exception("chart %s failed", symbol)


def _us_market_maybe_open(t):
    """ช่วงที่แท่ง "วันนี้" จาก Yahoo อาจยังเป็น intraday ไม่ปิด — ตลาด US เปิดเร็วสุด 20:30 ไทย
    (DST) ปิดช้าสุด ~04:00 เผื่อขอบถึง 05:00 (เหตุผลเดียวกับ jobstate.CATCHUP_UNTIL)"""
    return t >= time(20, 0) or t < time(5, 0)


async def _do_scan_and_send(bot, chat_id, lookback):
    scan = await asyncio.to_thread(run_scan, CONFIG, lookback,
                                   secondary_cal_fn=fetch_nasdaq_earnings)
    messages = format_scan(scan)
    save_reports(scan, messages)
    # บันทึกสัญญาณ A/B ลง signals.json (dedup ต่อรอบงบ) — ฐานของสรุปรายสัปดาห์
    record_signals(scan["candidates"], scan["to_date"])
    rows, scored = _record_scan_csv(scan)       # scan_log.csv (schema ไทย + grade) ให้ gem-lab
    # ปุ่มรวม "ติดตามถาวรทั้งหมด" ใต้ข้อความสแกนฉบับสุดท้าย (มี candidate ≥2)
    manual = set(load_watchlist())
    all_markup = build_watch_all_markup(
        [c["symbol"] for c in scan["candidates"] if c["symbol"] not in manual],
        permanent=True)
    for i, msg in enumerate(messages):
        await bot.send_message(
            chat_id=chat_id, text=msg,
            reply_markup=all_markup if i == len(messages) - 1 else None)
    for c in scan["candidates"][:CHART_MAX]:
        # in_auto: หุ้น A/B กำลังเข้า auto-watch ด้านล่าง — ปุ่มเลื่อนขั้นเป็นติดตามถาวร
        await _send_chart(bot, chat_id, c["symbol"], c["levels"],
                          caption=f"📈 {c['symbol']} — เกรด {c['grade']} "
                                  f"({c['score']:.0f}/100)",
                          reply_markup=add_plan_button(build_watch_markup(
                              c["symbol"], in_manual=c["symbol"] in manual,
                              in_auto=True), c["symbol"]))
    # เกณฑ์ไทยมีชีวิต 14 วัน (bot/rescore.py) — อยู่ *หลัง* ส่งรายงานสแกน: rescore ล้ม/ช้า
    # ต้องไม่ฉุดรายงานหลัก (เดิมอยู่ก่อนส่ง — state เสีย 1 entry = รายงานทั้งวันหาย)
    crossed = []
    if _us_market_maybe_open(datetime.now().time()):
        # แท่งวันนี้ยังเป็น intraday ไม่ปิด — ตัดสิน qualified ตอนนี้จะกินสิทธิ์แจ้งครั้งแรกถาวร
        logger.info("rescore: ตลาด US อาจเปิดอยู่ — เลื่อนคิดคะแนนไปรอบสแกนถัดไป")
    else:
        try:
            crossed = await asyncio.to_thread(
                rescore.run, rows, scored, lambda s: get_prices(s, 250),
                date.fromisoformat(scan["to_date"]), CONFIG.set_qualify_min,
                CONFIG.rescore_days, prefetch=prefetch)
            # crossing → signals.json (signal_type=set_cross) — feedback loop ของเกณฑ์ SET≥10:
            # เข้า weekly drift + /stats แยก cohort · dedup ต่อ (symbol, earn, type) retry ไม่เบิ้ล
            record_signals(rescore.signal_candidates(crossed), scan["to_date"])
            # ตัวที่เพิ่งข้ามครบ 2 วันติด = วันแรกที่ "ข้ามถาวร" — rescore.run ปักธงไว้ ที่นี่กินธงทิ้ง
            # จึงได้ใบแจ้งใบเดียวจริงแม้สแกนซ้ำวันเดิม (job + /scan + catch-up) · ≥3 ไปโผล่ที่ /status
            notice = rescore.stale_notice(rescore.pop_stale_notices())
            if notice:
                await bot.send_message(chat_id=chat_id, text=notice)
        except Exception:
            logger.exception("rescore failed")
            await bot.send_message(
                chat_id=chat_id,
                text="⚠️ เกณฑ์ไทยมีชีวิต (rescore) ล้มวันนี้ — จะคิดใหม่รอบสแกนถัดไป · ดู bot.log")
    # ตัวข้ามเกณฑ์ไทยที่ไม่อยู่ในลิสต์ A/B วันนี้ (แจ้งไปแล้วในข้อความสแกน) — แจ้งแยก + กราฟ
    cand_syms = [c["symbol"] for c in scan["candidates"]]
    new_crossed = [c for c in crossed if c["symbol"] not in set(cand_syms)]
    note = rescore.format_crossed(new_crossed, CONFIG.set_qualify_min,
                                  auto_days=AUTO_WATCH_DAYS)
    if note:
        await bot.send_message(chat_id=chat_id, text=note)
    # กราฟ+ปุ่มเหมือน candidate — bars อยู่ใน fetch_cache จาก rescore แล้ว ไม่ยิงเน็ตเพิ่ม
    for c in new_crossed[:CHART_MAX]:
        await _send_chart(bot, chat_id, c["symbol"],
                          {"sl": c.get("pre_low"), "reaction_date": c.get("d0")},
                          caption=f"⭐ {c['symbol']} — SET {c['pts']}/{SET_SCORE_MAX} "
                                  f"(วันทำการที่ {c['days_after']} หลังงบ)",
                          reply_markup=add_plan_button(build_watch_markup(
                              c["symbol"], in_manual=c["symbol"] in manual,
                              in_auto=True), c["symbol"]))
    # หุ้นเกรด A/B + ตัวข้ามเกณฑ์ไทย เข้า watchlist อัตโนมัติ → ได้เตือนทะลุแนว/วันงบต่อเอง
    added, evicted = auto_add(cand_syms + [c["symbol"] for c in crossed
                                           if c["symbol"] not in cand_syms])
    if added:
        await bot.send_message(
            chat_id=chat_id,
            text=f"➕ ติดตามอัตโนมัติ {AUTO_WATCH_DAYS} วัน: {', '.join(added)}\n"
                 "จะเตือนเมื่อทะลุแนว High 5 วัน/3 เดือนก่อนงบ · "
                 "เอาออก: เลิกติดตาม <ticker>")
    if evicted:
        # เพดานเต็มตัวเก่าสุดหลุด — ต้องบอก ไม่งั้นผู้ใช้เชื่อว่ายังเฝ้าอยู่ (ฤดูงบเกิน 20 ได้จริง)
        await bot.send_message(
            chat_id=chat_id,
            text=f"➖ หลุดจากติดตามอัตโนมัติ (เต็มเพดาน {AUTO_WATCH_MAX}): "
                 f"{', '.join(evicted)}\nยังต้องการเฝ้า: ติดตาม <ticker> (ถาวร)")


def _record_scan_csv(scan):
    """scan_log.csv (schema Set screnner + grade) ให้ gem-lab — แถวที่ผ่านด่าน SET หรือเกณฑ์เดิม
    คะแนน SET 0-15 จาก bars ใน fetch_cache ที่ run_scan เพิ่งดึง (ไม่ยิงเน็ตซ้ำ) · คืน (rows, scored) ให้ /scanlog ใช้ต่อ"""
    rows = scan.get("rows") or []
    picked = pick_rows(rows)
    scored = live_scores(picked, lambda s: fetch_cache.get(("prices", s, 250)))
    n = record_scan_csv([(r, scored.get(r["symbol"])) for r in picked], date.fromisoformat(scan["to_date"]))
    logger.info("scan_log.csv: บันทึก %d แถว (%s)", n, scan["to_date"])
    return rows, scored


async def _scanlog(bot, chat_id, lookback):
    """/scanlog · "สแกนล็อก" — สแกนย้อนหลัง N วันเหมือน /scan แต่โชว์สองเกณฑ์คู่กัน (🇹🇭 SET 0-15 + เดิม A/B)
    ไม่แตะ signals/auto-watch/chart · แถวเดียวกันลง scan_log.csv"""
    scan = await asyncio.to_thread(run_scan, CONFIG, lookback,
                                   secondary_cal_fn=fetch_nasdaq_earnings)
    rows, scored = _record_scan_csv(scan)
    for msg in format_scanlog(rows, scored, scan["from_date"], scan["to_date"], SET_RULE):
        await bot.send_message(chat_id=chat_id, text=msg)


async def _run_scanlog(update, context, lookback):
    await update.message.reply_text(f"🔍 กำลังสแกน + คิดคะแนน SET ย้อนหลัง {lookback} วัน...")
    try:
        await _scanlog(context.bot, update.effective_chat.id, lookback)
    except Exception:
        logger.exception("scanlog failed")
        await update.message.reply_text("⚠️ scanlog ล้มเหลว ดูรายละเอียดใน bot.log")


async def cmd_scanlog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    lookback = CONFIG.scanlog_lookback_days
    if context.args:
        try:
            lookback = max(1, min(30, int(context.args[0])))
        except ValueError:
            await update.message.reply_text("ใช้: /scanlog หรือ /scanlog <จำนวนวันย้อนหลัง 1-30>")
            return
    await _run_scanlog(update, context, lookback)


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    lookback = CONFIG.lookback_days
    if context.args:
        try:
            lookback = max(1, min(30, int(context.args[0])))
        except ValueError:
            await update.message.reply_text("ใช้: /scan หรือ /scan <จำนวนวันย้อนหลัง 1-30>")
            return
    await update.message.reply_text(f"🔍 กำลังสแกนย้อนหลัง {lookback} วัน...")
    try:
        await _do_scan_and_send(context.bot, update.effective_chat.id, lookback)
    except Exception:
        logger.exception("scan failed")
        await update.message.reply_text("⚠️ สแกนล้มเหลว ดูรายละเอียดใน bot.log")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    await update.message.reply_text(
        "คำสั่ง:\n"
        "/scan — สแกนย้อนหลัง 2 วัน\n"
        "/scan 7 — สแกนย้อนหลัง 7 วัน\n"
        "/scanlog (หรือพิมพ์ สแกนล็อก) — สองเกณฑ์คู่กัน: 🇹🇭 SET (ปิด D0 ≥2% & vol ≥1.5× · คะแนน 0-15 ⭐) + เดิม A/B\n"
        "  แถวเดียวกันลง scan_log.csv (schema ไทย + grade) ให้ gem-lab\n"
        "  ค่าเริ่มต้นย้อนหลัง 7 วัน · ใส่เลขเองได้ 1-30 เช่น /scanlog 14\n"
        "/help — วิธีใช้\n"
        "/status (หรือพิมพ์ สถานะ) — สุขภาพบอท: รันอยู่ไหม/ต้อง restart ไหม,\n"
        "job วันนี้, รอตอบรับ, FMP 402, error, สแกนล่าสุด\n"
        "/hot (หรือพิมพ์ น่าสนใจ) — หุ้นที่ติดตามตัวไหนน่าสนใจตอนนี้:\n"
        "ใกล้ H5d/H3m ≤3%, เพิ่งทะลุ, งบ ≤3 วัน · หลุด SL/Low ก่อนงบ\n"
        "คำสั่ง / ของคำสั่งไทย: /watch /unwatch /cal /dr /plan /risk /summary /stats\n\n"
        "ดูราคารายตัว: พิมพ์ ticker ได้เลย เช่น NVDA\n"
        f"หลายตัวพร้อมกัน (สูงสุด {LOOKUP_MAX}): NVDA TSLA AAPL\n"
        "ได้ราคาปิดล่าสุด, %เปลี่ยน, วอลุ่ม, วันงบ,\n"
        "สัญญาณหลังงบ + เกรด, High/Low 5วัน/3ด./52w\n"
        "+ 🇹🇭 เกณฑ์ SET คะแนน 0-15 ⭐ แบบบอทไทย (ไฮ 5d/3ด.,\n"
        "ไฮใหม่ล่าสุด, ความถี่, สัปดาห์↑, Low ก่อนงบ — โชว์แม้ตกด่านเข้า)\n"
        "พร้อมกราฟ 6 เดือน (เส้นแนว + SL)\n\n"
        f"Watchlist (สูงสุด {WATCHLIST_MAX} ตัว):\n"
        "ติดตาม NVDA — เพิ่มหุ้นเข้า watchlist\n"
        "เลิกติดตาม NVDA — เอาออก\n"
        "ติดตาม — ดูรายชื่อ + แนวรายตัว\n"
        "(H5d/H3m ทะลุหรือยัง, ระยะถึง SL, Low ก่อนงบ)\n"
        "บอทจะเตือนตอนเช้าเมื่อหุ้นที่ติดตาม\n"
        "มีงบวันนี้/พรุ่งนี้ (บอก BMO/AMC)\n"
        f"หุ้นเกรด A/B จากสแกนเข้าเองอัตโนมัติ {AUTO_WATCH_DAYS} วัน\n"
        "ปิดหลุด Low 5 วันก่อนงบ = setup จบ →\n"
        "ตัวอัตโนมัติถูกเอาออกเอง (แจ้งให้ทราบ)\n\n"
        f"สรุป — ผลหุ้นที่บอทแจ้งย้อนหลัง {SIGNAL_LOOKBACK_DAYS} วัน\n"
        "(+/-% ตั้งแต่วันแจ้ง, เคยหลุด SL ไหม)\n"
        "สถิติ — ผลงานสะสมทุกสัญญาณ:\n"
        "win rate แยกเกรด, drift +5/+20/+60 วัน, อัตราหลุด SL\n\n"
        "dr NVDA — DR ไทยแพง/ถูกกว่าปกติแค่ไหน\n"
        "(ราคา DR/USDTHB สดจาก quote · premium เทียบ\n"
        "หุ้นแม่ × USDTHB, ทุก DR ของหุ้นนั้น)\n\n"
        "แผน CRM (หรือ /plan CRM) — แผนเทรด 3 ทางเข้า:\n"
        "① เข้าตอนนี้ ② ทะลุ High วันงบ ③ ย่อถึง D0 Open\n"
        "SL = D0 Low · เป้า 1R/2R/3R · แปลงเป็นราคาบาท\n"
        "+ จำนวนหน่วยต่อ DR (ปุ่ม 📋 ใต้ lookup/สแกนก็ได้)\n"
        "เสี่ยง 1% ทุน 500000 (หรือ /risk ...) — ตั้งเงินเสี่ยง/ไม้\n"
        "ให้แผนคิดจำนวนหน่วย · พิมพ์ เสี่ยง เฉย ๆ = ดูค่า\n\n"
        "งบ — ปฏิทินงบ universe วันนี้ + 2 วันข้างหน้า\n"
        "งบ 5 — ล่วงหน้า 5 วัน (สูงสุด 7) · งบวันนี้ — เฉพาะวันนี้\n"
        "(บอก BMO/AMC, 🇹🇭 มี DR, 📌 อยู่ใน watchlist)\n\n"
        "Push อัตโนมัติ: อังคาร–เสาร์ 08:30 น.\n"
        "เตือนวันงบ: ทุกวัน 08:25 น.\n"
        "เตือนทะลุแนว (High 5วัน/3ด.ก่อนงบ)\n"
        "เตือนหลุด SL/Low ก่อนงบ: อังคาร–เสาร์ 08:20 น.\n"
        "สรุปผลรายสัปดาห์: อาทิตย์ 09:00 น.\n"
        "ยืนยันเปิดตลาด US (หุ้นที่ติดตาม): ~30 นาทีหลังเปิด"
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    try:
        await _send_status(context.bot, update.effective_chat.id)
    except Exception:
        logger.exception("status failed")
        await update.message.reply_text("⚠️ ดูสถานะล้มเหลว ดู bot.log")


def _watched_symbols():
    """หุ้นที่ติดตามทั้งหมด: manual ก่อน แล้ว auto ที่ไม่ซ้ำ — (symbols, auto_dates)"""
    manual = load_watchlist()
    auto = {s: d for s, d in active_auto().items() if s not in manual}
    return manual + list(auto), auto


async def _watch_snapshots(update, symbols):
    """snapshot ของหุ้นที่ติดตาม [(sym, snap|None)] — ใช้ร่วมกัน ติดตาม / น่าสนใจ

    แจ้งรอเฉพาะตอนต้องยิงเครือข่ายจริง — ช่วงเช้าหลัง job ราคาอยู่ใน cache ครบ
    """
    if any(fetch_cache.get(("prices", s, 250)) is None for s in symbols):
        await update.message.reply_text(f"⏳ กำลังเช็คแนว {len(symbols)} ตัว...")
    client = FMPClient(api_key=CONFIG.fmp_api_key,
                       max_api_calls=3 * len(symbols) + 2)
    universe = load_universe()
    await asyncio.to_thread(prefetch, symbols, 250, client)  # ดึงขนานก่อน
    items = []
    for sym in symbols:
        try:
            snap = await asyncio.to_thread(lookup_symbol, client, sym, universe)
        except Exception:
            logger.exception("watch detail %s failed", sym)
            snap = None
        items.append((sym, snap))
    return items


async def _handle_hot(update):
    """มุมมอง "น่าสนใจตอนนี้" — จัดกลุ่มหุ้นที่ติดตามจาก snapshot เดิม ไม่มี state ใหม่"""
    symbols, _auto = _watched_symbols()
    if not symbols:
        await update.message.reply_text(
            "ยังไม่มีหุ้นใน watchlist — พิมพ์ เช่น: ติดตาม NVDA")
        return
    items = await _watch_snapshots(update, symbols)
    await update.message.reply_text(format_hot(classify_watch(items)))


async def _handle_watch_command(update, action, tickers):
    if action == "show":
        symbols, auto = _watched_symbols()
        if not symbols:
            await update.message.reply_text(
                "ยังไม่มีหุ้นใน watchlist — พิมพ์ เช่น: ติดตาม NVDA")
            return
        items = await _watch_snapshots(update, symbols)
        # ปุ่ม 🗑 รายตัว — กดเอาออกได้เลย ต่อเนื่องกี่ตัวก็ได้ (ปุ่มที่กดหายไปทีละปุ่ม)
        await update.message.reply_text(format_watch_detail(items, auto),
                                        reply_markup=build_unwatch_markup(symbols))
        return
    if action == "remove":
        if not tickers:
            await update.message.reply_text("ใช้: เลิกติดตาม <ticker> เช่น เลิกติดตาม NVDA")
            return
        removed, missing = remove_everywhere(tickers)
        parts = []
        if removed:
            parts.append(f"🗑 เอาออกแล้ว: {', '.join(removed)}")
        if missing:
            parts.append(f"ไม่ได้ติดตามอยู่แล้ว: {', '.join(missing)}")
        await update.message.reply_text("\n".join(parts))
        return
    # action == "add"
    r = add_symbols(tickers)
    parts = []
    if r["added"]:
        parts.append(f"✅ ติดตามแล้ว: {', '.join(r['added'])}\n"
                     "บอทจะเตือนตอนเช้าเมื่อใกล้วันงบ (วันนี้/พรุ่งนี้)")
    if r["already"]:
        parts.append(f"ติดตามอยู่แล้ว: {', '.join(r['already'])}")
    if r["full"]:
        parts.append(f"⚠️ watchlist เต็ม ({WATCHLIST_MAX} ตัว) — "
                     f"ไม่ได้เพิ่ม: {', '.join(r['full'])}")
    await update.message.reply_text("\n".join(parts))


def _build_dr_report(sym, meta, drs):
    """รายงาน DR premium ของหุ้นแม่หนึ่งตัว (blocking — เรียกใน to_thread)

    ทุก fetch ผ่าน Yahoo (ฟรี ไม่กินงบ FMP) — แท่งรายวัน (baseline) cache 60
    นาที ส่วนราคาปัจจุบัน DR/FX ใช้ quote สดไม่ cache (quote เก่าไม่มีประโยชน์)
    quote ล้ม → compute_premium ถอยไปใช้ close แท่งล่าสุดแบบเดิมเอง
    """
    fx = fetch_cache.cached(
        ("fx", "USDTHB"),
        lambda: fetch_yahoo_prices("USDTHB=X", 120, raw=True))
    us = get_prices(sym, 250)  # Yahoo (ไม่มี client → ไม่แตะ FMP) + cache
    fx_quote = fetch_yahoo_quote("USDTHB=X", raw=True)
    items = []
    for d in drs[:DR_MAX]:
        dr_prices = fetch_cache.cached(
            ("dr", d), lambda d=d: fetch_yahoo_prices(f"{d}.BK", 120, raw=True))
        dr_quote = fetch_yahoo_quote(f"{d}.BK", raw=True)
        items.append((d, compute_premium(dr_prices, us, fx,
                                         dr_quote=dr_quote, fx_quote=fx_quote)))
    return format_dr(sym, meta["name"], items,
                     hidden=max(0, len(drs) - DR_MAX))


async def _handle_calendar(update, days_ahead):
    """ปฏิทินงบล่วงหน้า (พิมพ์ "งบ") — FMP 1 call + NASDAQ เสริม, cache 60 นาที"""
    client = FMPClient(api_key=CONFIG.fmp_api_key, max_api_calls=4)

    def get_calendar(from_date, to_date):
        return fetch_cache.cached(
            ("calendar", from_date, to_date),
            lambda: client.get_earnings_calendar(from_date, to_date))

    def secondary(from_date, to_date):
        return fetch_cache.cached(
            ("nasdaq_cal", from_date, to_date),
            lambda: fetch_nasdaq_earnings(from_date, to_date))

    items, from_date, to_date = await asyncio.to_thread(
        build_calendar, get_calendar, load_universe(),
        days_ahead=days_ahead, secondary_cal_fn=secondary)
    for msg in format_calendar(items, from_date, to_date, days_ahead,
                               watchlist=all_watched()):
        await update.message.reply_text(msg)


async def _handle_dr(update, tickers):
    if not tickers:
        await update.message.reply_text(
            "ใช้: dr <ticker> เช่น dr NVDA — ดูว่า DR ไทยแพง/ถูกกว่าปกติแค่ไหน")
        return
    universe = load_universe()
    for sym in tickers[:3]:
        meta = universe.get(sym)
        drs = parse_dr_symbols(meta["dr_symbols"]) if meta else []
        if not drs:
            await update.message.reply_text(f"{sym} ไม่มี DR ไทยใน universe")
            continue
        try:
            msg = await asyncio.to_thread(_build_dr_report, sym, meta, drs)
        except Exception:
            logger.exception("dr report %s failed", sym)
            await update.message.reply_text(
                f"⚠️ ดึงข้อมูล DR ของ {sym} ล้มเหลว ลองใหม่อีกครั้งนะครับ")
            continue
        await update.message.reply_text(msg)


def _plan_dr_items(sym, drs):
    """ข้อมูล DR ให้ build_plan (blocking — เรียกใน to_thread): implied ratio,
    USDTHB (quote สด → close ล่าสุด), ราคา DR ล่าสุด, วอลุ่มเฉลี่ย 20 วัน

    ทุก fetch ผ่าน Yahoo + cache คีย์เดียวกับรายงาน dr (ฟรี ไม่กินงบ FMP)
    คืน (items, skipped) — skipped = DR ที่คู่ข้อมูลไม่พอ (ใหม่/เบาบาง/ดึงไม่ได้)
    """
    fx = fetch_cache.cached(
        ("fx", "USDTHB"),
        lambda: fetch_yahoo_prices("USDTHB=X", 120, raw=True))
    us = get_prices(sym, 250)  # Yahoo (ไม่มี client → ไม่แตะ FMP) + cache
    fx_quote = fetch_yahoo_quote("USDTHB=X", raw=True) or {}
    fx_val = fx_quote.get("price") or (fx[0]["close"] if fx else None)
    items, skipped = [], []
    for d in drs:
        dr_prices = fetch_cache.cached(
            ("dr", d), lambda d=d: fetch_yahoo_prices(f"{d}.BK", 120, raw=True))
        ratio = implied_ratio(dr_prices, us, fx)
        if ratio is None or not fx_val:
            skipped.append(d)
            continue
        items.append({"dr": d, "ratio": ratio, "fx": fx_val,
                      "dr_price": dr_prices[0]["close"],
                      "avg_volume": avg_volume(dr_prices)})
    return items, skipped


def _build_plan_message(client, sym, universe, risk):
    """ข้อความแผนเทรดของหุ้นหนึ่งตัว (blocking — เรียกใน to_thread)

    snapshot เดียวกับ lookup → เช็คว่ามี setup หลังงบ (plan_unavailable_reason)
    → DR ผ่าน Yahoo (ล้ม/ไม่พอ = ยังได้แผนราคา US พร้อมหมายเหตุ ไม่ล้มทั้งข้อความ)
    """
    snap = lookup_symbol(client, sym, universe)
    if snap is None:
        return (f"❌ ไม่พบข้อมูล {sym} — เช็ค ticker เช่น NVDA / AAPL / BRK.B "
                "(หรือแหล่งราคาสะดุดชั่วคราว ลองใหม่อีกครั้ง)")
    reason = plan_unavailable_reason(snap)
    if reason:
        return f"📋 {sym}: {reason}"
    drs = parse_dr_symbols(snap.get("dr_symbols"))
    items, notes = [], []
    if drs:
        try:
            items, skipped = _plan_dr_items(sym, drs)
        except Exception:
            logger.exception("plan dr %s failed", sym)
            skipped = []
            notes.append("⚠️ ดึงราคา DR ไม่ได้ — แสดงเฉพาะราคาหุ้นแม่ ลองใหม่อีกครั้ง")
        if skipped:
            notes.append(f"(DR ข้อมูลไม่พอ ไม่แสดง: {', '.join(skipped)})")
    top, hidden = rank_drs(items)
    plan = build_plan(snap, risk_amount=risk, drs=top)
    msg = format_plan(plan, snap, hidden=hidden)
    return "\n".join([msg, *notes]) if notes else msg


async def _send_plans(bot, chat_id, tickers):
    """แผนเทรดรายตัว (พิมพ์ "แผน CRM" / /plan / ปุ่ม 📋) — ใช้ร่วมกันข้อความ+ปุ่ม

    เงินเสี่ยงจาก settings.json (ไม่ตั้ง = มีราคาบาทแต่ไม่มีจำนวนหน่วย)
    แจ้ง ⏳ เฉพาะตอนต้องยิงเครือข่ายจริง (ราคาหุ้นแม่/แท่ง DR ยังไม่อยู่ใน cache)
    """
    universe = load_universe()
    need_fetch = any(
        fetch_cache.get(("prices", s, 250)) is None
        or any(fetch_cache.get(("dr", d)) is None for d in
               parse_dr_symbols((universe.get(s) or {}).get("dr_symbols")))
        for s in tickers)
    if need_fetch:
        await bot.send_message(chat_id=chat_id,
                               text=f"⏳ กำลังทำแผน {', '.join(tickers)}...")
    client = FMPClient(api_key=CONFIG.fmp_api_key,
                       max_api_calls=3 * len(tickers))
    risk = risk_amount(load_settings())
    await asyncio.to_thread(prefetch, tickers, 250, client)  # ดึงขนานก่อน
    for sym in tickers:
        try:
            msg = await asyncio.to_thread(_build_plan_message, client, sym,
                                          universe, risk)
        except Exception:
            logger.exception("plan %s failed", sym)
            msg = f"⚠️ ทำแผน {sym} ล้มเหลว ลองใหม่อีกครั้งนะครับ"
        await bot.send_message(chat_id=chat_id, text=msg)


async def _handle_plan(update, context, tickers):
    if not tickers:
        await update.message.reply_text(
            "ใช้: แผน <ticker> เช่น แผน CRM — แผนเทรด 3 ทางเข้า "
            "(① เข้าตอนนี้ ② ทะลุ High วันงบ ③ ย่อถึง D0 Open) SL = D0 Low "
            f"เป้า 1R/2R/3R + ราคาบาทและจำนวนหน่วยต่อ DR (สูงสุด {PLAN_MAX} ตัว)")
        return
    await _send_plans(context.bot, update.effective_chat.id, tickers)


async def _handle_risk(update, changes):
    """ตั้ง/ดูทุน + %เสี่ยงต่อไม้ (settings.json) — changes {} = ขอดูค่า"""
    if not changes:
        await update.message.reply_text(format_settings(load_settings()))
        return
    try:
        settings = update_settings(changes)
    except ValueError as e:                  # ค่าไม่สมเหตุสมผล (เช่น เสี่ยง 50%)
        await update.message.reply_text(f"⚠️ {e}")
        return
    except Exception:
        logger.exception("update settings failed")
        await update.message.reply_text("⚠️ บันทึก settings.json ไม่ได้ ดู bot.log")
        return
    await update.message.reply_text("✅ บันทึกแล้ว\n" + format_settings(settings))


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """พิมพ์ ticker (ไม่ใช่คำสั่ง /) → snapshot ราคารายตัว · "ติดตาม ..." → watchlist"""
    if not _authorized(update):
        return
    await _dispatch_text(update, context, update.message.text)


async def cmd_alias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """slash alias ของคำสั่งพิมพ์ไทย (เมนู "/" ของ Telegram รับได้เฉพาะ slash):
    /watch NVDA → "ติดตาม NVDA" เข้า dispatcher เดิม — ไม่มี logic ซ้ำ"""
    if not _authorized(update):
        return
    cmd = update.message.text.split()[0].lstrip("/").split("@")[0].lower()
    thai = SLASH_ALIASES.get(cmd)
    if thai is None:
        return
    await _dispatch_text(update, context, " ".join([thai, *(context.args or [])]))


async def _dispatch_text(update, context, text):
    """แยกคำสั่งจากข้อความ — ใช้ร่วมกันระหว่างพิมพ์ไทยและ slash alias"""
    if text.strip().lower() in ("สถานะ", "status"):
        try:
            await _send_status(context.bot, update.effective_chat.id)
        except Exception:
            logger.exception("status failed")
            await update.message.reply_text("⚠️ ดูสถานะล้มเหลว ดู bot.log")
        return
    if text.strip().lower() in ("น่าสนใจ", "hot"):
        try:
            await _handle_hot(update)
        except Exception:
            logger.exception("hot failed")
            await update.message.reply_text("⚠️ ดูน่าสนใจล้มเหลว ดู bot.log")
        return
    if text.strip() in ("สรุป", "สรุปผล"):
        try:
            await _send_weekly(context.bot, update.effective_chat.id,
                               notify_empty=True)
        except Exception:
            logger.exception("weekly summary failed")
            await update.message.reply_text("⚠️ สรุปผลล้มเหลว ดู bot.log")
        return
    if text.strip() in ("สถิติ", "สถิติสะสม", "stats"):
        try:
            await _send_stats(context.bot, update.effective_chat.id)
        except Exception:
            logger.exception("stats failed")
            await update.message.reply_text("⚠️ สถิติล้มเหลว ดู bot.log")
        return
    words = text.strip().split()
    if words and words[0].lower() in ("สแกนล็อก", "สองเกณฑ์", "scanlog"):
        lookback = CONFIG.scanlog_lookback_days
        if len(words) > 1 and words[1].isdigit():
            lookback = max(1, min(30, int(words[1])))
        await _run_scanlog(update, context, lookback)
        return
    cal_cmd = parse_calendar_command(text)
    if cal_cmd is not None:
        try:
            await _handle_calendar(update, cal_cmd)
        except Exception:
            logger.exception("calendar failed")
            await update.message.reply_text(
                "⚠️ ดึงปฏิทินงบล้มเหลว ลองใหม่อีกครั้งนะครับ")
        return
    # เช็คก่อน lookup — "DR" เองก็เข้ารูป ticker จะโดนตีความผิดเป็นหุ้น
    dr_cmd = parse_dr_command(text)
    if dr_cmd is not None:
        await _handle_dr(update, dr_cmd)
        return
    plan_cmd = parse_plan_command(text)        # "แผน CRM" — ก่อน lookup ("PLAN" เข้ารูป ticker)
    if plan_cmd is not None:
        await _handle_plan(update, context, plan_cmd)
        return
    risk_cmd = parse_risk_command(text)        # "เสี่ยง 1% ทุน 500000" / "เสี่ยง" = ดูค่า
    if risk_cmd is not None:
        await _handle_risk(update, risk_cmd)
        return
    watch = parse_watch_command(text)
    if watch:
        await _handle_watch_command(update, *watch)
        return
    tickers = parse_tickers(text)
    if not tickers:
        await update.message.reply_text(
            "พิมพ์ ticker หุ้น US เช่น NVDA หรือหลายตัว: NVDA TSLA "
            f"(สูงสุด {LOOKUP_MAX} ตัว) · ดูคำสั่งอื่น: /help")
        return
    # client ใหม่ต่อข้อความ: งบ API เล็กๆ พอสำหรับ 2 calls/ตัว กันข้อความเดียวเผางบทั้งวัน
    client = FMPClient(api_key=CONFIG.fmp_api_key,
                       max_api_calls=3 * len(tickers))
    universe = load_universe()
    manual = set(load_watchlist())
    auto = set(active_auto())
    all_row_pending = len(tickers) >= 2   # แถว "ติดตามทั้งชุด" ติดข้อความแรกที่สำเร็จ
    await asyncio.to_thread(prefetch, tickers, 250, client)  # ดึงขนานก่อน
    for sym in tickers:
        try:
            snap = await asyncio.to_thread(lookup_symbol, client, sym, universe)
        except Exception:
            logger.exception("lookup %s failed", sym)
            await update.message.reply_text(
                f"⚠️ ดึงข้อมูล {sym} ล้มเหลว ลองใหม่อีกครั้งนะครับ")
            continue
        if snap is None:
            await update.message.reply_text(
                f"❌ ไม่พบข้อมูล {sym} — เช็ค ticker เช่น NVDA / AAPL / BRK.B "
                "(หรือแหล่งราคาสะดุดชั่วคราว ลองใหม่อีกครั้ง)")
            continue
        markup = build_watch_markup(
            sym, in_manual=sym in manual, in_auto=sym in auto,
            all_symbols=tickers if all_row_pending else None)
        if all_row_pending:
            all_row_pending = False
        if plan_unavailable_reason(snap) is None:   # มี setup หลังงบ → ปุ่ม 📋 แผนเทรด
            markup = add_plan_button(markup, sym)
        await update.message.reply_text(format_lookup(snap),
                                        reply_markup=markup)
        await _send_chart(context.bot, update.effective_chat.id, sym,
                          snap.get("levels"),
                          caption=f"{sym} — ปิด {snap['price']:,.2f}")


JOB_MAX_TRIES = 3               # เพดานลอง/วัน ต่อ job (นับใน process) กันสแปม+เผางบ API
REFRESH_AHEAD_DAYS = 7          # job เช้า: อัปเดตคลังวันงบล่วงหน้าเท่านี้ (NASDAQ ≤6 request)
REFRESH_WEEKLY_DAYS = 35        # อาทิตย์: ดึงต่อถึงเท่านี้ (NASDAQ มีข้อมูล ~4 สัปดาห์)
CATCHUP_INTERVAL = 30 * 60      # วินาที — catch-up วนเก็บ job ที่พลาด/ล้มทุกครึ่งชั่วโมง

_fail_counts = {}               # (job, วัน ISO) -> จำนวนครั้งที่ล้มวันนี้


async def _run_claimed(context, name, work):
    """claim วันนี้ → ทำงาน · ล้ม → คืน claim + แจ้งผู้ใช้ ให้ catch-up รอบถัดไปลองใหม่

    เดิม claim ค้างแม้ job ล้ม — เน็ตสะดุดตอนเช้า = job หายทั้งวันเงียบๆ
    ล้มครบ JOB_MAX_TRIES → เก็บ claim ไว้ (เลิกลองวันนี้) · retry อาจส่งข้อความ
    ที่ออกไปแล้วซ้ำถ้าล้มกลางคัน — ยอมรับ ดีกว่าพลาดเตือน SL/แนวทั้งวัน
    process crash (ไม่ใช่ exception) claim ค้างเหมือนเดิม — แยกไม่ได้ว่าส่งไปแค่ไหน
    """
    if not claim(name):
        return
    try:
        await work()
    except Exception as e:
        logger.exception("%s job failed", name)
        key = (name, date.today().isoformat())
        _fail_counts[key] = tries = _fail_counts.get(key, 0) + 1
        if tries < JOB_MAX_TRIES:
            release(name)
            note = (f"⚠️ job {name} ล้มเหลว: {e}\nจะลองใหม่อัตโนมัติภายใน "
                    f"~{CATCHUP_INTERVAL // 60} นาที (ครั้งที่ {tries}/{JOB_MAX_TRIES})")
        else:
            note = (f"⚠️ job {name} ล้มเหลวครบ {JOB_MAX_TRIES} ครั้ง — "
                    "หยุดลองสำหรับวันนี้ (ดู bot.log)")
        try:
            await context.bot.send_message(chat_id=CONFIG.chat_id, text=note)
        except Exception:
            logger.exception("%s failure notify failed", name)


async def reminder_job(context: ContextTypes.DEFAULT_TYPE):
    """เช้าทุกวัน: อัปเดตคลังวันงบล่วงหน้า 7 วัน แล้วเช็คหุ้นที่ติดตาม (manual + auto)
    ตัวไหนงบวันนี้/พรุ่งนี้ — อ่านจากคลัง ไม่ยิง FMP รายตัว (402 เกือบทุกตัว)"""
    async def work():
        symbols = all_watched()
        client = FMPClient(api_key=CONFIG.fmp_api_key,
                           max_api_calls=len(symbols) + 4)
        today = datetime.now(TZ).date()
        await asyncio.to_thread(
            refresh, default_sources(client, CONFIG.finnhub_api_key),
            today.isoformat(),
            (today + timedelta(days=REFRESH_AHEAD_DAYS)).isoformat(), today)
        if not symbols:
            return

        def get_earnings(sym):
            # คลัง ∪ signals.json ก่อน — FMP รายตัวเฉพาะตอนไม่รู้อะไรเลย (cache ข้าม job)
            return known_earnings(sym) or fetch_cache.cached(
                ("earnings", sym), lambda: client.get_earnings_dates(sym))

        items = await asyncio.to_thread(build_reminders, symbols, get_earnings)
        msg = format_reminders(items)
        if msg:
            await context.bot.send_message(chat_id=CONFIG.chat_id, text=msg)

    await _run_claimed(context, "reminder", work)


async def breakout_job(context: ContextTypes.DEFAULT_TYPE):
    """เช้าอังคาร–เสาร์ (หลังได้ EOD คืนก่อน): หุ้นที่ติดตามตัวไหนเพิ่งทะลุแนว/หลุด SL"""
    if datetime.now(TZ).weekday() not in PUSH_WEEKDAYS:
        return

    async def work():
        symbols = all_watched()
        if not symbols:
            return
        client = FMPClient(api_key=CONFIG.fmp_api_key,
                           max_api_calls=3 * len(symbols) + 2)
        universe = load_universe()
        auto = active_auto()
        alerts, sl_alerts, low_alerts, pull_alerts, dead = [], [], [], [], []
        bar_dates = []           # prices[0]["date"] ของทุกตัวที่ดึงราคาได้ — เทียบหาแท่งซ้ำ
        await asyncio.to_thread(prefetch, symbols, 250, client)  # ดึงขนานก่อน
        for sym in symbols:
            try:
                snap = await asyncio.to_thread(lookup_symbol, client, sym, universe)
            except Exception:
                logger.exception("breakout check %s failed", sym)
                continue
            if snap:
                bar_dates.append(snap["last_date"])
            if snap and snap.get("new_breaks"):
                alerts.append(snap)
            if snap and snap.get("sl_break"):
                sl_alerts.append(snap)
            if snap and snap.get("low_break"):
                low_alerts.append(snap)
            if snap and snap.get("gap_pullback"):
                pull_alerts.append(snap)
            # ปิดใต้ low ก่อนงบ = setup จบ → เก็บกวาดออกจาก auto-watch
            # (state ไม่ใช่ edge — ตัวที่หลุดค้างมาหลายวันก็โดนเก็บ) manual ไม่แตะ
            if snap and sym in auto and below_low_5d(snap.get("levels")):
                dead.append(sym)
        # แท่งล่าสุด (ทุกตัวที่ดึงราคาได้) เหมือนรอบก่อนเป๊ะ = วันหยุด US/Yahoo ยังไม่มีแท่งใหม่
        # (เช่น อังคารหลัง Labor Day ยังเห็นแท่งศุกร์ตัวเดิมที่รอบเสาร์ประมวลผลไปแล้ว) —
        # ข้ามทั้งรอบกันแจ้งซ้ำ (ดึงราคาไม่ได้เลยสักตัว = bar_dates ว่าง ปล่อยผ่านตามเดิม ไม่แตะ last_bar)
        bar_date = max(bar_dates) if bar_dates else None
        if bar_date is not None and bar_date == last_breakout_bar():
            logger.info("breakout: แท่งล่าสุด %s เหมือนรอบก่อน (วันหยุด/ยังไม่มีแท่งใหม่) — ข้ามแจ้งซ้ำ", bar_date)
            return
        removed = auto_remove(dead) if dead else []
        # เหตุการณ์ทะลุแนวลง breakouts.json — gem-lab อ่านไปเป็น candidate ยิง Gem
        record_breakouts(alerts)
        for msg in (format_breakouts(alerts), format_gap_pullbacks(pull_alerts),
                    format_sl_breaks(sl_alerts), format_low_breaks(low_alerts, removed)):
            if msg:
                await context.bot.send_message(chat_id=CONFIG.chat_id, text=msg)
        tagged = ([(s, "🚀 ทะลุแนว") for s in alerts]
                  + [(s, "🔽 ย่อเข้า gap") for s in pull_alerts]
                  + [(s, "🛑 หลุด SL") for s in sl_alerts]
                  + [(s, "⛔ หลุด Low ก่อนงบ") for s in low_alerts])
        seen = set()
        for snap, tag in tagged[:CHART_MAX]:
            if snap["symbol"] in seen:      # ตัวเดียวทะลุแนว+หลุด SL วันเดียวกัน
                continue
            seen.add(snap["symbol"])
            await _send_chart(context.bot, CONFIG.chat_id, snap["symbol"],
                              snap.get("levels"),
                              caption=f"{tag} {snap['symbol']} — "
                                      f"ปิด {snap['price']:,.2f}")
        # บันทึกหลังงานแจ้งเตือนสำเร็จทั้งหมดเท่านั้น — ส่งข้อความ/ส่งกราฟล้มกลางคัน exception
        # จะโยนออกจาก work() ก่อนถึงบรรทัดนี้ claim ถูกคืน (_run_claimed) แล้ว catch-up รอบถัดไป
        # retry ส่งซ้ำได้ — ห้ามบันทึก last_bar ไปก่อนแล้วเงียบทั้งชุดถ้าส่งไม่สำเร็จจริง
        if bar_date is not None:
            set_breakout_bar(bar_date)

    await _run_claimed(context, "breakout", work)


async def openbell_job(context: ContextTypes.DEFAULT_TYPE):
    """หลังตลาด US เปิด ~30 นาที: ยืนยันว่าหุ้นที่ติดตาม gap ยังอยู่ไหม

    ตั้งยิง 21:00 และ 22:00 ไทย — in_open_window เลือกรอบที่ตรงฤดู (DST) เอง
    """
    if not in_open_window(datetime.now(TZ)):
        return
    symbols = all_watched()
    if not symbols:
        return
    try:
        client = FMPClient(api_key=CONFIG.fmp_api_key,
                           max_api_calls=len(symbols) + 2)

        items = await asyncio.to_thread(
            build_open_report, symbols, lambda sym: fetch_quote(sym, client=client))
        msg = format_open_report(items)
        if msg:
            await context.bot.send_message(chat_id=CONFIG.chat_id, text=msg)
    except Exception:
        logger.exception("openbell job failed")


def _weekly_get_prices(client, sym):
    """ราคาสำหรับสรุปรายสัปดาห์/สถิติ — ทางเดียวกับ lookup (cache → Yahoo → FMP)"""
    return get_prices(sym, 250, client=client)


async def _send_weekly(bot, chat_id, notify_empty=False):
    """สรุปผลหุ้นที่บอทแจ้ง 30 วันล่าสุด (PEAD drift) — สัญญาณจาก signals.json"""
    client = FMPClient(api_key=CONFIG.fmp_api_key, max_api_calls=60)
    signals = signals_since(SIGNAL_LOOKBACK_DAYS)
    await asyncio.to_thread(prefetch, [s["symbol"] for s in signals], 250, client)
    items = await asyncio.to_thread(
        build_weekly_items, signals, lambda sym: _weekly_get_prices(client, sym))
    msg = format_weekly(items)
    if msg:
        await bot.send_message(chat_id=chat_id, text=msg)
    elif notify_empty:
        await bot.send_message(
            chat_id=chat_id,
            text=f"ยังไม่มีหุ้นเกรด A/B ที่แจ้งใน {SIGNAL_LOOKBACK_DAYS} วันล่าสุด")


async def _send_stats(bot, chat_id):
    """สถิติสะสมทุกสัญญาณใน signals.json (พิมพ์ "สถิติ") — win rate/drift แยกเกรด"""
    signals = load_signals()
    if not signals:
        await bot.send_message(
            chat_id=chat_id,
            text="ยังไม่มีสัญญาณสะสมใน signals.json — "
                 "จะเริ่มเก็บอัตโนมัติเมื่อสแกนเจอหุ้นเกรด A/B")
        return
    client = FMPClient(api_key=CONFIG.fmp_api_key,
                       max_api_calls=len(signals) + 2)
    await asyncio.to_thread(prefetch, [s["symbol"] for s in signals], 250, client)
    evaluated = await asyncio.to_thread(
        build_stats, signals, lambda sym: _weekly_get_prices(client, sym))
    msg = format_stats(summarize(evaluated), total=len(signals))
    if msg:
        await bot.send_message(chat_id=chat_id, text=msg)
    else:
        await bot.send_message(
            chat_id=chat_id,
            text=f"มี {len(signals)} สัญญาณแต่ยังประเมินไม่ได้ "
                 "(ดึงราคาไม่ได้/ข้อมูลย้อนไม่ถึงวันแจ้ง) — ลองใหม่ภายหลัง")


async def _send_status(bot, chat_id):
    """สถานะบอท (/status หรือพิมพ์ "สถานะ") — อ่าน state/log ใน thread กันบล็อก event loop"""
    st = await asyncio.to_thread(build_status, datetime.now(TZ))
    await bot.send_message(chat_id=chat_id, text=format_status(st))


async def weekly_job(context: ContextTypes.DEFAULT_TYPE):
    """อาทิตย์เช้า: ดึงคลังวันงบล่วงหน้าถึง +35 วัน แล้วสรุปว่าหุ้นที่บอทเคยแจ้งเป็นยังไงบ้าง"""
    if datetime.now(TZ).weekday() != 6:  # อาทิตย์
        return

    async def work():
        today = datetime.now(TZ).date()
        client = FMPClient(api_key=CONFIG.fmp_api_key, max_api_calls=4)
        await asyncio.to_thread(
            refresh, default_sources(client, CONFIG.finnhub_api_key),
            (today + timedelta(days=REFRESH_AHEAD_DAYS + 1)).isoformat(),
            (today + timedelta(days=REFRESH_WEEKLY_DAYS)).isoformat(), today)
        await _send_weekly(context.bot, CONFIG.chat_id)

    await _run_claimed(context, "weekly", work)


async def daily_job(context: ContextTypes.DEFAULT_TYPE):
    # job ตั้งรันทุกวัน แล้วเช็ควันในนี้เอง (กันความกำกวมเรื่อง days ของ JobQueue)
    if datetime.now(TZ).weekday() not in PUSH_WEEKDAYS:
        return
    # เครื่องปิดหลายวัน → ย้อนหน้าต่างสแกนครอบวันที่หายไป (ต้องอ่านก่อน claim จะทับค่าเดิม)
    lookback = widen_lookback(CONFIG.lookback_days, last_run("scan"),
                              datetime.now(TZ).date(), cap=CONFIG.rescore_days)
    await _run_claimed(context, "scan",
                       lambda: _do_scan_and_send(context.bot, CONFIG.chat_id,
                                                 lookback))


async def catchup_job(context: ContextTypes.DEFAULT_TYPE):
    """วนทุก CATCHUP_INTERVAL: รัน job เช้าที่เวลาผ่านแล้วแต่วันนี้ยังไม่สำเร็จ

    เก็บทั้ง (1) รอบที่พลาดเพราะเครื่องปิด/หลับช่วงเช้า — รอบแรกยิง 15 วิหลัง
    start (2) job ที่ล้มแล้วถูกคืน claim โดย _run_claimed — retry ในรอบถัดไป
    claim ในแต่ละ job กันส่งซ้ำ ทำให้วนถี่แค่ไหนก็ไม่รันเกินวันละครั้ง
    """
    jobs = {"breakout": breakout_job, "reminder": reminder_job,
            "scan": daily_job, "weekly": weekly_job}
    for name in due_catchup(datetime.now(TZ)):
        if already_ran(name):
            continue
        logger.info("catch-up: running missed job %s", name)
        await jobs[name](context)


async def _safe_answer(query, text=None):
    """ตอบ callback เสมอ (ปุ่มค้างหมุนติ้วถ้าไม่ตอบ) — query เก่าเกิน answer ล้มได้ ไม่เป็นไร"""
    try:
        await query.answer(text)
    except Exception as e:
        logger.warning("callback answer failed (query เก่าจากช่วงบอทปิด?): %s", e)


async def on_button(update, context):
    """ปุ่ม inline: w:/wa: เพิ่ม watchlist · u: เอาออก · p: ส่งแผนเทรด (ปุ่มคงอยู่ กดซ้ำได้)

    ลำดับสำคัญ: ทำงานจริงก่อน แล้วค่อย answer/edit — สองอย่างหลังล้มได้
    (query เก่า, ข้อความ >48 ชม. แก้ไม่ได้) โดยเจตนาผู้ใช้ต้องไม่สูญ
    """
    query = update.callback_query
    if query is None:
        return
    if str(query.from_user.id) != str(CONFIG.chat_id):
        await _safe_answer(query)
        return
    parsed = parse_callback(query.data or "")
    if parsed is None:                       # ปุ่ม ✓ ที่ปลดชนวนแล้ว / data ปลอม
        await _safe_answer(query)
        return
    action, syms = parsed
    if action == "plan":
        # งานยาว (ดึง DR) → answer ก่อนกัน query หมดอายุ · ไม่แก้ markup ปุ่มใช้ซ้ำได้
        await _safe_answer(query, f"⏳ ทำแผน {syms[0]}")
        try:
            await _send_plans(context.bot, CONFIG.chat_id, syms)
        except Exception:
            logger.exception("plan button %s failed", syms)
        return
    if action == "watch":
        r = add_symbols(syms)
        parts = []
        if r["added"]:
            parts.append(f"✅ ติดตาม: {', '.join(r['added'])}")
        if r["already"]:
            parts.append(f"อยู่แล้ว: {', '.join(r['already'])}")
        if r["full"]:
            parts.append(f"⚠️ เต็ม {WATCHLIST_MAX} ตัว: {', '.join(r['full'])}")
        toast, transform = " · ".join(parts), mark_pressed
    else:
        removed, missing = remove_everywhere(syms)
        toast = (f"🗑 เอา {', '.join(removed)} ออกแล้ว" if removed
                 else f"{', '.join(missing)} ไม่ได้ติดตามอยู่แล้ว")
        transform = drop_button
    await _safe_answer(query, toast)
    old = getattr(query.message, "reply_markup", None)
    if old is None:
        return
    try:
        await query.edit_message_reply_markup(reply_markup=transform(old, query.data))
    except Exception as e:
        logger.warning("edit reply markup failed (ข้อความเก่า?): %s", e)


# เมนู "/" ใน Telegram (setMyCommands ตอน start) — ชื่อ a-z0-9_ ≤32, คำอธิบาย ≤256
BOT_COMMANDS = [
    ("scan", "สแกนหุ้นหลังงบดี 2 วันล่าสุด (ใส่เลข = ย้อนหลัง N วัน)"),
    ("hot", "หุ้นที่ติดตามตัวไหนน่าสนใจตอนนี้ (ใกล้แนว/เพิ่งทะลุ/งบใกล้/หลุด SL)"),
    ("watch", "ดู watchlist + แนวรายตัว · /watch NVDA = ติดตาม"),
    ("unwatch", "เลิกติดตาม: /unwatch NVDA"),
    ("cal", "ปฏิทินงบ universe วันนี้+2 วัน (ใส่เลข 0-7)"),
    ("scanlog", "สองเกณฑ์คู่กัน: 🇹🇭 SET (ปิด D0 ≥2% & vol ≥1.5× · 0-15 ⭐) + เดิม A/B → scan_log.csv (ใส่เลข = N วัน)"),
    ("dr", "DR ไทยแพง/ถูกกว่าหุ้นแม่แค่ไหน: /dr NVDA"),
    ("plan", "แผนเทรด 3 ทางเข้า + SL/เป้า 1R-3R + ราคาบาท/จำนวนหน่วย DR: /plan CRM"),
    ("risk", "ตั้งทุน/%เสี่ยงต่อไม้ให้ /plan คิดจำนวนหน่วย: /risk 1% ทุน 500000 · /risk = ดูค่า"),
    ("summary", "ผลหุ้นที่บอทแจ้งย้อนหลัง 30 วัน"),
    ("stats", "สถิติสะสมทุกสัญญาณ (win rate, drift, หลุด SL)"),
    ("status", "สุขภาพบอท: job วันนี้, รอตอบรับ, FMP 402, error"),
    ("help", "วิธีใช้ทั้งหมด"),
]
# slash → คำสั่งไทยเดิม (ส่งเข้า _dispatch_text) — /scan /status /help มี handler ตรงอยู่แล้ว
SLASH_ALIASES = {"watch": "ติดตาม", "unwatch": "เลิกติดตาม", "hot": "น่าสนใจ",
                 "summary": "สรุป", "stats": "สถิติ", "dr": "dr", "cal": "งบ",
                 "plan": "แผน", "risk": "เสี่ยง"}


async def register_commands(app):
    """post_init: ลงทะเบียนเมนูคำสั่งกับ Telegram — ล้ม (เน็ต) แค่ log ไม่ให้บอทตาย"""
    try:
        await app.bot.set_my_commands([BotCommand(c, d) for c, d in BOT_COMMANDS])
    except Exception as e:
        logger.warning("set_my_commands failed: %s", e)


async def on_error(update, context):
    """error กลางของ PTB — เดิมไม่มี ทุก error ลง log เป็น "No error handlers are registered" """
    err = context.error
    if isinstance(err, Conflict):
        # มีบอทอีก instance แย่ง getUpdates (instance_lock กันชั้นหนึ่งแล้ว แต่กันข้ามเครื่องไม่ได้)
        logger.error("Conflict: bot อีก instance กำลังรันอยู่ — ปิดตัวที่ซ้ำ (%s)", err)
    elif isinstance(err, NetworkError):
        logger.warning("network hiccup (PTB retry เอง): %s", err)
    else:
        logger.error("unhandled error (update=%s)", update, exc_info=err)


def build_app(config):
    """ประกอบ Application: handlers + งานตั้งเวลา (แยกจาก main ให้เทสตรวจ wiring ได้)"""
    app = (Application.builder().token(config.telegram_token)
           .post_init(register_commands).build())
    # รับเฉพาะข้อความใหม่ — ข้อความที่ถูก "แก้ไข" (edited) ผ่าน filters.TEXT ได้
    # แต่ update.message เป็น None → handler เดิม AttributeError เงียบ
    new_msg = filters.UpdateType.MESSAGE
    app.add_handler(CommandHandler(["start", "help"], cmd_help, filters=new_msg))
    app.add_handler(CommandHandler("scan", cmd_scan, filters=new_msg))
    app.add_handler(CommandHandler("scanlog", cmd_scanlog, filters=new_msg))
    app.add_handler(CommandHandler("status", cmd_status, filters=new_msg))
    app.add_handler(CommandHandler(list(SLASH_ALIASES), cmd_alias, filters=new_msg))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & new_msg, on_text))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_error_handler(on_error)
    app.job_queue.run_daily(daily_job, time=time(8, 30, tzinfo=TZ))
    # เตือนวันงบรันทุกวัน (ไม่เว้นอาทิตย์/จันทร์ — งบวันจันทร์ต้องเตือนตั้งแต่อาทิตย์)
    app.job_queue.run_daily(reminder_job, time=time(8, 25, tzinfo=TZ))
    # เตือนทะลุแนวเฉพาะหลังวันซื้อขาย US (เช็ค weekday ใน callback)
    app.job_queue.run_daily(breakout_job, time=time(8, 20, tzinfo=TZ))
    # สรุปผลรายสัปดาห์ เช้าวันอาทิตย์ (เช็ค weekday ใน callback)
    app.job_queue.run_daily(weekly_job, time=time(9, 0, tzinfo=TZ))
    # ยืนยันเปิดตลาด US: ยิงสองรอบ in_open_window เลือกรอบที่ห่างเปิด 20-80 นาที
    app.job_queue.run_daily(openbell_job, time=time(21, 0, tzinfo=TZ))
    app.job_queue.run_daily(openbell_job, time=time(22, 0, tzinfo=TZ))
    # catch-up วนซ้ำ: รอบแรกเก็บ job ที่พลาดตอนเครื่องปิด/หลับ รอบถัดๆ ไป
    # retry job ที่ล้มแล้วถูกคืน claim (_run_claimed) — กันซ้ำด้วย claim
    app.job_queue.run_repeating(catchup_job, interval=CATCHUP_INTERVAL, first=15)
    return app


def main():
    setup_logging()
    lock = instance_lock.acquire()  # ถือ reference ไว้ตลอดอายุ process
    if lock is None:
        logger.error("bot.main รันอยู่แล้วอีก instance (port %d ถูกถือ) — จบตัวนี้",
                     instance_lock.LOCK_PORT)
        # ห้ามเป็น code 1 (= crash) — launcher จะวน restart ทุก 60 วิไม่รู้จบ
        raise SystemExit(EXIT_ALREADY_RUNNING)
    global CONFIG
    CONFIG = load_config()
    app = build_app(CONFIG)
    logger.info("bot starting")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
