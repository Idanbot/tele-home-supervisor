"""Tests for common handler utilities."""

import time
from unittest.mock import AsyncMock

import pytest
from conftest import DummyContext, DummyUpdate

from tele_home_supervisor import config
from tele_home_supervisor.handlers import common
from tele_home_supervisor.handlers.common import get_state


class TestAllowed:
    """Tests for allowed() function."""

    def test_allowed_user(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "ALLOWED", {123, 456})
        update = DummyUpdate(chat_id=123, user_id=123)
        assert common.allowed(update) is True

    def test_not_allowed_user(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "ALLOWED", {123})
        update = DummyUpdate(chat_id=999, user_id=999)
        assert common.allowed(update) is False

    def test_empty_allowed_set(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "ALLOWED", set())
        update = DummyUpdate(chat_id=123, user_id=123)
        assert common.allowed(update) is False

    def test_owner_allowed_even_if_not_in_allowlist(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "ALLOWED", set())
        monkeypatch.setattr(config, "OWNER_ID", 999)
        update = DummyUpdate(chat_id=999, user_id=999)
        assert common.allowed(update) is True

    def test_blocked_user_denied(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "ALLOWED", {123})
        monkeypatch.setattr(config, "BLOCKED_IDS", {123})
        update = DummyUpdate(chat_id=123, user_id=123)
        assert common.allowed(update) is False


class TestGuard:
    """Tests for guard() function."""

    @pytest.mark.asyncio
    async def test_guard_allows_valid_user(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "ALLOWED", {123})
        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext()
        result = await common.guard(update, context)
        assert result is True

    @pytest.mark.asyncio
    async def test_guard_blocks_invalid_user(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "ALLOWED", {123})
        monkeypatch.setattr(config, "OWNER_ID", 123)
        update = DummyUpdate(chat_id=999, user_id=999)
        update.effective_user.username = "intruder"
        update.message.text = "/status secret-argument"
        context = DummyContext()
        result = await common.guard(update, context)
        assert result is False
        assert "Not authorized" in update.effective_chat.sent[0]
        assert len(context.application.bot.sent_messages) == 1
        owner_id, notice = context.application.bot.sent_messages[0]
        assert owner_id == 123
        assert "Unauthorized Bot Interaction" in notice
        assert "999" in notice
        assert "@intruder" in notice
        assert "/status" in notice
        assert "secret-argument" not in notice

        await common.guard(update, context)
        assert len(context.application.bot.sent_messages) == 1

    @pytest.mark.asyncio
    async def test_guard_silently_blocks_blocked_user(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "ALLOWED", {123})
        monkeypatch.setattr(config, "BLOCKED_IDS", {123})
        monkeypatch.setattr(config, "OWNER_ID", 999)
        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext()
        result = await common.guard(update, context)
        assert result is False
        assert update.effective_chat.sent == []
        assert context.application.bot.sent_messages[0][0] == 999

    @pytest.mark.asyncio
    async def test_owner_notification_failure_does_not_break_guard(
        self, monkeypatch
    ) -> None:
        monkeypatch.setattr(config, "ALLOWED", {123})
        monkeypatch.setattr(config, "OWNER_ID", 123)
        update = DummyUpdate(chat_id=999, user_id=999)
        context = DummyContext()

        async def fail_to_send(**_kwargs):
            raise RuntimeError("Telegram unavailable")

        context.application.bot.send_message = fail_to_send
        assert await common.guard(update, context) is False
        assert "Not authorized" in update.effective_chat.sent[0]

    @pytest.mark.asyncio
    async def test_unhandled_message_uses_authorization_guard(
        self, monkeypatch
    ) -> None:
        guard = AsyncMock(return_value=False)
        monkeypatch.setattr(common, "guard", guard)
        update = DummyUpdate(chat_id=999, user_id=999)
        context = DummyContext()

        await common.guard_unhandled_message(update, context)

        guard.assert_awaited_once_with(update, context)


class TestGuardSensitive:
    """Tests for guard_sensitive() function."""

    @pytest.mark.asyncio
    async def test_denies_when_no_totp_configured(self, monkeypatch) -> None:
        """When TOTP is not configured, guard_sensitive should deny access."""
        monkeypatch.setattr(config, "ALLOWED", {123})
        monkeypatch.setattr(config, "BOT_AUTH_TOTP_SECRET", None)
        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext()
        result = await common.guard_sensitive(update, context)
        # Now returns False when TOTP is not configured
        assert result is False
        assert "not configured" in update.effective_chat.sent[0].lower()

    @pytest.mark.asyncio
    async def test_blocks_when_not_authenticated(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "ALLOWED", {123})
        monkeypatch.setattr(config, "BOT_AUTH_TOTP_SECRET", "SECRET")
        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext()
        result = await common.guard_sensitive(update, context)
        assert result is False
        assert "🔒" in update.effective_chat.sent[0]

    @pytest.mark.asyncio
    async def test_allows_when_authenticated(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "ALLOWED", {123})
        monkeypatch.setattr(config, "BOT_AUTH_TOTP_SECRET", "SECRET")
        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext()

        # Set up auth grant
        state = get_state(context.application)
        state.auth_grants[123] = time.time() + 3600

        result = await common.guard_sensitive(update, context)
        assert result is True


class TestAuthValid:
    """Tests for _auth_valid() function."""

    def test_valid_auth(self) -> None:
        from tele_home_supervisor.models.bot_state import BotState

        state = BotState()
        state.auth_grants[123] = time.time() + 3600
        assert common._auth_valid(state, 123) is True

    def test_expired_auth(self) -> None:
        from tele_home_supervisor.models.bot_state import BotState

        state = BotState()
        state.auth_grants[123] = time.time() - 10
        assert common._auth_valid(state, 123) is False
        # Should have removed expired grant
        assert 123 not in state.auth_grants

    def test_no_auth(self) -> None:
        from tele_home_supervisor.models.bot_state import BotState

        state = BotState()
        assert common._auth_valid(state, 123) is False


class TestRateLimit:
    """Tests for rate_limit decorator."""

    @pytest.mark.asyncio
    async def test_allows_when_not_rate_limited(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "RATE_LIMIT_S", 0.0)

        called = False

        async def handler(update, context):
            nonlocal called
            called = True

        wrapped = common.rate_limit(handler, name="test")
        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext()

        await wrapped(update, context)
        assert called is True

    @pytest.mark.asyncio
    async def test_blocks_when_rate_limited(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "RATE_LIMIT_S", 100.0)

        called = False

        async def handler(update, context):
            nonlocal called
            called = True

        wrapped = common.rate_limit(handler, name="test")
        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext()
        state = get_state(context.application)
        state.set_last_command_ts(123, "test", time.monotonic())

        await wrapped(update, context)
        assert called is False


class TestGetState:
    """Tests for get_state() function."""

    def test_creates_state_if_missing(self) -> None:
        context = DummyContext()
        state = get_state(context.application)
        assert state is not None

    def test_returns_same_state(self) -> None:
        context = DummyContext()
        state1 = get_state(context.application)
        state2 = get_state(context.application)
        assert state1 is state2


class TestAuthTtlSeconds:
    """Tests for auth_ttl_seconds() function."""

    def test_returns_configured_ttl(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "BOT_AUTH_TTL_HOURS", 168)
        ttl = common.auth_ttl_seconds()
        assert ttl == 168 * 3600

    def test_returns_custom_ttl(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "BOT_AUTH_TTL_HOURS", 48)
        ttl = common.auth_ttl_seconds()
        assert ttl == 48 * 3600
