"""Tests for the background graceful shutdown mechanism."""

from __future__ import annotations

import asyncio
import pytest

from tele_home_supervisor import background
from tele_home_supervisor.models.bot_state import BotState


@pytest.fixture(autouse=True)
def _reset_shutdown_flag():
    """Ensure the shutdown flag is clean before/after each test."""
    background._shutdown_requested = False
    yield
    background._shutdown_requested = False


@pytest.mark.asyncio
async def test_interruptible_sleep_normal_timeout() -> None:
    """_interruptible_sleep returns False when timeout elapses normally."""
    result = await background._interruptible_sleep(0.05)
    assert result is False


@pytest.mark.asyncio
async def test_interruptible_sleep_shutdown_requested() -> None:
    """_interruptible_sleep returns True immediately when shutdown is set."""
    background.request_shutdown()
    result = await background._interruptible_sleep(10.0)
    assert result is True


@pytest.mark.asyncio
async def test_request_shutdown_sets_flag() -> None:
    assert background._shutdown_requested is False
    background.request_shutdown()
    assert background._shutdown_requested is True


@pytest.mark.asyncio
async def test_cancel_tasks_clears_state() -> None:
    state = BotState()

    # Create a dummy long-running task
    async def _dummy_loop():
        while True:
            await asyncio.sleep(0.01)

    state.tasks["test_task"] = asyncio.create_task(_dummy_loop())

    await background.cancel_tasks(state)

    assert state.tasks == {}
    assert background._shutdown_requested is True


@pytest.mark.asyncio
async def test_cancel_tasks_handles_already_done() -> None:
    """cancel_tasks should not error on tasks that finished before cancel."""
    state = BotState()

    async def _instant():
        return

    task = asyncio.create_task(_instant())
    await task  # let it complete
    state.tasks["done_task"] = task

    await background.cancel_tasks(state)
    assert state.tasks == {}
