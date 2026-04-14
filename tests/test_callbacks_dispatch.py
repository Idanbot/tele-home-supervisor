"""Tests for the callback query dispatcher and the new sub-modules."""

from __future__ import annotations

import pytest
from typing import Any

from tele_home_supervisor.handlers import callbacks, cb_docker, cb_torrents, cb_media
from tele_home_supervisor.handlers.cb_helpers import (
    build_pagination_row,
    parse_page,
    safe_edit_message_text,
)


# ---------------------------------------------------------------------------
# Lightweight test doubles
# ---------------------------------------------------------------------------


class _DummyQuery:
    """Minimal CallbackQuery stand-in."""

    def __init__(self, data: str = "") -> None:
        self.data = data
        self.message = _DummyMessage()
        self._answered = False
        self._edited_texts: list[str] = []

    async def answer(self, text: str | None = None) -> None:
        self._answered = True

    async def edit_message_text(self, text: str, **_: Any) -> None:
        self._edited_texts.append(text)


class _DummyMessage:
    def __init__(self) -> None:
        self.replies: list[str] = []
        self.chat = type("C", (), {"id": 1})()

    async def reply_text(self, text: str, **_: Any) -> "_DummyMessage":
        self.replies.append(text)
        return self


class _DummyUpdate:
    def __init__(self, data: str) -> None:
        self.callback_query = _DummyQuery(data)
        self.effective_chat = type("C", (), {"id": 1})()
        self.effective_user = type("U", (), {"id": 1, "username": "test"})()

    @property
    def message(self):
        return self.callback_query.message


class _DummyApp:
    def __init__(self) -> None:
        self.bot_data: dict[str, object] = {}


class _DummyContext:
    def __init__(self) -> None:
        self.application = _DummyApp()
        self.args: list[str] = []


# ---------------------------------------------------------------------------
# cb_helpers unit tests
# ---------------------------------------------------------------------------


def test_parse_page_valid() -> None:
    assert parse_page("docker:page:3", "docker:page:") == 3


def test_parse_page_invalid() -> None:
    assert parse_page("docker:page:abc", "docker:page:") == 0


def test_parse_page_negative_clamped() -> None:
    assert parse_page("docker:page:-5", "docker:page:") == 0


def test_build_pagination_row_single_page() -> None:
    row = build_pagination_row(0, 1, "docker:page")
    assert row == []


def test_build_pagination_row_first_page() -> None:
    row = build_pagination_row(0, 3, "docker:page")
    labels = [btn.text for btn in row]
    assert "⬅️ Prev" not in labels
    assert "Next ➡️" in labels
    assert "📄 1/3" in labels


def test_build_pagination_row_middle_page() -> None:
    row = build_pagination_row(1, 3, "docker:page")
    labels = [btn.text for btn in row]
    assert "⬅️ Prev" in labels
    assert "Next ➡️" in labels


def test_build_pagination_row_last_page() -> None:
    row = build_pagination_row(2, 3, "docker:page")
    labels = [btn.text for btn in row]
    assert "⬅️ Prev" in labels
    assert "Next ➡️" not in labels


@pytest.mark.asyncio
async def test_safe_edit_no_error() -> None:
    query = _DummyQuery()
    await safe_edit_message_text(query, "hello")
    assert query._edited_texts == ["hello"]


# ---------------------------------------------------------------------------
# Callback router tests – verify dispatch reaches the right sub-module
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_unknown_action(monkeypatch) -> None:
    monkeypatch.setattr(callbacks, "allowed", lambda *_: True)
    update = _DummyUpdate("totally:unknown:action")
    ctx = _DummyContext()
    await callbacks.handle_callback_query(update, ctx)
    assert "Unknown action" in update.callback_query._edited_texts[0]


@pytest.mark.asyncio
async def test_dispatch_noop_docker(monkeypatch) -> None:
    monkeypatch.setattr(callbacks, "allowed", lambda *_: True)
    update = _DummyUpdate("docker:noop")
    ctx = _DummyContext()
    await callbacks.handle_callback_query(update, ctx)
    assert update.callback_query._edited_texts == []
    assert update.callback_query.message.replies == []


@pytest.mark.asyncio
async def test_dispatch_noop_torrent(monkeypatch) -> None:
    monkeypatch.setattr(callbacks, "allowed", lambda *_: True)
    update = _DummyUpdate("torrent:noop")
    ctx = _DummyContext()
    await callbacks.handle_callback_query(update, ctx)
    assert update.callback_query._edited_texts == []


@pytest.mark.asyncio
async def test_dispatch_unauthorized(monkeypatch) -> None:
    monkeypatch.setattr(callbacks, "allowed", lambda *_: False)
    update = _DummyUpdate("docker:refresh")
    ctx = _DummyContext()
    await callbacks.handle_callback_query(update, ctx)
    assert "Not authorized" in update.callback_query._edited_texts[0]


@pytest.mark.asyncio
async def test_dispatch_silently_ignores_blocked_user(monkeypatch) -> None:
    monkeypatch.setattr(callbacks, "allowed", lambda *_: True)
    monkeypatch.setattr(callbacks, "is_blocked_user_id", lambda *_: True)
    update = _DummyUpdate("docker:refresh")
    ctx = _DummyContext()
    await callbacks.handle_callback_query(update, ctx)
    assert update.callback_query._answered is False
    assert update.callback_query._edited_texts == []


# ---------------------------------------------------------------------------
# cb_docker unit tests
# ---------------------------------------------------------------------------


def test_normalize_docker_page_clamp() -> None:
    page, total = cb_docker.normalize_docker_page(20, 999)
    assert page == total - 1


def test_log_page_payload_parse() -> None:
    result = cb_docker._parse_log_page_payload(
        "dlogs:page:mycontainer:10", "dlogs:page:"
    )
    assert result == ("mycontainer", 10, None)


def test_log_page_payload_with_since() -> None:
    result = cb_docker._parse_log_page_payload(
        "dlogs:page:container:0:1700000000", "dlogs:page:"
    )
    assert result == ("container", 0, 1700000000)


def test_log_page_payload_invalid() -> None:
    assert cb_docker._parse_log_page_payload("dlogs:page:", "dlogs:page:") is None


# ---------------------------------------------------------------------------
# cb_torrents unit tests
# ---------------------------------------------------------------------------


def test_paginate_torrents_empty() -> None:
    page_items, page, total = cb_torrents.paginate_torrents([], 0)
    assert page_items == []
    assert page == 0
    assert total == 1


def test_paginate_torrents_page_clamp() -> None:
    items = [{"name": f"t{i}", "hash": f"h{i}", "state": "done"} for i in range(15)]
    page_items, page, total = cb_torrents.paginate_torrents(items, 999)
    assert page == total - 1
    assert len(page_items) <= cb_torrents.TORRENT_PAGE_SIZE


# ---------------------------------------------------------------------------
# cb_media unit tests
# ---------------------------------------------------------------------------


def test_build_free_games_keyboard() -> None:
    kb = cb_media.build_free_games_keyboard()
    all_labels = [btn.text for row in kb.inline_keyboard for btn in row]
    assert "🎮 Epic" in all_labels
    assert "🎮 Steam" in all_labels
    assert "🎮 GOG" in all_labels
    assert "🎮 Humble" in all_labels


def test_build_protondb_keyboard_empty() -> None:
    kb = cb_media.build_protondb_keyboard("k", [])
    assert kb.inline_keyboard == ()


def test_build_tmdb_keyboard_nav() -> None:
    items = [
        {"id": 1, "title": "Movie A", "media_type": "movie"},
        {"id": 2, "title": "Show B", "media_type": "tv"},
    ]
    kb = cb_media.build_tmdb_keyboard("test", items, page=1, total_pages=3)
    nav_labels = [btn.text for btn in kb.inline_keyboard[-1]]
    assert "⬅️ Prev" not in nav_labels  # page 1 = first
    assert "Next ➡️" in nav_labels


# ---------------------------------------------------------------------------
# Backward-compat re-exports from callbacks
# ---------------------------------------------------------------------------


def test_reexports_accessible() -> None:
    """Ensure external modules can still import from callbacks directly."""
    assert hasattr(callbacks, "build_docker_keyboard")
    assert hasattr(callbacks, "build_torrent_keyboard")
    assert hasattr(callbacks, "build_tmdb_keyboard")
    assert hasattr(callbacks, "build_protondb_keyboard")
    assert hasattr(callbacks, "build_free_games_keyboard")
    assert hasattr(callbacks, "build_dlogs_selection_keyboard")
    assert hasattr(callbacks, "paginate_torrents")
    assert hasattr(callbacks, "normalize_docker_page")
    assert hasattr(callbacks, "DOCKER_PAGE_SIZE")
    assert hasattr(callbacks, "TORRENT_PAGE_SIZE")
    assert hasattr(callbacks, "LOG_PAGE_SIZE")
    assert hasattr(callbacks, "_render_logs_page")
    assert hasattr(callbacks, "_parse_log_page_payload")
