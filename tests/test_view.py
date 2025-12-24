"""Tests for view module."""

from tele_home_supervisor import view


def test_render_protondb_list_empty() -> None:
    result = view.render_protondb_list("Test", [])
    assert "No games found" in result


def test_render_protondb_list_with_games() -> None:
    games = [
        {"name": "Elden Ring", "appid": "1245620"},
        {"name": "Cyberpunk 2077", "appid": "1091500"},
    ]
    result = view.render_protondb_list("ProtonDB Search: elden", games)
    assert "ProtonDB Search: elden" in result
    assert "1. Elden Ring" in result
    assert "2. Cyberpunk 2077" in result


def test_render_tmdb_list_empty() -> None:
    result = view.render_tmdb_list("Test", [])
    assert "No results found" in result


def test_render_tmdb_list_with_items() -> None:
    items = [
        {"title": "Movie 1", "year": "2024", "rating": 7.5},
        {"title": "Movie 2", "year": "2023", "rating": 8.2},
    ]
    result = view.render_tmdb_list("Trending Movies", items)
    assert "Trending Movies" in result
    assert "Movie 1" in result
    assert "(2024)" in result
    assert "7.5" in result


def test_chunk_small_message() -> None:
    msg = "short message"
    chunks = view.chunk(msg, size=100)
    assert chunks == [msg]


def test_chunk_large_message() -> None:
    msg = "line1\nline2\nline3\nline4"
    chunks = view.chunk(msg, size=12)
    assert len(chunks) >= 2
    # All content should be preserved
    assert "".join(chunks).replace("\n", "") == msg.replace("\n", "")
