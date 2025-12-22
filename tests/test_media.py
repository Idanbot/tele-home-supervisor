import json

from tele_home_supervisor import media


def test_rt_extract_next_data_from_next_script() -> None:
    payload = {"props": {"pageProps": {"items": [{"title": "Foo"}]}}}
    html = (
        "<html><head></head><body>"
        '<script id="__NEXT_DATA__" type="application/json">'
        f"{json.dumps(payload)}"
        "</script></body></html>"
    )
    data = media._rt_extract_next_data(html)
    assert data["props"]["pageProps"]["items"][0]["title"] == "Foo"


def test_rt_extract_next_data_from_state_marker() -> None:
    payload = {"state": {"search": [{"title": "Bar"}]}}
    html = (
        "<html><body>"
        f"<script>window.__INITIAL_STATE__ = {json.dumps(payload)};</script>"
        "</body></html>"
    )
    data = media._rt_extract_next_data(html)
    assert data["state"]["search"][0]["title"] == "Bar"


def test_rt_extract_items_collects_titles() -> None:
    data = {
        "items": [
            {"title": "Movie A", "url": "/m/movie-a", "tomatometerScore": 92},
            {"name": "Show B", "urlPath": "/tv/show-b", "audienceScore": 81},
        ]
    }
    items = media._rt_extract_items(data)
    assert len(items) == 2
    assert items[0]["title"] == "Movie A"
    assert items[1]["title"] == "Show B"


def test_rt_extract_search_items_dedupes() -> None:
    data = {
        "results": [
            {"title": "Search One", "url": "/m/search-one"},
            {"title": "Search One", "url": "/m/search-one"},
        ]
    }
    items = media._rt_extract_search_items(data)
    assert len(items) == 1
    assert items[0]["title"] == "Search One"
