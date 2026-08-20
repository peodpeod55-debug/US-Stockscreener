"""Telegram bot entry: /scan /help + daily push อังคาร–เสาร์ 08:30 Asia/Bangkok"""
import asyncio
import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from bot.config import PROJECT_ROOT, load_config
from bot.formatter import format_scan
from bot.screener import run_scan, save_reports

TZ = ZoneInfo("Asia/Bangkok")
PUSH_WEEKDAYS = {1, 2, 3, 4, 5}  # date.weekday(): จ=0 → อังคาร(1)–เสาร์(5)

logging.basicConfig(
    filename=PROJECT_ROOT / "bot.log", level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("bot")
CONFIG = load_config()


def _authorized(update: Update) -> bool:
    return str(update.effective_chat.id) == str(CONFIG.chat_id)


async def _do_scan_and_send(bot, chat_id, lookback):
    scan = await asyncio.to_thread(run_scan, CONFIG, lookback)
    messages = format_scan(scan)
    save_reports(scan, messages)
    for msg in messages:
        await bot.send_message(chat_id=chat_id, text=msg)


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
        "Push อัตโนมัติ: อังคาร–เสาร์ 08:30 น."
    )


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
    app.job_queue.run_daily(daily_job, time=time(8, 30, tzinfo=TZ))
    logger.info("bot starting")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
