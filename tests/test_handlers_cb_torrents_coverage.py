from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tele_home_supervisor.handlers import cb_torrents


@pytest.mark.asyncio
async def test_handle_torrent_stop():
    mock_query = AsyncMock()
    mock_context = MagicMock()
    mock_context.application = MagicMock()

    with (
        patch(
            "tele_home_supervisor.handlers.cb_torrents._validate_torrent_hash",
            return_value=True,
        ),
        patch(
            "tele_home_supervisor.handlers.cb_torrents.services.torrent_stop_by_hash",
            return_value="success",
        ),
    ):
        await cb_torrents.handle_torrent_stop(mock_query, mock_context, "hash123")
        mock_query.message.reply_text.assert_called_once()

    mock_query = AsyncMock()
    with patch(
        "tele_home_supervisor.handlers.cb_torrents._validate_torrent_hash",
        return_value=False,
    ):
        await cb_torrents.handle_torrent_stop(mock_query, mock_context, "hash123")
        mock_query.message.reply_text.assert_called_with("❌ Unknown torrent.")


@pytest.mark.asyncio
async def test_handle_torrent_start():
    mock_query = AsyncMock()
    mock_context = MagicMock()
    mock_context.application = MagicMock()

    with (
        patch(
            "tele_home_supervisor.handlers.cb_torrents._validate_torrent_hash",
            return_value=True,
        ),
        patch(
            "tele_home_supervisor.handlers.cb_torrents.services.torrent_start_by_hash",
            return_value="success",
        ),
    ):
        await cb_torrents.handle_torrent_start(mock_query, mock_context, "hash123")
        mock_query.message.reply_text.assert_called_once()


@pytest.mark.asyncio
async def test_handle_torrent_info():
    mock_query = AsyncMock()
    mock_context = MagicMock()
    mock_context.application = MagicMock()

    with (
        patch(
            "tele_home_supervisor.handlers.cb_torrents._validate_torrent_hash",
            return_value=True,
        ),
        patch(
            "tele_home_supervisor.handlers.cb_torrents.services.torrent_info_by_hash",
            return_value="success",
        ),
    ):
        await cb_torrents.handle_torrent_info(mock_query, mock_context, "hash123")
        mock_query.message.reply_text.assert_called_once()


@pytest.mark.asyncio
async def test_handle_torrent_delete():
    mock_query = AsyncMock()
    mock_context = MagicMock()
    mock_context.application = MagicMock()

    with (
        patch(
            "tele_home_supervisor.handlers.cb_torrents._validate_torrent_hash",
            return_value=True,
        ),
        patch(
            "tele_home_supervisor.handlers.cb_torrents.services.torrent_delete_by_hash",
            return_value="success",
        ),
    ):
        await cb_torrents.handle_torrent_delete(mock_query, mock_context, "hash123")
        mock_query.message.reply_text.assert_called_once()


@pytest.mark.asyncio
async def test_validate_torrent_hash():
    mock_context = MagicMock()
    mock_state = AsyncMock()

    with (
        patch(
            "tele_home_supervisor.handlers.cb_torrents.get_state",
            return_value=mock_state,
        ),
        patch(
            "tele_home_supervisor.handlers.cb_torrents.services.get_torrent_list",
            return_value=[{"hash": "hash12345"}],
        ),
    ):
        res = await cb_torrents._validate_torrent_hash(mock_context, "hash123")
        assert res is True

        res = await cb_torrents._validate_torrent_hash(mock_context, "hash999")
        assert res is False


def test_build_torrent_keyboard():
    torrents = [
        {"name": "Torrent 1", "hash": "123456", "state": "downloading"},
        {"name": "Torrent 2", "hash": "654321", "state": "paused"},
    ]
    markup = cb_torrents.build_torrent_keyboard(torrents, 0)
    assert markup
    assert len(markup.inline_keyboard) > 0


@pytest.mark.asyncio
async def test_torrent_refresh_page():
    mock_query = AsyncMock()
    mock_context = MagicMock()
    mock_state = AsyncMock()
    torrents = [
        {
            "name": "Torrent 1",
            "hash": "123456",
            "state": "paused",
            "progress": 50.0,
            "dlspeed": 0.0,
        }
    ]

    with (
        patch(
            "tele_home_supervisor.handlers.cb_torrents.get_state",
            return_value=mock_state,
        ),
        patch(
            "tele_home_supervisor.handlers.cb_torrents.services.get_torrent_list",
            return_value=torrents,
        ),
        patch(
            "tele_home_supervisor.handlers.cb_torrents.safe_edit_message_text"
        ) as mock_edit,
    ):
        await cb_torrents.handle_torrent_refresh(mock_query, mock_context, 0)
        mock_state.refresh_torrents.assert_called_once()
        mock_edit.assert_called_once()

        mock_edit.reset_mock()
        await cb_torrents.handle_torrent_page(mock_query, mock_context, 0)
        mock_state.maybe_refresh.assert_called_with("torrents")
        mock_edit.assert_called_once()
