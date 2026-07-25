from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from conftest import DummyContext, DummyUpdate

from tele_home_supervisor import background
from tele_home_supervisor.handlers import release_watches
from tele_home_supervisor.models.bot_state import BOT_STATE_KEY, BotState


async def allow_sensitive(update, context):
    return True


def _state(context: DummyContext, tmp_path: Path) -> BotState:
    state = BotState()
    state._state_file = tmp_path / "state.json"
    state._database_file = tmp_path / "state.sqlite3"
    context.application.bot_data[BOT_STATE_KEY] = state
    return state


@pytest.mark.asyncio
async def test_releasewatch_add_list_remove(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(release_watches, "guard_sensitive", allow_sensitive)
    context = DummyContext(args=["add", "movie", "1080p", "Dune", "Part", "Two"])
    state = _state(context, tmp_path)
    update = DummyUpdate(chat_id=7, user_id=7)

    await release_watches.cmd_releasewatch(update, context)
    watch = state.release_watches[0]
    assert watch.query == "Dune Part Two"
    assert watch.min_quality == "1080p"
    assert "Watching" in update.message.replies[-1]

    context.args = []
    await release_watches.cmd_releasewatch(update, context)
    assert watch.id in update.message.replies[-1]

    context.args = ["remove", watch.id]
    await release_watches.cmd_releasewatch(update, context)
    assert not state.release_watches
    assert "removed" in update.message.replies[-1]


@pytest.mark.asyncio
async def test_releasewatch_game_and_manual_check(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(release_watches, "guard_sensitive", allow_sensitive)
    context = DummyContext(args=["add", "game", "Hades", "II"])
    _state(context, tmp_path)
    update = DummyUpdate(chat_id=8, user_id=8)
    await release_watches.cmd_releasewatch(update, context)

    monkeypatch.setattr(
        release_watches.background,
        "check_release_watches",
        AsyncMock(return_value=1),
    )
    context.args = ["check"]
    await release_watches.cmd_releasewatch(update, context)
    assert "1 watch(es) triggered" in update.message.replies[-1]


@pytest.mark.asyncio
async def test_check_release_watches_disables_only_after_send(
    monkeypatch, tmp_path
) -> None:
    context = DummyContext()
    state = _state(context, tmp_path)
    watch = state.add_release_watch(9, "episode", "Show S01E02", "720p")
    assert watch is not None
    match = {"name": "Show S01E02 1080p", "seeders": 10, "leechers": 1}
    monkeypatch.setattr(
        background.release_monitor, "check_watch", AsyncMock(return_value=match)
    )

    triggered = await background.check_release_watches(context.application)
    assert triggered == 1
    assert watch.enabled is False
    assert watch.matched_name == "Show S01E02 1080p"
    assert len(context.application.bot.sent_messages) == 1

    failed_context = DummyContext()
    failed_state = _state(failed_context, tmp_path / "failed")
    failed_watch = failed_state.add_release_watch(9, "game", "Game", None)
    assert failed_watch is not None
    failed_context.application.bot.send_message = AsyncMock(
        side_effect=RuntimeError("telegram offline")
    )
    triggered = await background.check_release_watches(failed_context.application)
    assert triggered == 0
    assert failed_watch.enabled is True
