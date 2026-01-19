"""Tests for the torrent sources fallback module."""

from unittest.mock import MagicMock, patch

from tele_home_supervisor.torrentsources import (
    BitSearchSource,
    EZTVSource,
    TorrentResult,
    X1337Source,
    _build_browser_headers,
    _build_magnet,
    _get_random_user_agent,
    fallback_search,
    fallback_top,
    get_enabled_sources,
)

# Sample BitSearch HTML response
BITSEARCH_SAMPLE_HTML = """
<html>
<head><title>Search results for "ubuntu"</title></head>
<body>
<ul>
    <li class="card search-result">
        <a href="magnet:?xt=urn:btih:ABC123&amp;dn=%5BBitsearch.to%5D%20ubuntu-24.04-desktop-amd64.iso&amp;tr=udp%3A%2F%2Ftracker.opentrackr.org%3A1337%2Fannounce">
            Magnet Link
        </a>
        <div class="flex flex-wrap items-center gap-4 text-sm">
            <span class="inline-flex items-center space-x-1 text-green-600">
                <i class="fas fa-arrow-up"></i>
                <span class="font-medium">165</span>
                <span>seeders</span>
            </span>
            <span class="inline-flex items-center space-x-1 text-red-600">
                <i class="fas fa-arrow-down"></i>
                <span class="font-medium">10</span>
                <span>leechers</span>
            </span>
        </div>
    </li>
    <li class="card search-result">
        <a href="magnet:?xt=urn:btih:DEF456&amp;dn=%5BBitsearch.to%5D%20ubuntu-22.04-server.iso&amp;tr=udp%3A%2F%2Ftracker.opentrackr.org%3A1337%2Fannounce">
            Magnet Link
        </a>
        <div class="flex flex-wrap items-center gap-4 text-sm">
            <span class="inline-flex items-center space-x-1 text-green-600">
                <i class="fas fa-arrow-up"></i>
                <span class="font-medium">100</span>
                <span>seeders</span>
            </span>
            <span class="inline-flex items-center space-x-1 text-red-600">
                <i class="fas fa-arrow-down"></i>
                <span class="font-medium">5</span>
                <span>leechers</span>
            </span>
        </div>
    </li>
</ul>
</body>
</html>
"""

# Sample EZTV API response
EZTV_SAMPLE_RESPONSE = {
    "torrents_count": 2,
    "limit": 10,
    "page": 1,
    "torrents": [
        {
            "id": 1234567,
            "hash": "abc123def456",
            "filename": "Show.S01E01.720p.WEB.mkv",
            "magnet_url": "magnet:?xt=urn:btih:abc123def456&dn=Show.S01E01",
            "title": "Show S01E01 720p WEB",
            "seeds": 50,
            "peers": 10,
            "size_bytes": "1073741824",  # 1GB
        },
        {
            "id": 7654321,
            "hash": "xyz789abc012",
            "filename": "Show.S01E02.1080p.WEB.mkv",
            "magnet_url": "magnet:?xt=urn:btih:xyz789abc012&dn=Show.S01E02",
            "title": "Show S01E02 1080p WEB",
            "seeds": 75,
            "peers": 15,
            "size_bytes": "2147483648",  # 2GB
        },
    ],
}


class TestHelperFunctions:
    """Test helper utility functions."""

    def test_get_random_user_agent(self):
        ua = _get_random_user_agent()
        assert ua is not None
        assert "Mozilla" in ua

    def test_build_browser_headers(self):
        headers = _build_browser_headers()
        assert "User-Agent" in headers
        assert "Accept" in headers
        assert "Accept-Language" in headers

    def test_build_browser_headers_with_referer(self):
        headers = _build_browser_headers(referer="https://example.com")
        assert headers["Referer"] == "https://example.com"

    def test_build_magnet(self):
        magnet = _build_magnet("ABC123", "Test Torrent")
        assert magnet.startswith("magnet:?xt=urn:btih:ABC123")
        assert "dn=Test%20Torrent" in magnet
        assert "tr=" in magnet


class TestTorrentResult:
    """Test TorrentResult class."""

    def test_to_dict(self):
        result = TorrentResult(
            name="Test",
            magnet="magnet:?xt=...",
            seeders=100,
            leechers=10,
            source="TestSource",
            size="1.5 GB",
        )
        d = result.to_dict()
        assert d["name"] == "Test"
        assert d["magnet"] == "magnet:?xt=..."
        assert d["seeders"] == 100
        assert d["leechers"] == 10
        assert d["source"] == "TestSource"
        assert d["size"] == "1.5 GB"


class TestBitSearchSource:
    """Tests for BitSearch.to source."""

    def test_extract_name_from_magnet(self):
        source = BitSearchSource()
        magnet = "magnet:?xt=urn:btih:ABC&dn=%5BBitsearch.to%5D%20ubuntu-24.04.iso"
        name = source._extract_name_from_magnet(magnet)
        assert name == "ubuntu-24.04.iso"

    def test_extract_name_from_magnet_no_prefix(self):
        source = BitSearchSource()
        magnet = "magnet:?xt=urn:btih:ABC&dn=test-file.iso"
        name = source._extract_name_from_magnet(magnet)
        assert name == "test-file.iso"

    @patch.object(BitSearchSource, "_fetch")
    def test_search_success(self, mock_fetch):
        mock_fetch.return_value = BITSEARCH_SAMPLE_HTML
        source = BitSearchSource()
        results = source.search("ubuntu")

        assert len(results) == 2
        assert results[0].seeders >= results[1].seeders  # Sorted by seeders
        assert results[0].source == "BitSearch"

    @patch.object(BitSearchSource, "_fetch")
    def test_search_empty_query(self, mock_fetch):
        source = BitSearchSource()
        results = source.search("")
        assert results == []
        mock_fetch.assert_not_called()

    @patch.object(BitSearchSource, "_fetch")
    def test_search_exception(self, mock_fetch):
        mock_fetch.side_effect = Exception("Network error")
        source = BitSearchSource()
        debug_sink = MagicMock()
        results = source.search("ubuntu", debug_sink)

        assert results == []
        debug_sink.assert_called_once()


class TestEZTVSource:
    """Tests for EZTV.re source."""

    @patch.object(EZTVSource, "_fetch_json")
    def test_search_with_imdb_id(self, mock_fetch):
        mock_fetch.return_value = EZTV_SAMPLE_RESPONSE
        source = EZTVSource()
        results = source.search("tt0944947")

        assert len(results) == 2
        mock_fetch.assert_called_once()
        args, _ = mock_fetch.call_args
        assert "imdb_id=tt0944947" in args[0]

    def test_search_without_imdb_id(self):
        # EZTV doesn't support keyword search, so should return empty
        source = EZTVSource()
        results = source.search("game of thrones")
        assert results == []

    @patch.object(EZTVSource, "_fetch_json")
    def test_top(self, mock_fetch):
        mock_fetch.return_value = EZTV_SAMPLE_RESPONSE
        source = EZTVSource()
        results = source.top()

        assert len(results) == 2
        assert results[0].source == "EZTV"
        # Should be sorted by seeders
        assert results[0].seeders >= results[1].seeders

    @patch.object(EZTVSource, "_fetch_json")
    def test_parse_size(self, mock_fetch):
        mock_fetch.return_value = EZTV_SAMPLE_RESPONSE
        source = EZTVSource()
        results = source.top()

        # Check size parsing
        assert results[0].size is not None
        assert "GB" in results[0].size


class TestX1337Source:
    """Tests for 1337x.to source."""

    def test_disabled_by_default(self):
        source = X1337Source()
        assert source.enabled is False

    def test_search_when_disabled(self):
        source = X1337Source()
        results = source.search("test")
        assert results == []

    def test_top_when_disabled(self):
        source = X1337Source()
        results = source.top()
        assert results == []


class TestFallbackFunctions:
    """Tests for fallback search and top functions."""

    def test_get_enabled_sources(self):
        sources = get_enabled_sources()
        # Should include BitSearch and EZTV, but not 1337x (disabled)
        source_names = [s.name for s in sources]
        assert "BitSearch" in source_names
        assert "EZTV" in source_names
        assert "1337x" not in source_names

    @patch.object(BitSearchSource, "search")
    def test_fallback_search_first_source_succeeds(self, mock_search):
        mock_results = [
            TorrentResult(
                name="Test",
                magnet="magnet:?...",
                seeders=100,
                leechers=10,
                source="BitSearch",
            )
        ]
        mock_search.return_value = mock_results

        results = fallback_search("test query")
        assert len(results) == 1
        assert results[0].name == "Test"

    @patch.object(BitSearchSource, "search")
    @patch.object(EZTVSource, "search")
    def test_fallback_search_first_fails_second_succeeds(
        self, mock_eztv_search, mock_bitsearch_search
    ):
        mock_bitsearch_search.return_value = []
        mock_eztv_search.return_value = [
            TorrentResult(
                name="EZTV Result",
                magnet="magnet:?...",
                seeders=50,
                leechers=5,
                source="EZTV",
            )
        ]

        results = fallback_search("tt0944947")  # IMDB ID
        assert len(results) == 1
        assert results[0].source == "EZTV"

    @patch.object(BitSearchSource, "search")
    @patch.object(EZTVSource, "search")
    def test_fallback_search_all_fail(self, mock_eztv_search, mock_bitsearch_search):
        mock_bitsearch_search.return_value = []
        mock_eztv_search.return_value = []

        results = fallback_search("nonexistent query")
        assert results == []

    @patch.object(BitSearchSource, "top")
    def test_fallback_top(self, mock_top):
        mock_results = [
            TorrentResult(
                name="Top Result",
                magnet="magnet:?...",
                seeders=500,
                leechers=50,
                source="BitSearch",
            )
        ]
        mock_top.return_value = mock_results

        results = fallback_top()
        assert len(results) == 1
        assert results[0].name == "Top Result"

    @patch.object(BitSearchSource, "top")
    def test_fallback_top_with_category(self, mock_top):
        mock_results = [
            TorrentResult(
                name="Movie Result",
                magnet="magnet:?...",
                seeders=200,
                leechers=20,
                source="BitSearch",
            )
        ]
        mock_top.return_value = mock_results

        results = fallback_top("movies")
        assert len(results) == 1
        mock_top.assert_called_with("movies", None)
