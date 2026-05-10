from unittest.mock import AsyncMock, MagicMock

import pytest

from tele_home_supervisor import tmdb


def test_tmdb_extract_items_filters_and_limits() -> None:
    data = {
        "results": [
            {
                "id": 1,
                "title": "Example Movie",
                "media_type": "movie",
                "release_date": "2024-01-01",
                "vote_average": 7.2,
            },
            {
                "id": 2,
                "name": "Example Show",
                "media_type": "tv",
                "first_air_date": "2023-05-10",
                "vote_average": 8.1,
            },
            {"id": 3, "media_type": "person", "name": "Ignore"},
        ]
    }
    items = tmdb.extract_items(data)
    assert len(items) == 2
    assert items[0]["title"] == "Example Movie"
    assert items[0]["year"] == "2024"
    assert items[1]["title"] == "Example Show"
    assert items[1]["year"] == "2023"


@pytest.mark.asyncio
async def test_tmdb_fetch_raises_on_http_error(monkeypatch) -> None:
    monkeypatch.setattr(tmdb.config.settings, "TMDB_API_KEY", "test-key")

    response = MagicMock()
    response.status_code = 403
    response.is_success = False
    response.text = "nope"
    client = MagicMock()
    client.get = AsyncMock(return_value=response)

    monkeypatch.setattr(tmdb, "_get_client", lambda: client)

    try:
        await tmdb.trending_movies()
    except RuntimeError as exc:
        assert "TMDB HTTP 403" in str(exc)
    else:
        raise AssertionError("Expected TMDB error")
