from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from conftest import DummyContext, DummyUpdate

from tele_home_supervisor.handlers import torrents
from tele_home_supervisor.handlers.common import get_state
from tele_home_supervisor.models.cache import CacheEntry


async def allow_guard(update, context):
    return True


@pytest.mark.asyncio
async def test_torrent_status_stop_start_delete_and_clean(monkeypatch):
    monkeypatch.setattr(torrents, "guard_sensitive", allow_guard)
    monkeypatch.setattr(
        torrents.services, "get_torrent_list", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        torrents.services, "torrent_stop", AsyncMock(return_value="stopped")
    )
    monkeypatch.setattr(
        torrents.services, "torrent_start", AsyncMock(return_value="started")
    )
    monkeypatch.setattr(
        torrents.services, "torrent_preview", AsyncMock(return_value="preview")
    )
    monkeypatch.setattr(
        torrents.services, "torrent_delete", AsyncMock(return_value="deleted")
    )
    monkeypatch.setattr(
        torrents.services,
        "torrent_preview_missing",
        AsyncMock(return_value="missing preview"),
    )
    monkeypatch.setattr(
        torrents.services,
        "torrent_clean_missing",
        AsyncMock(return_value="cleaned"),
    )
    monkeypatch.setattr(torrents.view, "render_torrent_chart", lambda items: None)
    monkeypatch.setattr(
        torrents.view,
        "render_torrent_list_page",
        lambda page_items, page, total_pages: "torrent page",
    )

    update = DummyUpdate(chat_id=1, user_id=1)
    context = DummyContext()
    state = get_state(context.application)
    state.caches["torrents"] = CacheEntry(updated_at=999999999.0, items={"Ubuntu ISO"})

    await torrents.cmd_torrent_status(update, context)
    context.args = ["Ubuntu"]
    await torrents.cmd_torrent_stop(update, context)
    await torrents.cmd_torrent_start(update, context)
    await torrents.cmd_torrent_delete(update, context)
    context.args = ["Ubuntu", "yes"]
    await torrents.cmd_torrent_delete(update, context)
    context.args = []
    await torrents.cmd_torrent_clean(update, context)
    context.args = ["yes"]
    await torrents.cmd_torrent_clean(update, context)

    replies = "\n".join(update.message.replies)
    assert "torrent page" in replies
    assert "stopped" in replies
    assert "started" in replies
    assert "preview" in replies
    assert "deleted" in replies
    assert "missing preview" in replies
    assert "cleaned" in replies


@pytest.mark.asyncio
async def test_subscribe_modes(monkeypatch):
    monkeypatch.setattr(torrents, "guard_sensitive", allow_guard)
    monkeypatch.setattr(torrents, "ensure_started", Mock())

    update = DummyUpdate(chat_id=5, user_id=5)
    context = DummyContext(args=["status"])
    await torrents.cmd_subscribe(update, context)
    await torrents.cmd_subscribe(update, DummyContext(args=["on"]))
    await torrents.cmd_subscribe(update, DummyContext(args=["off"]))
    await torrents.cmd_subscribe(update, DummyContext(args=["bad"]))

    replies = "\n".join(update.message.replies)
    assert "OFF" in replies
    assert "ON" in replies
    assert "Usage" in replies


@pytest.mark.asyncio
async def test_piratebay_commands_and_provider_toggles(monkeypatch):
    monkeypatch.setattr(torrents, "guard_sensitive", allow_guard)
    monkeypatch.setattr(torrents.piratebay, "resolve_category", lambda value: "100")
    monkeypatch.setattr(torrents.piratebay, "resolve_top_mode", lambda value: None)
    monkeypatch.setattr(torrents.piratebay, "category_help", lambda: "all")
    monkeypatch.setattr(
        torrents.services,
        "piratebay_top",
        AsyncMock(
            return_value=[{"name": "Top", "seeders": 10, "leechers": 1, "magnet": "m"}]
        ),
    )
    monkeypatch.setattr(
        torrents.services,
        "piratebay_search",
        AsyncMock(
            return_value=[
                {"name": "Search", "seeders": 5, "leechers": 2, "magnet": "m2"}
            ]
        ),
    )
    monkeypatch.setattr(
        torrents.torrentsources, "get_last_used_provider", lambda: "api"
    )
    monkeypatch.setattr(torrents.torrentsources, "get_forced_provider", lambda: None)
    monkeypatch.setattr(
        torrents.torrentsources,
        "get_provider_status",
        lambda: [{"name": "apibay", "enabled": True, "forced": False}],
    )
    monkeypatch.setattr(
        torrents.torrentsources,
        "get_available_provider_names",
        lambda: ["apibay"],
    )
    set_forced = Mock(side_effect=lambda name: name in {None, "apibay"})
    monkeypatch.setattr(torrents.torrentsources, "set_forced_provider", set_forced)
    monkeypatch.setattr(
        torrents.torrentsources,
        "toggle_provider",
        lambda name: (name == "apibay", False),
    )

    update = DummyUpdate(chat_id=1, user_id=1)
    context = DummyContext(args=["100"])
    await torrents.cmd_pbtop(update, context)
    await torrents.cmd_pbsearch(update, DummyContext(args=["ubuntu"]))
    await torrents.cmd_pbprovider(update, DummyContext(args=[]))
    await torrents.cmd_pbprovider(update, DummyContext(args=["auto"]))
    await torrents.cmd_pbprovider(update, DummyContext(args=["apibay"]))
    await torrents.cmd_pbprovider(update, DummyContext(args=["missing"]))
    await torrents.cmd_pbtoggle(update, DummyContext(args=[]))
    await torrents.cmd_pbtoggle(update, DummyContext(args=["1"]))
    await torrents.cmd_pbtoggle(update, DummyContext(args=["missing"]))

    replies = "\n".join(update.message.replies)
    assert "Pirate Bay Top" in replies
    assert "Pirate Bay Search" in replies
    assert "Provider Status" in replies
    assert "auto-fallback" in replies
    assert "apibay" in replies
    assert "Unknown provider" in replies


def test_piratebay_keyboard_and_format_helpers():
    state = Mock()
    state.store_magnet.side_effect = ["a", "b"]
    results = [
        {"name": "A" * 80, "seeders": 10, "leechers": 1, "magnet": "m"},
        {"name": "No Magnet", "seeders": 0, "leechers": 0, "magnet": ""},
        {"name": "Short", "seeders": 5, "leechers": 2, "magnet": "m2"},
    ]

    keyboard = torrents._build_piratebay_keyboard(state, results)
    formatted = torrents._format_piratebay_list("Title", results)

    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 2
    assert keyboard.inline_keyboard[0][0].callback_data == "pbselect:a"
    assert "Title" in formatted
    assert "Short" in formatted
    assert torrents._has_torrent_match({"Ubuntu ISO"}, "ubuntu") is True
    assert torrents._has_torrent_match({"Ubuntu ISO"}, "missing") is False
