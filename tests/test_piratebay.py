from unittest.mock import MagicMock, patch


from tele_home_supervisor import piratebay

SAMPLE_HTML = """
<tr class="header"><th>Type</th><th>Name</th><th>SE</th><th>LE</th></tr>
<tr>
    <td class="vertTh"><center><a href="/browse/201" title="More from this category">Video</a><br />(<a href="/browse/201" title="More from this category">Movies</a>)</center></td>
    <td>
        <div class="detName"><a href="/torrent/12345/Some.Movie.2024.1080p" class="detLink" title="Details for Some Movie">Some Movie 2024 1080p</a></div>
        <a href="magnet:?xt=urn:btih:hash123&dn=Some.Movie&tr=udp://tracker.openbittorrent.com:80" title="Download this torrent using magnet"><img src="..." /></a>
    </td>
    <td align="right">1500</td>
    <td align="right">50</td>
</tr>
<tr>
    <td class="vertTh">...</td>
    <td>
        <div class="detName"><a href="/torrent/67890/Another.Thing" class="detLink">Another Thing</a></div>
        <a href="magnet:?xt=urn:btih:hash456&dn=Another.Thing" title="Download magnet"></a>
    </td>
    <td align="right">100</td>
    <td align="right">20</td>
</tr>
"""


def test_resolve_category():
    assert piratebay.resolve_category("video") == 200
    assert piratebay.resolve_category("movies") == 200
    assert piratebay.resolve_category("200") == 200
    assert piratebay.resolve_category("unknown") is None
    assert piratebay.resolve_category(None) is None


def test_parse_rows():
    results = piratebay._parse_rows(SAMPLE_HTML)
    assert len(results) == 2

    item1 = results[0]
    assert item1["name"] == "Some Movie 2024 1080p"
    assert item1["seeders"] == 1500
    assert item1["leechers"] == 50
    assert item1["magnet"].startswith("magnet:?xt=urn:btih:hash123")

    item2 = results[1]
    assert item2["name"] == "Another Thing"
    assert item2["seeders"] == 100
    assert item2["leechers"] == 20
    assert item2["magnet"].startswith("magnet:?xt=urn:btih:hash456")


@patch("tele_home_supervisor.piratebay.requests.get")
def test_search_html_fallback(mock_get):
    # Mock HTML response
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.text = SAMPLE_HTML
    mock_get.return_value = mock_resp

    results = piratebay.search("test query")
    assert len(results) == 2
    assert results[0]["name"] == "Some Movie 2024 1080p"
    # Should call the search URL
    mock_get.assert_called()
    args, _ = mock_get.call_args
    assert "/search/test%20query/" in args[0]
