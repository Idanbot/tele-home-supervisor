from tele_home_supervisor.handlers.cb_media import _parse_tmdb_page_payload


class TestParseTmdbPagePayload:
    def test_valid_payload(self) -> None:
        result = _parse_tmdb_page_payload("tmdbpage:abc123:2")
        assert result == ("abc123", 2)

    def test_page_one(self) -> None:
        result = _parse_tmdb_page_payload("tmdbpage:key:1")
        assert result == ("key", 1)

    def test_page_clamped_to_one(self) -> None:
        result = _parse_tmdb_page_payload("tmdbpage:key:0")
        assert result == ("key", 1)

    def test_negative_page_clamped(self) -> None:
        result = _parse_tmdb_page_payload("tmdbpage:key:-1")
        assert result == ("key", 1)

    def test_invalid_page_not_int(self) -> None:
        result = _parse_tmdb_page_payload("tmdbpage:key:abc")
        assert result is None

    def test_too_few_parts(self) -> None:
        result = _parse_tmdb_page_payload("tmdbpage:key")
        assert result is None

    def test_too_many_parts(self) -> None:
        result = _parse_tmdb_page_payload("tmdbpage:key:2:extra")
        assert result is None
