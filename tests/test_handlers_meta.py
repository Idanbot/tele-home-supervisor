"""Tests for meta handlers (auth, metrics, debug, etc.)."""

import time

import pytest

from tele_home_supervisor import config
from tele_home_supervisor.handlers import meta
from tele_home_supervisor.handlers.common import get_state

from conftest import DummyContext, DummyUpdate


class TestCmdStart:
    """Tests for /start command."""

    @pytest.mark.asyncio
    async def test_returns_help_text(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "ALLOWED", {123})
        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext()

        await meta.cmd_start(update, context)

        assert len(update.message.replies) == 1
        reply = update.message.replies[0]
        assert "Commands" in reply or "Hi" in reply


class TestCmdHelp:
    """Tests for /help command."""

    @pytest.mark.asyncio
    async def test_same_as_start(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "ALLOWED", {123})
        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext()

        await meta.cmd_help(update, context)

        # Should have same output as start
        assert len(update.message.replies) == 1


class TestCmdWhoami:
    """Tests for /whoami command."""

    @pytest.mark.asyncio
    async def test_shows_chat_info(self) -> None:
        update = DummyUpdate(chat_id=123, user_id=456)
        context = DummyContext()

        await meta.cmd_whoami(update, context)

        assert len(update.message.replies) == 1
        reply = update.message.replies[0]
        assert "123" in reply  # chat_id
        assert "chat_id" in reply


class TestCmdVersion:
    """Tests for /version command."""

    @pytest.mark.asyncio
    async def test_shows_version(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "ALLOWED", {123})
        monkeypatch.setattr(config, "BOT_AUTH_TOTP_SECRET", None)

        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext()

        await meta.cmd_version(update, context)

        assert len(update.message.replies) == 1


class TestCmdAuth:
    """Tests for /auth command."""

    @pytest.mark.asyncio
    async def test_requires_totp_secret(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "ALLOWED", {123})
        monkeypatch.setattr(config, "BOT_AUTH_TOTP_SECRET", None)
        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext(args=["123456"])

        await meta.cmd_auth(update, context)

        assert "not configured" in update.message.replies[0]

    @pytest.mark.asyncio
    async def test_requires_code_arg(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "ALLOWED", {123})
        monkeypatch.setattr(config, "BOT_AUTH_TOTP_SECRET", "SECRET")
        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext(args=[])

        await meta.cmd_auth(update, context)

        assert "Usage" in update.message.replies[0]


class TestCmdCheckAuth:
    """Tests for /check_auth command."""

    @pytest.mark.asyncio
    async def test_not_authenticated(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "ALLOWED", {123})
        monkeypatch.setattr(config, "BOT_AUTH_TOTP_SECRET", "SECRET")
        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext()

        await meta.cmd_check_auth(update, context)

        assert "Not authenticated" in update.message.replies[0]

    @pytest.mark.asyncio
    async def test_authenticated_shows_expiry(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "ALLOWED", {123})
        monkeypatch.setattr(config, "BOT_AUTH_TOTP_SECRET", "SECRET")
        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext()

        state = get_state(context.application)
        state.auth_grants[123] = time.time() + 3600

        await meta.cmd_check_auth(update, context)

        assert "Authenticated" in update.message.replies[0]
        assert "Expires" in update.message.replies[0]


class TestCmdMetrics:
    """Tests for /metrics command."""

    @pytest.mark.asyncio
    async def test_shows_metrics(self, monkeypatch) -> None:
        async def mock_guard(update, context):
            return True

        monkeypatch.setattr(meta, "guard_sensitive", mock_guard)

        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext()

        # Add reply_photo method
        update.message.photos = []

        async def reply_photo(photo, caption="", **kwargs):
            update.message.photos.append((photo, caption))

        update.message.reply_photo = reply_photo

        await meta.cmd_metrics(update, context)

        # Should have either a photo or text reply
        assert len(update.message.replies) >= 1 or len(update.message.photos) >= 1


class TestCmdDebug:
    """Tests for /debug command."""

    @pytest.mark.asyncio
    async def test_shows_debug_info(self, monkeypatch) -> None:
        async def mock_guard(update, context):
            return True

        monkeypatch.setattr(meta, "guard_sensitive", mock_guard)

        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext()

        await meta.cmd_debug(update, context)

        assert len(update.message.replies) >= 1


class TestRenderHelp:
    """Tests for _render_help function."""

    def test_includes_command_groups(self) -> None:
        result = meta._render_help()
        assert "System" in result or "Docker" in result or "Info" in result

    def test_includes_commands(self) -> None:
        result = meta._render_help()
        assert "/help" in result or "/start" in result
