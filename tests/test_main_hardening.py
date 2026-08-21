"""Hardening ของ bot/main.py: edited message, error handler, log rotation

บั๊กจริงที่เจอ: (1) ข้อความที่ถูก "แก้ไข" (edited) ผ่าน filters.TEXT ได้แต่
update.message เป็น None → AttributeError เงียบ (2) ไม่มี error handler →
telegram.error.Conflict ลง log เป็น "No error handlers are registered" 65 ครั้ง
(3) bot.log โตไม่จำกัด (~190KB/วัน)

การทดสอบ import bot.main ได้โดยไม่มี .env คือเงื่อนไขของ CI อยู่แล้ว
(CI ไม่มี .env — ถ้า main กลับไป load_config ตอน import ไฟล์นี้จะพังบน CI)
"""
import asyncio
import datetime as dt
import logging
from logging.handlers import RotatingFileHandler
from types import SimpleNamespace

from telegram import Chat, Message, MessageEntity, Update
from telegram.error import Conflict, NetworkError
from telegram.ext import CommandHandler, MessageHandler

from bot.config import Config
from bot.main import LOG_BACKUPS, LOG_MAX_BYTES, build_app, on_error, setup_logging

DUMMY_CONFIG = Config(telegram_token="123:ABC", chat_id="1", fmp_api_key="k")


def _msg(text, entities=()):
    return Message(message_id=1, date=dt.datetime.now(),
                   chat=Chat(id=99, type="private"), text=text,
                   entities=list(entities) or None)


def _cmd_msg(text):
    ent = MessageEntity(type=MessageEntity.BOT_COMMAND, offset=0,
                        length=len(text.split()[0]))
    return _msg(text, entities=[ent])


# ── edited message ต้องไม่เข้า handler ──────────────────────────


def test_text_handler_matches_new_text_message():
    app = build_app(DUMMY_CONFIG)
    update = Update(update_id=1, message=_msg("NVDA"))
    handlers = [h for h in app.handlers[0] if isinstance(h, MessageHandler)]
    assert handlers and any(h.check_update(update) for h in handlers)


def test_text_handler_ignores_edited_message():
    app = build_app(DUMMY_CONFIG)
    update = Update(update_id=1, edited_message=_msg("NVDA"))
    for h in app.handlers[0]:
        if isinstance(h, MessageHandler):
            assert not h.check_update(update)


def test_command_handlers_ignore_edited_command():
    # เช็คที่ filters ของ handler ตรงๆ — check_update เต็มๆ ต้องมี bot.username
    app = build_app(DUMMY_CONFIG)
    edited = Update(update_id=1, edited_message=_cmd_msg("/scan 7"))
    normal = Update(update_id=2, message=_cmd_msg("/scan 7"))
    cmd_handlers = [h for h in app.handlers[0] if isinstance(h, CommandHandler)]
    assert cmd_handlers
    for h in cmd_handlers:
        assert h.filters.check_update(normal)
        assert not h.filters.check_update(edited)


# ── error handler ───────────────────────────────────────────────


def _run_on_error(err):
    return asyncio.run(on_error(None, SimpleNamespace(error=err)))


def test_error_handler_registered():
    app = build_app(DUMMY_CONFIG)
    assert on_error in app.error_handlers


def test_on_error_conflict_logs_one_line_no_traceback(caplog):
    with caplog.at_level(logging.WARNING, logger="bot"):
        _run_on_error(Conflict("terminated by other getUpdates request"))
    recs = [r for r in caplog.records if "instance" in r.getMessage()]
    assert recs and all(not r.exc_info for r in recs)


def test_on_error_network_logs_warning_no_traceback(caplog):
    with caplog.at_level(logging.WARNING, logger="bot"):
        _run_on_error(NetworkError("Bad Gateway"))
    assert any(r.levelno == logging.WARNING and not r.exc_info
               for r in caplog.records)


def test_on_error_unexpected_logs_traceback(caplog):
    with caplog.at_level(logging.ERROR, logger="bot"):
        _run_on_error(ValueError("boom"))
    assert any(r.levelno == logging.ERROR and r.exc_info
               for r in caplog.records)


# ── log rotation ────────────────────────────────────────────────


def test_setup_logging_rotates_and_quiets_noisy_libs(tmp_path):
    handler = setup_logging(tmp_path / "bot.log")
    try:
        assert isinstance(handler, RotatingFileHandler)
        assert handler.maxBytes == LOG_MAX_BYTES
        assert handler.backupCount == LOG_BACKUPS
        # httpx (URL มี token) / apscheduler (log ทุก job) ต้องเงียบระดับ INFO
        assert logging.getLogger("httpx").level == logging.WARNING
        assert logging.getLogger("apscheduler").level == logging.WARNING
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()
