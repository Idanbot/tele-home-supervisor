"""Tests for /check_auth command."""

import time

import pytest

from tele_home_supervisor import config
from tele_home_supervisor.handlers import meta
from tele_home_supervisor.handlers.common import get_state

from conftest import DummyContext, DummyUpdate


@pytest.mark.asyncio
async def test_check_auth_not_authenticated(monkeypatch) -> None:
    monkeypatch.setattr(config, "ALLOWED", {123})
    monkeypatch.setattr(config, "BOT_AUTH_TOTP_SECRET", "BASE32")
    update = DummyUpdate(chat_id=123, user_id=123)
    context = DummyContext()

    await meta.cmd_check_auth(update, context)

    assert len(update.message.replies) == 1
    assert "Not authenticated" in update.message.replies[0]


@pytest.mark.asyncio
async def test_check_auth_authenticated(monkeypatch) -> None:
    monkeypatch.setattr(config, "ALLOWED", {123})
    monkeypatch.setattr(config, "BOT_AUTH_TOTP_SECRET", "BASE32")
    update = DummyUpdate(chat_id=123, user_id=123)
    context = DummyContext()

    # Set up auth grant
    state = get_state(context.application)
    state.auth_grants[123] = time.monotonic() + 3600  # 1 hour from now

    await meta.cmd_check_auth(update, context)

    assert len(update.message.replies) == 1
    assert "Authenticated" in update.message.replies[0]
    assert "Expires in" in update.message.replies[0]


@pytest.mark.asyncio
async def test_check_auth_expired(monkeypatch) -> None:
    monkeypatch.setattr(config, "ALLOWED", {123})
    monkeypatch.setattr(config, "BOT_AUTH_TOTP_SECRET", "BASE32")
    update = DummyUpdate(chat_id=123, user_id=123)
    context = DummyContext()

    # Set up expired auth grant
    state = get_state(context.application)
    state.auth_grants[123] = time.monotonic() - 10  # Expired

    await meta.cmd_check_auth(update, context)

    assert len(update.message.replies) == 1
    assert "Not authenticated" in update.message.replies[0]
    # Should have cleaned up expired grant
    assert 123 not in state.auth_grants


@pytest.mark.asyncio
async def test_check_auth_no_totp_secret(monkeypatch) -> None:
    monkeypatch.setattr(config, "ALLOWED", {123})
    monkeypatch.setattr(config, "BOT_AUTH_TOTP_SECRET", None)
    update = DummyUpdate(chat_id=123, user_id=123)
    context = DummyContext()

    await meta.cmd_check_auth(update, context)

    assert update.message.replies == ["⛔ BOT_AUTH_TOTP_SECRET is not configured."]
