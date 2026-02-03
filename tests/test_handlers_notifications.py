"""Tests for notification handlers."""

import pytest
from unittest.mock import AsyncMock, patch

from tele_home_supervisor import config
from tele_home_supervisor.handlers import notifications
from tele_home_supervisor.handlers.common import get_state

from conftest import DummyContext, DummyUpdate


class TestMuteCommands:
    """Tests for mute toggle commands."""

    @pytest.mark.asyncio
    async def test_cmd_mute_gameoffers_toggles(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "ALLOWED", {123})
        monkeypatch.setattr(config, "BOT_AUTH_TOTP_SECRET", None)

        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext()

        # First call - mutes
        await notifications.cmd_mute_gameoffers(update, context)
        state = get_state(context.application)
        assert 123 in state.gameoffers_muted
        assert "muted" in update.message.replies[0].lower()

        # Second call - unmutes
        update.message.replies.clear()
        await notifications.cmd_mute_gameoffers(update, context)
        assert 123 not in state.gameoffers_muted
        assert (
            "unmuted" in update.message.replies[0].lower()
            or "enabled" in update.message.replies[0].lower()
        )

    @pytest.mark.asyncio
    async def test_cmd_mute_hackernews_toggles(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "ALLOWED", {123})
        monkeypatch.setattr(config, "BOT_AUTH_TOTP_SECRET", None)

        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext()

        # First call - mutes
        await notifications.cmd_mute_hackernews(update, context)
        state = get_state(context.application)
        assert 123 in state.hackernews_muted

        # Second call - unmutes
        await notifications.cmd_mute_hackernews(update, context)
        assert 123 not in state.hackernews_muted


class TestOnDemandCommands:
    """Tests for on-demand fetch commands."""

    @pytest.mark.asyncio
    async def test_cmd_hackernews_now_default_limit(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "ALLOWED", {123})
        monkeypatch.setattr(config, "BOT_AUTH_TOTP_SECRET", None)

        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext()

        # Add edit_text to the reply message
        update.message.edit_text = AsyncMock()

        with patch("tele_home_supervisor.scheduled.fetch_hackernews_top") as mock_fetch:
            mock_fetch.return_value = "<b>HN:</b>\n1. Story"

            await notifications.cmd_hackernews_now(update, context)

            # Should have called with default limit
            mock_fetch.assert_called_once()
            args = mock_fetch.call_args
            assert args[0][0] == 5  # default limit

    @pytest.mark.asyncio
    async def test_cmd_hackernews_now_custom_limit(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "ALLOWED", {123})
        monkeypatch.setattr(config, "BOT_AUTH_TOTP_SECRET", None)

        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext(args=["10"])

        update.message.edit_text = AsyncMock()

        with patch("tele_home_supervisor.scheduled.fetch_hackernews_top") as mock_fetch:
            mock_fetch.return_value = "<b>HN:</b>\n1. Story"

            await notifications.cmd_hackernews_now(update, context)

            args = mock_fetch.call_args
            assert args[0][0] == 10

    @pytest.mark.asyncio
    async def test_cmd_steamfree_now_fetches(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "ALLOWED", {123})
        monkeypatch.setattr(config, "BOT_AUTH_TOTP_SECRET", None)

        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext()
        update.message.edit_text = AsyncMock()

        with patch(
            "tele_home_supervisor.scheduled.fetch_steam_free_games"
        ) as mock_fetch:
            mock_fetch.return_value = ("<b>Steam Free:</b>\nNo games", [])

            await notifications.cmd_steamfree_now(update, context)

            mock_fetch.assert_called_once()
