"""Tests for scheduled fetchers."""

from unittest.mock import patch, MagicMock

from tele_home_supervisor import scheduled


class TestFetchHackernewsTop:
    """Tests for fetch_hackernews_top function."""

    def test_returns_formatted_html(self) -> None:
        mock_stories = [
            {
                "id": 1,
                "title": "Story 1",
                "url": "https://example.com/1",
                "score": 100,
                "descendants": 50,
            },
            {
                "id": 2,
                "title": "Story 2",
                "url": "https://example.com/2",
                "score": 80,
                "descendants": 30,
            },
        ]

        with patch("tele_home_supervisor.scheduled.requests") as mock_req:
            # Mock the top stories endpoint
            top_resp = MagicMock()
            top_resp.json.return_value = [1, 2, 3]
            top_resp.ok = True

            # Mock individual story fetches
            def get_side_effect(url, **kwargs):
                if "topstories" in url:
                    return top_resp
                for story in mock_stories:
                    if str(story["id"]) in url:
                        resp = MagicMock()
                        resp.json.return_value = story
                        resp.ok = True
                        return resp
                return MagicMock(ok=False)

            mock_req.get.side_effect = get_side_effect

            result = scheduled.fetch_hackernews_top(limit=2)

            assert "Hacker News" in result or "HN" in result
            assert "Story 1" in result

    def test_handles_api_error(self) -> None:
        import requests as real_requests

        with patch("tele_home_supervisor.scheduled.requests.get") as mock_get:
            mock_get.side_effect = real_requests.RequestException("Network error")

            result = scheduled.fetch_hackernews_top(limit=3)

            assert "❌" in result or "error" in result.lower()


class TestFetchEpicFreeGames:
    """Tests for fetch_epic_free_games function."""

    def test_returns_tuple(self) -> None:
        with patch("tele_home_supervisor.scheduled._cached_fetch") as mock_cache:
            mock_cache.return_value = ("<b>Epic Games:</b>\nNo games", [])

            result = scheduled.fetch_epic_free_games()

            assert isinstance(result, tuple)
            assert len(result) == 2


class TestFetchSteamFreeGames:
    """Tests for fetch_steam_free_games function."""

    def test_returns_tuple(self) -> None:
        with patch("tele_home_supervisor.scheduled._cached_fetch") as mock_cache:
            mock_cache.return_value = ("<b>Steam Free:</b>\nNo games", [])

            result = scheduled.fetch_steam_free_games(limit=5)

            assert isinstance(result, tuple)


class TestFetchGogFreeGames:
    """Tests for fetch_gog_free_games function."""

    def test_returns_tuple(self) -> None:
        with patch("tele_home_supervisor.scheduled._cached_fetch") as mock_cache:
            mock_cache.return_value = ("<b>GOG Free:</b>\nNo games", [])

            result = scheduled.fetch_gog_free_games()

            assert isinstance(result, tuple)


class TestFetchHumbleFreeGames:
    """Tests for fetch_humble_free_games function."""

    def test_returns_tuple(self) -> None:
        with patch("tele_home_supervisor.scheduled._cached_fetch") as mock_cache:
            mock_cache.return_value = ("<b>Humble Free:</b>\nNo games", [])

            result = scheduled.fetch_humble_free_games()

            assert isinstance(result, tuple)


class TestBuildCombinedGameOffers:
    """Tests for build_combined_game_offers function."""

    def test_combines_all_sources(self) -> None:
        with (
            patch.object(
                scheduled,
                "fetch_epic_free_games",
                return_value=("Epic: Game1", ["url1"]),
            ),
            patch.object(
                scheduled,
                "fetch_steam_free_games",
                return_value=("Steam: Game2", ["url2"]),
            ),
            patch.object(
                scheduled, "fetch_gog_free_games", return_value=("GOG: Game3", ["url3"])
            ),
            patch.object(
                scheduled,
                "fetch_humble_free_games",
                return_value=("Humble: Game4", ["url4"]),
            ),
        ):
            result, error = scheduled.build_combined_game_offers()

            assert "Epic" in result or "Steam" in result


class TestCachedFetch:
    """Tests for _cached_fetch internal function."""

    def test_caches_result(self) -> None:
        call_count = 0

        def fetcher():
            nonlocal call_count
            call_count += 1
            return f"result-{call_count}"

        # Clear any existing cache
        with scheduled._cache_lock:
            scheduled._cache.clear()

        result1 = scheduled._cached_fetch("test_key", ttl_s=3600, fetcher=fetcher)
        result2 = scheduled._cached_fetch("test_key", ttl_s=3600, fetcher=fetcher)

        assert result1 == result2
        assert call_count == 1  # Only called once due to caching


class TestIsErrorValue:
    """Tests for _is_error_value helper."""

    def test_detects_error_string(self) -> None:
        assert scheduled._is_error_value("❌ Something went wrong") is True
        assert scheduled._is_error_value("Normal message") is False

    def test_detects_error_tuple(self) -> None:
        assert scheduled._is_error_value(("❌ Error", [])) is True
        assert scheduled._is_error_value(("Normal", ["data"])) is False
