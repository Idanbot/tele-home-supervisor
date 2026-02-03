"""Tests for media handlers (TMDB, ProtonDB)."""

import pytest
from unittest.mock import AsyncMock, patch

from tele_home_supervisor import config
from tele_home_supervisor.handlers import media

from conftest import DummyContext, DummyUpdate


class TestTmdbHandlers:
    """Tests for TMDB command handlers."""

    @pytest.mark.asyncio
    async def test_cmd_movies_fetches_trending(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "ALLOWED", {123})
        monkeypatch.setattr(config, "BOT_AUTH_TOTP_SECRET", None)

        mock_data = {
            "results": [
                {
                    "title": "Movie 1",
                    "id": 1,
                    "media_type": "movie",
                    "vote_average": 7.5,
                },
                {
                    "title": "Movie 2",
                    "id": 2,
                    "media_type": "movie",
                    "vote_average": 8.0,
                },
            ],
            "total_pages": 1,
        }

        with patch(
            "tele_home_supervisor.services.tmdb_trending_movies", new_callable=AsyncMock
        ) as mock_tmdb:
            mock_tmdb.return_value = mock_data
            update = DummyUpdate(chat_id=123, user_id=123)
            context = DummyContext()

            await media.cmd_movies(update, context)

            mock_tmdb.assert_called_once()
            assert len(update.message.replies) == 1
            assert "Movie" in update.message.replies[0]

    @pytest.mark.asyncio
    async def test_cmd_shows_fetches_trending(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "ALLOWED", {123})
        monkeypatch.setattr(config, "BOT_AUTH_TOTP_SECRET", None)

        mock_data = {
            "results": [
                {"name": "Show 1", "id": 1, "media_type": "tv", "vote_average": 8.5},
            ],
            "total_pages": 1,
        }

        with patch(
            "tele_home_supervisor.services.tmdb_trending_shows", new_callable=AsyncMock
        ) as mock_tmdb:
            mock_tmdb.return_value = mock_data
            update = DummyUpdate(chat_id=123, user_id=123)
            context = DummyContext()

            await media.cmd_shows(update, context)

            mock_tmdb.assert_called_once()

    @pytest.mark.asyncio
    async def test_cmd_tmdb_requires_query(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "ALLOWED", {123})
        monkeypatch.setattr(config, "BOT_AUTH_TOTP_SECRET", None)

        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext(args=[])

        await media.cmd_tmdb(update, context)

        assert "Usage" in update.message.replies[0]

    @pytest.mark.asyncio
    async def test_cmd_tmdb_searches(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "ALLOWED", {123})
        monkeypatch.setattr(config, "BOT_AUTH_TOTP_SECRET", None)

        mock_data = {
            "results": [
                {
                    "title": "The Matrix",
                    "id": 603,
                    "media_type": "movie",
                    "vote_average": 8.7,
                },
            ],
            "total_pages": 1,
        }

        with patch(
            "tele_home_supervisor.services.tmdb_search_multi", new_callable=AsyncMock
        ) as mock_search:
            mock_search.return_value = mock_data
            update = DummyUpdate(chat_id=123, user_id=123)
            context = DummyContext(args=["matrix"])

            await media.cmd_tmdb(update, context)

            mock_search.assert_called_once()

    @pytest.mark.asyncio
    async def test_cmd_incinema_fetches(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "ALLOWED", {123})
        monkeypatch.setattr(config, "BOT_AUTH_TOTP_SECRET", None)

        mock_data = {
            "results": [
                {
                    "title": "New Movie",
                    "id": 1,
                    "media_type": "movie",
                    "vote_average": 7.0,
                },
            ],
            "total_pages": 1,
        }

        with patch(
            "tele_home_supervisor.services.tmdb_in_cinema", new_callable=AsyncMock
        ) as mock_tmdb:
            mock_tmdb.return_value = mock_data
            update = DummyUpdate(chat_id=123, user_id=123)
            context = DummyContext()

            await media.cmd_incinema(update, context)

            mock_tmdb.assert_called_once()


class TestProtonDbHandlers:
    """Tests for ProtonDB command handlers."""

    @pytest.mark.asyncio
    async def test_cmd_protondb_requires_query(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "ALLOWED", {123})
        monkeypatch.setattr(config, "BOT_AUTH_TOTP_SECRET", None)

        update = DummyUpdate(chat_id=123, user_id=123)
        context = DummyContext(args=[])

        await media.cmd_protondb(update, context)

        assert "Usage" in update.message.replies[0]

    @pytest.mark.asyncio
    async def test_cmd_protondb_searches(self, monkeypatch) -> None:
        monkeypatch.setattr(config, "ALLOWED", {123})
        monkeypatch.setattr(config, "BOT_AUTH_TOTP_SECRET", None)

        mock_games = [
            {"name": "Elden Ring", "appid": "1245620"},
            {"name": "Dark Souls", "appid": "570940"},
        ]

        with patch(
            "tele_home_supervisor.services.protondb_search", new_callable=AsyncMock
        ) as mock_search:
            mock_search.return_value = mock_games
            update = DummyUpdate(chat_id=123, user_id=123)
            context = DummyContext(args=["elden"])

            await media.cmd_protondb(update, context)

            mock_search.assert_called_once()
