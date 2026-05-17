from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from conftest import DummyContext, DummyUpdate

from tele_home_supervisor.handlers import system
from tele_home_supervisor.handlers.common import get_state


async def allow_guard(update, context):
    return True


@pytest.mark.asyncio
async def test_system_info_commands(monkeypatch):
    monkeypatch.setattr(system, "guard_sensitive", allow_guard)
    monkeypatch.setattr(
        system.services.utils, "get_primary_ip", AsyncMock(return_value="192.168.1.5")
    )
    monkeypatch.setattr(
        system.services.utils, "get_wan_ip", AsyncMock(return_value="8.8.8.8")
    )
    monkeypatch.setattr(
        system.services, "host_health", AsyncMock(return_value={"host": "pi"})
    )
    monkeypatch.setattr(
        system.view, "render_host_health", lambda data, show_wan=False: "health"
    )
    monkeypatch.setattr(
        system.view, "render_command_metrics", lambda metrics: "metrics"
    )
    monkeypatch.setattr(system.view, "render_health_chart", lambda data: None)
    monkeypatch.setattr(
        system.services, "get_uptime_info", AsyncMock(return_value="1 day")
    )
    monkeypatch.setattr(system.services, "get_cpu_temp", AsyncMock(return_value="42C"))
    monkeypatch.setattr(
        system.services, "get_top_processes", AsyncMock(return_value="top")
    )
    monkeypatch.setattr(system.services, "ping_host", AsyncMock(return_value="pong"))

    update = DummyUpdate(chat_id=1, user_id=1)
    context = DummyContext(args=["example.com", "2"])

    await system.cmd_ip(update, context)
    await system.cmd_health(update, context)
    await system.cmd_uptime(update, context)
    await system.cmd_temp(update, context)
    await system.cmd_top(update, context)
    await system.cmd_ping(update, context)

    replies = "\n".join(update.message.replies)
    assert "192.168.1.5" in replies
    assert "health" in replies
    assert "1 day" in replies
    assert "42C" in replies
    assert "top" in replies
    assert "pong" in replies


@pytest.mark.asyncio
async def test_remind_list_cancel_create_and_cleanup(monkeypatch):
    monkeypatch.setattr(system, "guard_sensitive", allow_guard)
    monkeypatch.setattr(system, "delete_media_messages", AsyncMock(return_value=2))

    update = DummyUpdate(chat_id=1, user_id=1)
    context = DummyContext(args=["0.01", "drink", "water"])
    state = get_state(context.application)

    await system.cmd_remind(update, context)
    context.args = ["list"]
    await system.cmd_remind(update, context)
    reminder_id = state.get_reminders(1)[0]["id"]
    context.args = ["cancel", reminder_id]
    await system.cmd_remind(update, context)
    context.args = ["cancel", "missing"]
    await system.cmd_remind(update, context)

    await system.cmd_cleanup(update, context)
    state.track_media_message(1, 10)
    state.track_media_message(1, 11)
    await system.cmd_cleanup(update, context)

    replies = "\n".join(update.message.replies)
    assert "Reminder set" in replies
    assert "Your Reminders" in replies
    assert "cancelled" in replies
    assert "not found" in replies
    assert "No tracked media" in replies
    assert "Deleted 2/2" in replies


def test_draw_bar_clamps():
    assert system._draw_bar(-10, length=4) == "░░░░"
    assert system._draw_bar(50, length=4) == "██░░"
    assert system._draw_bar(150, length=4) == "████"
