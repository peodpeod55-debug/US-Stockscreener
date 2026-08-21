"""on_button: callback ปุ่มติดตาม/เลิกติดตาม — auth, ลำดับงาน, answer เสมอ, edit พังไม่ล้ม"""
import asyncio
from types import SimpleNamespace

from telegram import CallbackQuery, Update, User
from telegram.ext import CallbackQueryHandler

import bot.main as m
from bot.buttons import build_unwatch_markup, build_watch_markup
from bot.config import Config
from bot.main import build_app, on_button

DUMMY_CONFIG = Config(telegram_token="123:ABC", chat_id="1", fmp_api_key="k")


class FakeQuery:
    def __init__(self, data, user_id=1, markup=None,
                 answer_fails=False, edit_fails=False):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = SimpleNamespace(reply_markup=markup)
        self.log = []
        self.answers = []
        self.edits = []
        self._answer_fails = answer_fails
        self._edit_fails = edit_fails

    async def answer(self, text=None):
        self.log.append("answer")
        if self._answer_fails:
            raise RuntimeError("query is too old")
        self.answers.append(text)

    async def edit_message_reply_markup(self, reply_markup=None):
        self.log.append("edit")
        if self._edit_fails:
            raise RuntimeError("message can't be edited")
        self.edits.append(reply_markup)


def _run(query, monkeypatch, add_result=None, remove_result=None):
    monkeypatch.setattr(m, "CONFIG", DUMMY_CONFIG)

    def fake_add(syms):
        query.log.append("add")
        return add_result or {"added": list(syms), "already": [], "full": []}

    def fake_remove(syms):
        query.log.append("remove")
        return remove_result or (list(syms), [])

    monkeypatch.setattr(m, "add_symbols", fake_add)
    monkeypatch.setattr(m, "remove_everywhere", fake_remove)
    update = SimpleNamespace(callback_query=query)
    asyncio.run(on_button(update, None))


def test_callback_handler_registered():
    app = build_app(DUMMY_CONFIG)
    handlers = [h for h in app.handlers[0]
                if isinstance(h, CallbackQueryHandler)]
    assert handlers
    q = CallbackQuery(id="1", from_user=User(id=1, first_name="u", is_bot=False),
                      chat_instance="ci", data="w:EL")
    update = Update(update_id=1, callback_query=q)
    assert any(h.check_update(update) for h in handlers)


def test_watch_runs_action_before_answer_then_edits(monkeypatch):
    q = FakeQuery("w:EL", markup=build_watch_markup("EL"))
    _run(q, monkeypatch)
    assert q.log == ["add", "answer", "edit"]
    assert "EL" in q.answers[0]
    # ปุ่มถูกปลดชนวนเป็น ✓
    texts = [b.text for row in q.edits[0].inline_keyboard for b in row]
    assert texts == ["✓ ติดตามแล้ว"]


def test_watch_all_toast_summarizes(monkeypatch):
    q = FakeQuery("wa:EL,TGT", markup=build_watch_markup("EL",
                                                         all_symbols=["EL", "TGT"]))
    _run(q, monkeypatch,
         add_result={"added": ["EL"], "already": ["TGT"], "full": []})
    toast = q.answers[0]
    assert "EL" in toast and "TGT" in toast


def test_watch_full_toast_mentions_limit(monkeypatch):
    q = FakeQuery("w:EL", markup=build_watch_markup("EL"))
    _run(q, monkeypatch,
         add_result={"added": [], "already": [], "full": ["EL"]})
    assert str(m.WATCHLIST_MAX) in q.answers[0]


def test_unwatch_drops_pressed_button(monkeypatch):
    q = FakeQuery("u:EL", markup=build_unwatch_markup(["EL", "TGT"]))
    _run(q, monkeypatch)
    assert q.log == ["remove", "answer", "edit"]
    assert "EL" in q.answers[0]
    data = [b.callback_data for row in q.edits[0].inline_keyboard for b in row]
    assert data == ["u:TGT"]


def test_unauthorized_answers_silently_without_action(monkeypatch):
    q = FakeQuery("w:EL", user_id=999)
    _run(q, monkeypatch)
    assert q.log == ["answer"]


def test_invalid_data_answers_without_action(monkeypatch):
    q = FakeQuery("-")
    _run(q, monkeypatch)
    assert q.log == ["answer"]


def test_answer_failure_still_edits(monkeypatch):
    """callback ค้างช่วงบอทดับ: answer โดน query is too old — งานต้องเสร็จ+ปุ่มถูกแก้"""
    q = FakeQuery("w:EL", markup=build_watch_markup("EL"), answer_fails=True)
    _run(q, monkeypatch)
    assert q.log == ["add", "answer", "edit"]
    assert q.edits


def test_edit_failure_swallowed(monkeypatch):
    """ข้อความเก่า >48 ชม. แก้ปุ่มไม่ได้ — ห้าม exception หลุด งานหลักสำเร็จไปแล้ว"""
    q = FakeQuery("w:EL", markup=build_watch_markup("EL"), edit_fails=True)
    _run(q, monkeypatch)
    assert q.log == ["add", "answer", "edit"]


def test_no_markup_on_message_skips_edit(monkeypatch):
    """InaccessibleMessage/ไม่มี markup — เพิ่มหุ้นได้ answer ได้ ข้าม edit เงียบๆ"""
    q = FakeQuery("w:EL", markup=None)
    q.message = None
    _run(q, monkeypatch)
    assert q.log == ["add", "answer"]


def test_on_button_none_query_returns():
    asyncio.run(on_button(SimpleNamespace(callback_query=None), None))
