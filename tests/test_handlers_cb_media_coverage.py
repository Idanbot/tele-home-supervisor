import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tele_home_supervisor.handlers import cb_media
from tele_home_supervisor.models.magnet import MagnetEntry
from tele_home_supervisor.models.tmdb_cache import TmdbCacheEntry


@pytest.mark.asyncio
async def test_handle_tmdb_page():
    mock_query = AsyncMock()
    mock_context = MagicMock()

    entry = TmdbCacheEntry(
        updated_at=time.monotonic(),
        kind="movies",
        query=None,
        page=1,
        total_pages=1,
        items=[{"id": 1, "title": "Movie", "media_type": "movie"}],
    )
    mock_state = MagicMock()
    mock_state.get_tmdb_results = MagicMock(return_value=entry)

    with (
        patch(
            "tele_home_supervisor.handlers.cb_media.get_state", return_value=mock_state
        ),
        patch(
            "tele_home_supervisor.handlers.cb_media.services.tmdb_trending_movies",
            return_value={"results": [], "total_pages": 1},
        ),
        patch(
            "tele_home_supervisor.handlers.cb_media.tmdb.extract_items",
            return_value=entry.items,
        ),
        patch(
            "tele_home_supervisor.handlers.cb_media.safe_edit_message_text"
        ) as mock_edit,
    ):
        await cb_media.handle_tmdb_page(mock_query, mock_context, "tmdbpage:key123:1")
        mock_edit.assert_called_once()


@pytest.mark.asyncio
async def test_handle_tmdb_info():
    mock_query = AsyncMock()
    mock_context = MagicMock()

    with patch(
        "tele_home_supervisor.handlers.cb_media.services.tmdb_movie_details",
        return_value={
            "title": "Details",
            "overview": "Some desc",
            "genres": [],
            "poster_path": None,
        },
    ):
        await cb_media.handle_tmdb_info(mock_query, mock_context, "tmdbinfo:movie:123")
        mock_query.message.reply_text.assert_called_once()


@pytest.mark.asyncio
async def test_handle_protondb_info():
    mock_query = AsyncMock()
    mock_context = MagicMock()

    mock_state = MagicMock()
    games = [{"appid": "123", "name": "Game"}]
    mock_state.get_protondb_results = MagicMock(return_value=games)

    with (
        patch(
            "tele_home_supervisor.handlers.cb_media.get_state", return_value=mock_state
        ),
        patch(
            "tele_home_supervisor.handlers.cb_media.services.protondb_summary",
            return_value={
                "tier": "gold",
                "trendingTier": "gold",
                "confidence": "good",
                "total": 100,
                "score": 1.0,
            },
        ),
        patch(
            "tele_home_supervisor.handlers.cb_media.services.steam_app_details",
            return_value={"header_image": None},
        ),
        patch(
            "tele_home_supervisor.handlers.cb_media.services.steam_player_count",
            return_value=500,
        ),
    ):
        await cb_media.handle_protondb_info(
            mock_query, mock_context, "protondbinfo:key:0"
        )
        mock_query.message.reply_text.assert_called_once()


@pytest.mark.asyncio
async def test_handle_games_callback():
    mock_query = AsyncMock()
    mock_context = MagicMock()

    with (
        patch(
            "tele_home_supervisor.scheduled.fetch_epic_free_games",
            new_callable=AsyncMock,
            return_value=("Epic Games", []),
        ) as mock_fetch,
        patch(
            "tele_home_supervisor.handlers.cb_media.get_state", return_value=MagicMock()
        ),
    ):
        await cb_media.handle_games_callback(mock_query, mock_context, "epic")
        mock_fetch.assert_called_once()


@pytest.mark.asyncio
async def test_handle_piratebay_select():
    mock_query = AsyncMock()
    mock_context = MagicMock()

    magnet_entry = MagnetEntry(
        name="Torrent 1", magnet="magnet:?", seeders=100, leechers=50
    )
    mock_state = MagicMock()
    mock_state.get_magnet = MagicMock(return_value=magnet_entry)

    with patch(
        "tele_home_supervisor.handlers.cb_media.get_state", return_value=mock_state
    ):
        await cb_media.handle_piratebay_select(mock_query, mock_context, "key:0")
        mock_query.message.reply_text.assert_called_once()


@pytest.mark.asyncio
async def test_handle_piratebay_add():
    mock_query = AsyncMock()
    mock_context = MagicMock()

    magnet_entry = MagnetEntry(
        name="Torrent 1", magnet="magnet:?", seeders=100, leechers=50
    )
    mock_state = MagicMock()
    mock_state.get_magnet = MagicMock(return_value=magnet_entry)
    mock_state.torrent_completion_enabled = MagicMock(return_value=False)

    with (
        patch(
            "tele_home_supervisor.handlers.cb_media.get_state", return_value=mock_state
        ),
        patch(
            "tele_home_supervisor.handlers.cb_media.services.torrent_add",
            return_value="success",
        ),
    ):
        await cb_media.handle_piratebay_add(mock_query, mock_context, "key:0")
        mock_query.message.reply_text.assert_called_once()


@pytest.mark.asyncio
async def test_handle_piratebay_magnet():
    mock_query = AsyncMock()
    mock_context = MagicMock()

    magnet_entry = MagnetEntry(
        name="Torrent 1", magnet="magnet:?", seeders=100, leechers=50
    )
    mock_state = MagicMock()
    mock_state.get_magnet = MagicMock(return_value=magnet_entry)

    with patch(
        "tele_home_supervisor.handlers.cb_media.get_state", return_value=mock_state
    ):
        await cb_media.handle_piratebay_magnet(mock_query, mock_context, "key:0")
        mock_query.message.reply_text.assert_called_once()
