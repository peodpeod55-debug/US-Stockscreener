"""เมนูคำสั่งใน Telegram (setMyCommands) + slash alias ของคำสั่งที่เดิมพิมพ์ไทย

เมนู "/" ของแอป Telegram รับได้เฉพาะคำสั่ง slash — คำสั่งไทย (ติดตาม/สรุป/สถิติ/dr/งบ)
จึงได้ alias `/watch /unwatch /hot /summary /stats /dr /cal` ที่ส่งเข้า dispatcher
ข้อความเดิม ไม่มี logic ซ้ำ · ลงทะเบียนตอน start (post_init) ล้มไม่ทำให้บอทตาย
"""
import asyncio
import logging
import re
from types import SimpleNamespace

from telegram import BotCommand
from telegram.ext import CommandHandler

import bot.main as m
from bot.config import Config
from bot.main import BOT_COMMANDS, SLASH_ALIASES, build_app, register_commands

DUMMY_CONFIG = Config(telegram_token="123:ABC", chat_id="1", fmp_api_key="k")


def _registered_commands(app):
    return {c for h in app.handlers[0] if isinstance(h, CommandHandler) for c in h.commands}


# ── เมนู ─────────────────────────────────────────────────────────


def test_every_menu_command_has_a_handler():
    app = build_app(DUMMY_CONFIG)
    missing = [c for c, _ in BOT_COMMANDS if c not in _registered_commands(app)]
    assert missing == []


def test_every_alias_is_in_menu_and_has_handler():
    app = build_app(DUMMY_CONFIG)
    menu = {c for c, _ in BOT_COMMANDS}
    for cmd in SLASH_ALIASES:
        assert cmd in menu, cmd
        assert cmd in _registered_commands(app), cmd


def test_menu_entries_follow_telegram_limits():
    names = [c for c, _ in BOT_COMMANDS]
    assert len(names) == len(set(names))
    for name, desc in BOT_COMMANDS:
        assert re.fullmatch(r"[a-z0-9_]{1,32}", name), name
        assert 3 <= len(desc) <= 256, name


def test_menu_lists_core_commands_first():
    assert [c for c, _ in BOT_COMMANDS][:2] == ["scan", "hot"]
    assert {"status", "help", "watch", "unwatch", "cal", "scanlog", "dr", "summary", "stats"} <= {
        c for c, _ in BOT_COMMANDS}


def test_register_commands_sends_menu_to_telegram():
    sent = []

    async def set_my_commands(cmds):
        sent.append(cmds)
    app = SimpleNamespace(bot=SimpleNamespace(set_my_commands=set_my_commands))
    asyncio.run(register_commands(app))
    assert sent == [[BotCommand(c, d) for c, d in BOT_COMMANDS]]


def test_register_commands_failure_is_logged_not_raised(caplog):
    async def set_my_commands(cmds):
        raise RuntimeError("network down")
    app = SimpleNamespace(bot=SimpleNamespace(set_my_commands=set_my_commands))
    with caplog.at_level(logging.WARNING, logger="bot"):
        asyncio.run(register_commands(app))
    assert "network down" in caplog.text


def test_build_app_registers_menu_on_startup():
    app = build_app(DUMMY_CONFIG)
    assert app.post_init is register_commands


# ── slash alias → dispatcher ข้อความเดิม ──────────────────────────


def _fake_update(text, chat_id=1):
    replies = []

    async def reply_text(t, **kw):
        replies.append(t)
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id),
        message=SimpleNamespace(text=text, reply_text=reply_text)), replies


def _run_alias(monkeypatch, text, capture):
    monkeypatch.setattr(m, "CONFIG", DUMMY_CONFIG)
    for name, fake in capture.items():
        monkeypatch.setattr(m, name, fake)
    update, replies = _fake_update(text)
    args = text.split()[1:]
    asyncio.run(m.cmd_alias(update, SimpleNamespace(bot=None, args=args)))
    return replies


def test_watch_alias_add_show_remove(monkeypatch):
    calls = []

    async def fake_watch(update, action, tickers):
        calls.append((action, tickers))
    _run_alias(monkeypatch, "/watch NVDA TSLA", {"_handle_watch_command": fake_watch})
    _run_alias(monkeypatch, "/watch", {"_handle_watch_command": fake_watch})
    _run_alias(monkeypatch, "/unwatch NVDA", {"_handle_watch_command": fake_watch})
    assert calls == [("add", ["NVDA", "TSLA"]), ("show", []), ("remove", ["NVDA"])]


def test_alias_with_bot_username_suffix(monkeypatch):
    calls = []

    async def fake_watch(update, action, tickers):
        calls.append((action, tickers))
    _run_alias(monkeypatch, "/watch@Sakuro_usbot AAPL", {"_handle_watch_command": fake_watch})
    assert calls == [("add", ["AAPL"])]


def test_cal_alias_passes_days(monkeypatch):
    calls = []

    async def fake_cal(update, days):
        calls.append(days)
    _run_alias(monkeypatch, "/cal 5", {"_handle_calendar": fake_cal})
    _run_alias(monkeypatch, "/cal", {"_handle_calendar": fake_cal})
    assert calls == [5, 2]


def test_dr_alias_passes_tickers(monkeypatch):
    calls = []

    async def fake_dr(update, tickers):
        calls.append(tickers)
    _run_alias(monkeypatch, "/dr NVDA", {"_handle_dr": fake_dr})
    assert calls == [["NVDA"]]


def test_hot_summary_stats_aliases(monkeypatch):
    calls = []

    async def fake_hot(update):
        calls.append("hot")

    async def fake_weekly(bot, chat_id, notify_empty=False):
        calls.append(("weekly", notify_empty))

    async def fake_stats(bot, chat_id):
        calls.append("stats")
    fakes = {"_handle_hot": fake_hot, "_send_weekly": fake_weekly, "_send_stats": fake_stats}
    _run_alias(monkeypatch, "/hot", fakes)
    _run_alias(monkeypatch, "/summary", fakes)
    _run_alias(monkeypatch, "/stats", fakes)
    assert calls == ["hot", ("weekly", True), "stats"]


def test_alias_ignores_unauthorized_chat(monkeypatch):
    monkeypatch.setattr(m, "CONFIG", DUMMY_CONFIG)
    calls = []

    async def fake_hot(update):
        calls.append("hot")
    monkeypatch.setattr(m, "_handle_hot", fake_hot)
    update, _ = _fake_update("/hot", chat_id=999)
    asyncio.run(m.cmd_alias(update, SimpleNamespace(bot=None, args=[])))
    assert calls == []


def test_help_lists_slash_aliases(monkeypatch):
    monkeypatch.setattr(m, "CONFIG", DUMMY_CONFIG)
    update, replies = _fake_update("/help")
    asyncio.run(m.cmd_help(update, SimpleNamespace(bot=None, args=[])))
    for cmd in ("/hot", "/watch", "/unwatch", "/cal", "/dr", "/summary", "/stats"):
        assert cmd in replies[0], cmd
