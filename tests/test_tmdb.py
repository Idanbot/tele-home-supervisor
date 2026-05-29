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


def test_tmdb_extract_items_empty_results() -> None:
    items = tmdb.extract_items({"results": []})
    assert items == []


def test_tmdb_extract_items_missing_results_key() -> None:
    items = tmdb.extract_items({})
    assert items == []


def test_tmdb_extract_items_filters_no_title() -> None:
    data = {
        "results": [
            {"id": 1, "media_type": "movie"},
        ]
    }
    items = tmdb.extract_items(data)
    assert len(items) == 0


def test_tmdb_extract_items_default_type() -> None:
    data = {
        "results": [
            {"id": 1, "title": "A Movie", "vote_average": 5.0},
        ]
    }
    items = tmdb.extract_items(data, default_type="movie")
    assert len(items) == 1
    assert items[0]["media_type"] == "movie"


def test_tmdb_extract_items_skips_non_dict() -> None:
    data = {"results": ["not_a_dict", 42, None]}
    items = tmdb.extract_items(data)
    assert items == []


def test_tmdb_extract_items_limits_to_10() -> None:
    data = {
        "results": [
            {
                "id": i,
                "title": f"Movie {i}",
                "media_type": "movie",
                "release_date": "2024",
            }
            for i in range(15)
        ]
    }
    items = tmdb.extract_items(data)
    assert len(items) == 10


def test_tmdb_ensure_api_key_raises() -> None:
    import os

    original = os.environ.get("TMDB_API_KEY")
    if "TMDB_API_KEY" in os.environ:
        del os.environ["TMDB_API_KEY"]
    tmdb.config.settings.TMDB_API_KEY = ""
    with pytest.raises(RuntimeError, match="TMDB_API_KEY"):
        tmdb._ensure_api_key()
    if original is not None:
        os.environ["TMDB_API_KEY"] = original
