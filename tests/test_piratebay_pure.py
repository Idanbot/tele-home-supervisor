from tele_home_supervisor import piratebay


class TestCategoryHelp:
    def test_returns_string(self) -> None:
        result = piratebay.category_help()
        assert isinstance(result, str)
        assert "audio" in result
        assert "games" in result


class TestResolveCategory:
    def test_known_aliases(self) -> None:
        assert piratebay.resolve_category("audio") == 101
        assert piratebay.resolve_category("music") == 101
        assert piratebay.resolve_category("movies") == 200
        assert piratebay.resolve_category("hdmovies") == 207
        assert piratebay.resolve_category("games") == 400
        assert piratebay.resolve_category("ebook") == 601

    def test_numeric_string(self) -> None:
        assert piratebay.resolve_category("200") == 200
        assert piratebay.resolve_category("101") == 101

    def test_unknown_returns_none(self) -> None:
        assert piratebay.resolve_category("unknown") is None

    def test_none_returns_none(self) -> None:
        assert piratebay.resolve_category(None) is None

    def test_empty_returns_none(self) -> None:
        assert piratebay.resolve_category("") is None
        assert piratebay.resolve_category("   ") is None

    def test_case_insensitive(self) -> None:
        assert piratebay.resolve_category("AUDIO") == 101
        assert piratebay.resolve_category("Games") == 400


class TestResolveTopMode:
    def test_default_top(self) -> None:
        assert piratebay.resolve_top_mode("top") == "top100"

    def test_top100(self) -> None:
        assert piratebay.resolve_top_mode("top100") == "top100"

    def test_48h_variants(self) -> None:
        assert piratebay.resolve_top_mode("top48") == "top48h"
        assert piratebay.resolve_top_mode("48h") == "top48h"
        assert piratebay.resolve_top_mode("top48h") == "top48h"

    def test_none_defaults_to_top100(self) -> None:
        assert piratebay.resolve_top_mode(None) == "top100"

    def test_empty_defaults_to_top100(self) -> None:
        assert piratebay.resolve_top_mode("") == "top100"
        assert piratebay.resolve_top_mode("   ") == "top100"

    def test_unknown_returns_none(self) -> None:
        assert piratebay.resolve_top_mode("unknown") is None


class TestEnsureNotBlocked:
    def test_clean_html_passes(self) -> None:
        piratebay._ensure_not_blocked("<html><body>Normal page</body></html>")

    def test_cloudflare_blocked(self) -> None:
        import pytest

        with pytest.raises(RuntimeError, match="blocked"):
            piratebay._ensure_not_blocked("Please complete the Cloudflare captcha")

    def test_attention_required(self) -> None:
        import pytest

        with pytest.raises(RuntimeError, match="blocked"):
            piratebay._ensure_not_blocked("Attention Required! Access Denied")

    def test_access_denied(self) -> None:
        import pytest

        with pytest.raises(RuntimeError, match="blocked"):
            piratebay._ensure_not_blocked("Access denied to this resource")


class TestIsNoResults:
    def test_no_results_text(self) -> None:
        assert piratebay._is_no_results("No results returned for your query") is True

    def test_no_matches_text(self) -> None:
        assert piratebay._is_no_results("No matches found") is True

    def test_results_present(self) -> None:
        assert piratebay._is_no_results("<tr><td>Some result</td></tr>") is False


class TestTopN:
    def test_sorts_by_seeders(self) -> None:
        results = [
            {"name": "A", "seeders": 50, "leechers": 5},
            {"name": "B", "seeders": 200, "leechers": 20},
            {"name": "C", "seeders": 100, "leechers": 10},
        ]
        top = piratebay._top_n(results, n=2)
        assert len(top) == 2
        assert top[0]["name"] == "B"
        assert top[1]["name"] == "C"

    def test_default_n_is_10(self) -> None:
        results = [{"name": f"R{i}", "seeders": i} for i in range(20)]
        top = piratebay._top_n(results)
        assert len(top) == 10

    def test_fewer_than_n(self) -> None:
        results = [{"name": "A", "seeders": 10}]
        top = piratebay._top_n(results, n=5)
        assert len(top) == 1

    def test_missing_seeders_defaults_to_zero(self) -> None:
        results = [{"name": "A"}, {"name": "B", "seeders": 5}]
        top = piratebay._top_n(results, n=10)
        assert top[0]["name"] == "B"


class TestMagnetFromHash:
    def test_basic_magnet(self) -> None:
        magnet = piratebay._magnet_from_hash("abc123", "Test File")
        assert magnet.startswith("magnet:?xt=urn:btih:abc123")
        assert "dn=Test%20File" in magnet
        assert "&tr=" in magnet

    def test_special_characters_encoded(self) -> None:
        magnet = piratebay._magnet_from_hash("hash", "Hello & World")
        assert "Hello%20%26%20World" in magnet


class TestApiToResults:
    def test_valid_items(self) -> None:
        items = [
            {"name": "Movie", "info_hash": "abc123", "seeders": 100, "leechers": 10},
            {"name": "Show", "info_hash": "def456", "seeders": 50, "leechers": 5},
        ]
        results = piratebay._api_to_results(items)
        assert len(results) == 2
        assert results[0]["name"] == "Movie"
        assert results[0]["seeders"] == 100
        assert results[0]["magnet"].startswith("magnet:?xt=urn:btih:abc123")

    def test_skips_non_dict(self) -> None:
        items = [
            "not a dict",
            42,
            {"name": "OK", "info_hash": "h", "seeders": 1, "leechers": 0},
        ]
        results = piratebay._api_to_results(items)
        assert len(results) == 1
        assert results[0]["name"] == "OK"

    def test_skips_empty_name(self) -> None:
        items = [
            {"name": "", "info_hash": "abc", "seeders": 1, "leechers": 0},
            {"name": "Valid", "info_hash": "def", "seeders": 1, "leechers": 0},
        ]
        results = piratebay._api_to_results(items)
        assert len(results) == 1
        assert results[0]["name"] == "Valid"

    def test_skips_empty_hash(self) -> None:
        items = [
            {"name": "NoHash", "info_hash": "", "seeders": 1, "leechers": 0},
        ]
        results = piratebay._api_to_results(items)
        assert len(results) == 0
