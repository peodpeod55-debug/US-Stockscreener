"""Telegram bot entry: /scan /help + daily push อังคาร–เสาร์ 08:30 Asia/Bangkok"""
import asyncio
import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from bot.config import PROJECT_ROOT, load_config
from bot.formatter import (
    format_breakouts,
    format_lookup,
    format_reminders,
    format_scan,
    format_weekly,
)
from bot.lookup import LOOKUP_MAX, SymbolNotCovered, lookup_symbol, parse_tickers
from bot.nasdaq_cal import fetch_nasdaq_earnings
from bot.reminders import build_reminders
from bot.screener import REPORTS_DIR, load_universe, run_scan, save_reports
from bot.weekly import SIGNAL_LOOKBACK_DAYS, build_weekly_items
from bot.yahoo_prices import fetch_yahoo_prices
from bot.watchlist import (
    AUTO_WATCH_DAYS,
    WATCHLIST_MAX,
    active_auto,
    add_symbols,
    all_watched,
    auto_add,
    auto_remove,
    load_watchlist,
    parse_watch_command,
    remove_symbols,
)
from fmp_client import FMPClient  # sys.path ถูกตั้งโดย bot.screener/bot.lookup แล้ว

TZ = ZoneInfo("Asia/Bangkok")
PUSH_WEEKDAYS = {1, 2, 3, 4, 5}  # date.weekday(): จ=0 → อังคาร(1)–เสาร์(5)

logging.basicConfig(
    filename=PROJECT_ROOT / "bot.log", level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
# httpx log URL เต็มของ Telegram API ซึ่งมี bot token — ห้ามให้ลง log
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("bot")
CONFIG = load_config()


def _authorized(update: Update) -> bool:
    return str(update.effective_chat.id) == str(CONFIG.chat_id)


async def _do_scan_and_send(bot, chat_id, lookback):
    scan = await asyncio.to_thread(run_scan, CONFIG, lookback,
                                   secondary_cal_fn=fetch_nasdaq_earnings,
                                   fallback_prices_fn=fetch_yahoo_prices)
    messages = format_scan(scan)
    save_reports(scan, messages)
    for msg in messages:
        await bot.send_message(chat_id=chat_id, text=msg)
    # หุ้นเกรด A/B เข้า watchlist อัตโนมัติ → ได้เตือนทะลุแนว/วันงบต่อเอง
    added = auto_add([c["symbol"] for c in scan["candidates"]])
    if added:
        await bot.send_message(
            chat_id=chat_id,
            text=f"➕ ติดตามอัตโนมัติ {AUTO_WATCH_DAYS} วัน: {', '.join(added)}\n"
                 "จะเตือนเมื่อทะลุแนว High 5 วัน/3 เดือนก่อนงบ · "
                 "เอาออก: เลิกติดตาม <ticker>")


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
        "/help — วิธีใช้\n\n"
        "ดูราคารายตัว: พิมพ์ ticker ได้เลย เช่น NVDA\n"
        f"หลายตัวพร้อมกัน (สูงสุด {LOOKUP_MAX}): NVDA TSLA AAPL\n"
        "ได้ราคาปิดล่าสุด, %เปลี่ยน, วอลุ่ม, วันงบ,\n"
        "สัญญาณหลังงบ + เกรด, High/Low 5วัน/3ด./52w\n\n"
        f"Watchlist (สูงสุด {WATCHLIST_MAX} ตัว):\n"
        "ติดตาม NVDA — เพิ่มหุ้นเข้า watchlist\n"
        "เลิกติดตาม NVDA — เอาออก\n"
        "ติดตาม — ดูรายชื่อที่ติดตามอยู่\n"
        "บอทจะเตือนตอนเช้าเมื่อหุ้นที่ติดตาม\n"
        "มีงบวันนี้/พรุ่งนี้ (บอก BMO/AMC)\n"
        f"หุ้นเกรด A/B จากสแกนเข้าเองอัตโนมัติ {AUTO_WATCH_DAYS} วัน\n\n"
        f"สรุป — ผลหุ้นที่บอทแจ้งย้อนหลัง {SIGNAL_LOOKBACK_DAYS} วัน\n"
        "(+/-% ตั้งแต่วันแจ้ง, เคยหลุด SL ไหม)\n\n"
        "Push อัตโนมัติ: อังคาร–เสาร์ 08:30 น.\n"
        "เตือนวันงบ: ทุกวัน 08:25 น.\n"
        "เตือนทะลุแนว (High 5วัน/3ด.ก่อนงบ): อังคาร–เสาร์ 08:20 น.\n"
        "สรุปผลรายสัปดาห์: อาทิตย์ 09:00 น."
    )


async def _handle_watch_command(update, action, tickers):
    if action == "show":
        manual = load_watchlist()
        auto = {s: d for s, d in active_auto().items() if s not in manual}
        if not manual and not auto:
            await update.message.reply_text(
                "ยังไม่มีหุ้นใน watchlist — พิมพ์ เช่น: ติดตาม NVDA")
            return
        lines = []
        if manual:
            lines.append(f"👀 ติดตามอยู่ {len(manual)} ตัว: {', '.join(manual)}")
        if auto:
            lines.append(f"🤖 อัตโนมัติจากสแกน A/B ({AUTO_WATCH_DAYS} วัน): "
                         + ", ".join(f"{s} ({d})" for s, d in auto.items()))
        lines.append("เตือนวันงบ 08:25 · เตือนทะลุแนว 08:20 · "
                     "เอาออก: เลิกติดตาม <ticker>")
        await update.message.reply_text("\n".join(lines))
        return
    if action == "remove":
        if not tickers:
            await update.message.reply_text("ใช้: เลิกติดตาม <ticker> เช่น เลิกติดตาม NVDA")
            return
        r = remove_symbols(tickers)
        auto_removed = auto_remove(tickers)
        removed = r["removed"] + [s for s in auto_removed
                                  if s not in r["removed"]]
        missing = [s for s in r["missing"] if s not in auto_removed]
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


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """พิมพ์ ticker (ไม่ใช่คำสั่ง /) → snapshot ราคารายตัว · "ติดตาม ..." → watchlist"""
    if not _authorized(update):
        return
    if update.message.text.strip() in ("สรุป", "สรุปผล"):
        try:
            await _send_weekly(context.bot, update.effective_chat.id,
                               notify_empty=True)
        except Exception:
            logger.exception("weekly summary failed")
            await update.message.reply_text("⚠️ สรุปผลล้มเหลว ดู bot.log")
        return
    watch = parse_watch_command(update.message.text)
    if watch:
        await _handle_watch_command(update, *watch)
        return
    tickers = parse_tickers(update.message.text)
    if not tickers:
        await update.message.reply_text(
            "พิมพ์ ticker หุ้น US เช่น NVDA หรือหลายตัว: NVDA TSLA "
            f"(สูงสุด {LOOKUP_MAX} ตัว) · ดูคำสั่งอื่น: /help")
        return
    # client ใหม่ต่อข้อความ: งบ API เล็กๆ พอสำหรับ 2 calls/ตัว กันข้อความเดียวเผางบทั้งวัน
    client = FMPClient(api_key=CONFIG.fmp_api_key,
                       max_api_calls=3 * len(tickers))
    universe = load_universe()
    for sym in tickers:
        try:
            snap = await asyncio.to_thread(lookup_symbol, client, sym, universe,
                                           fallback_prices_fn=fetch_yahoo_prices)
        except SymbolNotCovered:
            await update.message.reply_text(
                f"🔒 ดึง {sym} ไม่ได้ — ticker ไม่ถูกต้อง "
                "หรือหุ้นตัวนี้ไม่อยู่ในแผนฟรีของ FMP (ฟรีทีร์จำกัดรายชื่อหุ้น)")
            continue
        except Exception:
            logger.exception("lookup %s failed", sym)
            await update.message.reply_text(
                f"⚠️ ดึงข้อมูล {sym} ล้มเหลว ลองใหม่อีกครั้งนะครับ")
            continue
        if snap is None:
            await update.message.reply_text(
                f"❌ ไม่พบข้อมูล {sym} — เช็ค ticker เช่น NVDA / AAPL / BRK.B")
            continue
        await update.message.reply_text(format_lookup(snap))


async def reminder_job(context: ContextTypes.DEFAULT_TYPE):
    """เช้าทุกวัน: เช็คหุ้นที่ติดตาม (manual + auto) ตัวไหนงบวันนี้/พรุ่งนี้"""
    symbols = all_watched()
    if not symbols:
        return
    try:
        client = FMPClient(api_key=CONFIG.fmp_api_key,
                           max_api_calls=len(symbols) + 2)
        items = await asyncio.to_thread(
            build_reminders, symbols, client.get_earnings_dates)
        msg = format_reminders(items)
        if msg:
            await context.bot.send_message(chat_id=CONFIG.chat_id, text=msg)
    except Exception:
        logger.exception("reminder job failed")


async def breakout_job(context: ContextTypes.DEFAULT_TYPE):
    """เช้าอังคาร–เสาร์ (หลังได้ EOD คืนก่อน): หุ้นที่ติดตามตัวไหนเพิ่งทะลุแนว"""
    if datetime.now(TZ).weekday() not in PUSH_WEEKDAYS:
        return
    symbols = all_watched()
    if not symbols:
        return
    try:
        client = FMPClient(api_key=CONFIG.fmp_api_key,
                           max_api_calls=3 * len(symbols) + 2)
        universe = load_universe()
        alerts = []
        for sym in symbols:
            try:
                snap = await asyncio.to_thread(
                    lookup_symbol, client, sym, universe,
                    fallback_prices_fn=fetch_yahoo_prices)
            except Exception:
                logger.exception("breakout check %s failed", sym)
                continue
            if snap and snap.get("new_breaks"):
                alerts.append(snap)
        msg = format_breakouts(alerts)
        if msg:
            await context.bot.send_message(chat_id=CONFIG.chat_id, text=msg)
    except Exception:
        logger.exception("breakout job failed")


def _weekly_get_prices(client, sym):
    """ราคาสำหรับสรุปรายสัปดาห์ — FMP ก่อน, 402 → yahoo (แบบเดียวกับ lookup)"""
    client.saw_402 = False
    prices = client.get_historical_prices(sym, days=250)
    if not prices and getattr(client, "saw_402", False):
        try:
            prices = fetch_yahoo_prices(sym, 250)
        except Exception:
            prices = None
    return prices


async def _send_weekly(bot, chat_id, notify_empty=False):
    """สรุปผลหุ้นที่บอทแจ้ง 30 วันล่าสุด (PEAD drift)"""
    client = FMPClient(api_key=CONFIG.fmp_api_key, max_api_calls=60)
    items = await asyncio.to_thread(
        build_weekly_items, REPORTS_DIR,
        lambda sym: _weekly_get_prices(client, sym))
    msg = format_weekly(items)
    if msg:
        await bot.send_message(chat_id=chat_id, text=msg)
    elif notify_empty:
        await bot.send_message(
            chat_id=chat_id,
            text=f"ยังไม่มีหุ้นเกรด A/B ที่แจ้งใน {SIGNAL_LOOKBACK_DAYS} วันล่าสุด")


async def weekly_job(context: ContextTypes.DEFAULT_TYPE):
    """อาทิตย์เช้า: สรุปว่าหุ้นที่บอทเคยแจ้ง ตอนนี้เป็นยังไงบ้าง"""
    if datetime.now(TZ).weekday() != 6:  # อาทิตย์
        return
    try:
        await _send_weekly(context.bot, CONFIG.chat_id)
    except Exception:
        logger.exception("weekly job failed")


async def daily_job(context: ContextTypes.DEFAULT_TYPE):
    # job ตั้งรันทุกวัน แล้วเช็ควันในนี้เอง (กันความกำกวมเรื่อง days ของ JobQueue)
    if datetime.now(TZ).weekday() not in PUSH_WEEKDAYS:
        return
    try:
        await _do_scan_and_send(context.bot, CONFIG.chat_id, CONFIG.lookback_days)
    except Exception as e:
        logger.exception("daily job failed")
        try:
            await context.bot.send_message(
                chat_id=CONFIG.chat_id, text=f"⚠️ Daily scan ล้มเหลว: {e}")
        except Exception:
            logger.exception("error notify failed")


def main():
    app = Application.builder().token(CONFIG.telegram_token).build()
    app.add_handler(CommandHandler(["start", "help"], cmd_help))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.job_queue.run_daily(daily_job, time=time(8, 30, tzinfo=TZ))
    # เตือนวันงบรันทุกวัน (ไม่เว้นอาทิตย์/จันทร์ — งบวันจันทร์ต้องเตือนตั้งแต่อาทิตย์)
    app.job_queue.run_daily(reminder_job, time=time(8, 25, tzinfo=TZ))
    # เตือนทะลุแนวเฉพาะหลังวันซื้อขาย US (เช็ค weekday ใน callback)
    app.job_queue.run_daily(breakout_job, time=time(8, 20, tzinfo=TZ))
    # สรุปผลรายสัปดาห์ เช้าวันอาทิตย์ (เช็ค weekday ใน callback)
    app.job_queue.run_daily(weekly_job, time=time(9, 0, tzinfo=TZ))
    logger.info("bot starting")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
