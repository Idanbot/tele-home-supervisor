import time

import pytest
from conftest import DummyContext, DummyUpdate

from tele_home_supervisor import config, security
from tele_home_supervisor.handlers import common
from tele_home_supervisor.handlers.security import cmd_security
from tele_home_supervisor.models import database
from tele_home_supervisor.models.bot_state import BotState
from tele_home_supervisor.state import BOT_STATE_KEY


def test_attempts_survive_reopening_and_aggregate(tmp_path):
    path = tmp_path / "state.sqlite3"
    assert security.record_attempt(path, 99, 99, "test", "/start", 1000) == (True, 1)
    assert security.record_attempt(path, 99, 99, "test", "/help", 1001) == (False, 1)
    assert security.record_attempt(path, 99, 99, "test", "/status", 1300) == (True, 2)
    row = security.recent_attempts(path, 1301)[0]
    assert row["attempts"] == 3
    assert row["first_seen"] == 1000
    assert row["last_seen"] == 1300
    assert row["action"] == "/status"
    assert database.schema_version(path) == 3


def test_attempt_retention_and_identity_limit(tmp_path, monkeypatch):
    path = tmp_path / "state.sqlite3"
    monkeypatch.setattr(security, "MAX_IDENTITIES", 2)
    for uid in range(3):
        security.record_attempt(path, uid, uid, "test", "/start", 1000 + uid)
    assert len(security.recent_attempts(path, 1003)) == 2
    assert security.recent_attempts(path, 1003 + security.RETENTION_SECONDS) == []


@pytest.fixture
def secured_context(tmp_path):
    context = DummyContext()
    state = BotState(_database_file=tmp_path / "state.sqlite3")
    state._state_loaded = True
    context.application.bot_data[BOT_STATE_KEY] = state
    return context, state


@pytest.mark.asyncio
async def test_records_suppressed_attempts_and_restart_cooldown(
    secured_context, monkeypatch
):
    context, state = secured_context
    monkeypatch.setattr(config, "OWNER_ID", 123)
    update = DummyUpdate(999, 999)
    update.message.text = "/auth 123456"
    await common.notify_owner_unauthorized_attempt(update, context, state)
    state._last_unauthorized_notice_ts.clear()
    await common.notify_owner_unauthorized_attempt(update, context, state)
    assert len(context.bot.sent_messages) == 1
    row = security.recent_attempts(state._database_file, time.time())[0]
    assert row["attempts"] == 2
    assert row["action"] == "/auth"
    assert "123456" not in str(context.bot.sent_messages)


@pytest.mark.asyncio
async def test_security_owner_review_and_ban(secured_context, monkeypatch):
    context, state = secured_context
    monkeypatch.setattr(config, "OWNER_ID", 123)
    security.record_attempt(
        state._database_file, 999, 999, "<attacker>", "/start", time.time()
    )
    update = DummyUpdate(123, 123)
    await cmd_security(update, context)
    assert "<attacker>" in update.message.replies[0]
    assert "999" in update.message.replies[0]
    context.args = ["ban", "999"]
    await cmd_security(update, context)
    assert 999 in state.blocked_ids


@pytest.mark.asyncio
async def test_security_denies_non_owner(secured_context, monkeypatch):
    context, _ = secured_context
    monkeypatch.setattr(config, "OWNER_ID", 123)
    monkeypatch.setattr(config, "ALLOWED", {456})
    update = DummyUpdate(456, 456)
    await cmd_security(update, context)
    assert update.message.replies == []
    assert "Owner only" in update.effective_chat.sent[0]


@pytest.mark.asyncio
async def test_no_plain_text_or_callback_payload_stored(secured_context):
    context, state = secured_context
    update = DummyUpdate(999, 999)
    update.message.text = "sensitive private message"
    assert common._unauthorized_interaction_name(update) == "message"
    update.callback_query = type("Query", (), {"data": "secret:123456"})()
    assert common._unauthorized_interaction_name(update) == "callback: secret"
