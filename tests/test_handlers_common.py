"""Tests for common handler utilities."""

import time

import pytest

from tele_home_supervisor import config
from tele_home_supervisor.handlers import common
from tele_home_supervisor.handlers.common import get_state

from conftest import DummyContext, DummyUpdate


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
        update = DummyUpdate(chat_id=999, user_id=999)
        context = DummyContext()
        result = await common.guard(update, context)
        assert result is False


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
        monkeypatch.setattr(common, "_last_command_ts", 0.0)

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
        monkeypatch.setattr(common, "_last_command_ts", time.monotonic())

        called = False

        async def handler(update, context):
            nonlocal called
            called = True

        wrapped = common.rate_limit(handler, name="test")
        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext()

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

    def test_returns_24_hours(self) -> None:
        ttl = common.auth_ttl_seconds()
        assert ttl == 24 * 60 * 60
