from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from conftest import DummyContext, DummyUpdate

from tele_home_supervisor.handlers import notifications


async def allow_guard(update, context):
    return True


@pytest.mark.asyncio
async def test_mute_commands_and_intel_settings(monkeypatch):
    monkeypatch.setattr(notifications, "guard", allow_guard)
    update = DummyUpdate(chat_id=1, user_id=1)
    context = DummyContext()

    await notifications.cmd_mute_gameoffers(update, context)
    await notifications.cmd_mute_gameoffers(update, context)
    await notifications.cmd_mute_hackernews(update, context)
    await notifications.cmd_mute_hackernews(update, context)
    await notifications.cmd_intel_settings(update, context)

    replies = "\n".join(update.message.replies)
    assert "muted" in replies
    assert "enabled" in replies
    assert "Intel Briefing Settings" in replies


@pytest.mark.asyncio
async def test_on_demand_game_and_news_commands(monkeypatch):
    monkeypatch.setattr(notifications, "guard", allow_guard)
    update = DummyUpdate(chat_id=1, user_id=1)
    context = DummyContext()

    async def delete():
        update.message.replies.append("deleted")

    async def reply_text(text, **kwargs):
        update.message.replies.append(text)
        msg = update.message
        msg.delete = delete
        return msg

    update.message.reply_text = reply_text
    monkeypatch.setattr(
        notifications.scheduled_fetchers,
        "build_combined_game_offers",
        AsyncMock(return_value=("combined", None)),
    )
    monkeypatch.setattr(
        notifications.scheduled_fetchers,
        "fetch_hackernews_top",
        AsyncMock(return_value="hn"),
    )
    monkeypatch.setattr(
        notifications.scheduled_fetchers,
        "fetch_steam_free_games",
        AsyncMock(return_value=("steam", [])),
    )
    monkeypatch.setattr(
        notifications.scheduled_fetchers,
        "fetch_epic_free_games",
        AsyncMock(return_value=("epic", [])),
    )
    monkeypatch.setattr(
        notifications.scheduled_fetchers,
        "fetch_gog_free_games",
        AsyncMock(return_value=("gog", [])),
    )
    monkeypatch.setattr(
        notifications.scheduled_fetchers,
        "fetch_humble_free_games",
        AsyncMock(return_value=("humble", [])),
    )

    await notifications.cmd_gameoffers_now(update, context)
    await notifications.cmd_hackernews_now(update, DummyContext(args=["3"]))
    await notifications.cmd_steamfree_now(update, DummyContext(args=["3"]))
    await notifications.cmd_epicgames_now(update, context)
    await notifications.cmd_gogfree_now(update, context)
    await notifications.cmd_humblefree_now(update, context)

    replies = "\n".join(update.message.replies)
    assert "combined" in replies
    assert "hn" in replies
    assert "steam" in replies
    assert "epic" in replies
    assert "gog" in replies
    assert "humble" in replies


@pytest.mark.asyncio
async def test_notification_error_and_usage_paths(monkeypatch):
    monkeypatch.setattr(notifications, "guard", allow_guard)
    update = DummyUpdate(chat_id=1, user_id=1)

    await notifications.cmd_hackernews_now(update, DummyContext(args=["bad"]))
    await notifications.cmd_steamfree_now(update, DummyContext(args=["bad"]))

    monkeypatch.setattr(
        notifications.scheduled_fetchers,
        "fetch_hackernews_top",
        AsyncMock(side_effect=RuntimeError("offline")),
    )
    await notifications.cmd_hackernews_now(update, DummyContext(args=["2"]))

    replies = "\n".join(update.message.replies)
    assert "Usage: /hackernews" in replies
    assert "Usage: /steamfree" in replies
    assert "offline" in replies


@pytest.mark.asyncio
async def test_intel_toggle_and_briefing(monkeypatch):
    monkeypatch.setattr(notifications, "guard", allow_guard)
    update = DummyUpdate(chat_id=1, user_id=1)
    context = DummyContext()
    query = Mock()
    query.data = "intel_toggle:weather"
    query.answer = AsyncMock()
    query.edit_message_reply_markup = AsyncMock()
    update.callback_query = query

    await notifications.cb_intel_toggle(update, context)
    query.answer.assert_awaited_once()
    query.edit_message_reply_markup.assert_awaited_once()

    monkeypatch.setattr(
        notifications.intel,
        "build_intel_briefing",
        AsyncMock(return_value="briefing"),
    )
    await notifications.cmd_intel_briefing(update, context)
    assert "briefing" in update.message.replies[-1]
