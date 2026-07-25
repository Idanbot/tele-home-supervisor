from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from tele_home_supervisor import reddit_briefing
from tele_home_supervisor.models.reddit_settings import (
    RedditBriefingSettings,
    normalize_subreddit,
)


def test_reddit_settings_normalizes_and_clamps() -> None:
    settings = RedditBriefingSettings.from_dict(
        {
            "enabled_groups": ["tech", "invalid"],
            "custom_subreddits": ["r/Linux", "../bad", "python"],
            "post_count": 99,
            "mode": "RANDOM",
        }
    )

    assert settings.enabled_groups == {"tech"}
    assert settings.custom_subreddits == {"linux", "python"}
    assert settings.post_count == 5
    assert settings.mode == "random"
    assert normalize_subreddit("r/devops") == "devops"
    assert normalize_subreddit("bad/name") is None
    assert RedditBriefingSettings.from_dict(None).post_count == 3


def test_old_reddit_parser_extracts_metadata_and_filters_unsafe_posts() -> None:
    listing = """
    <div class="thing link" data-fullname="t3_safe"
         data-author="alice" data-subreddit="python" data-score="123"
         data-comments-count="45" data-permalink="/r/python/comments/safe"
         data-promoted="false" data-nsfw="false">
      <div class="entry"><a class="title may-blank">Safe &amp; useful</a></div>
    </div>
    <div class="thing link stickied" data-fullname="t3_sticky"
         data-author="mod" data-subreddit="python" data-score="1"
         data-comments-count="2" data-permalink="/r/python/comments/sticky"
         data-promoted="false" data-nsfw="false">
      <a class="title">Pinned post</a>
    </div>
    <div class="thing link" data-fullname="t3_nsfw"
         data-author="bob" data-subreddit="python"
         data-permalink="/r/python/comments/nsfw"
         data-promoted="false" data-nsfw="true">
      <a class="title">Filtered post</a>
    </div>
    """

    assert reddit_briefing._parse_old_reddit(listing) == [
        {
            "id": "safe",
            "subreddit": "python",
            "author": "alice",
            "score": 123,
            "num_comments": 45,
            "permalink": "/r/python/comments/safe",
            "title": "Safe & useful",
        }
    ]


@pytest.mark.asyncio
async def test_reddit_digest_formats_metadata(monkeypatch) -> None:
    settings = RedditBriefingSettings(
        enabled_groups=set(),
        custom_subreddits={"python"},
        post_count=2,
        mode="mixed",
    )
    fetch = AsyncMock(
        side_effect=[
            [
                {
                    "id": "one",
                    "title": "First <post>",
                    "subreddit": "python",
                    "author": "dev",
                    "score": 1234,
                    "num_comments": 45,
                    "permalink": "/r/python/comments/one",
                }
            ],
            [
                {
                    "id": "two",
                    "title": "Second post",
                    "subreddit": "python",
                    "author": "ops",
                    "score": 12,
                    "num_comments": 3,
                    "permalink": "/r/python/comments/two",
                }
            ],
        ]
    )
    monkeypatch.setattr(reddit_briefing, "_fetch_candidates", fetch)

    result = await reddit_briefing.get_reddit_digest(settings)

    assert "Reddit Radar" in result
    assert "First &lt;post&gt;" in result
    assert "↑ 1,234" in result
    assert "r/python" in result
    assert "https://www.reddit.com/r/python/comments/one" in result
    assert [call.args[1] for call in fetch.await_args_list] == ["top", "trending"]


@pytest.mark.asyncio
async def test_reddit_digest_handles_empty_and_failure(monkeypatch) -> None:
    empty = RedditBriefingSettings(enabled_groups=set())
    assert "No subreddits configured" in await reddit_briefing.get_reddit_digest(empty)

    configured = RedditBriefingSettings(
        enabled_groups=set(),
        custom_subreddits={"python"},
        post_count=1,
        mode="trending",
    )
    fetch = AsyncMock(side_effect=RuntimeError("offline"))
    monkeypatch.setattr(
        reddit_briefing,
        "_fetch_candidates",
        fetch,
    )
    assert "Reddit unavailable" in await reddit_briefing.get_reddit_digest(configured)
    fetch.assert_awaited_once()


@pytest.mark.asyncio
async def test_rss_fallback_parses_atom_safely() -> None:
    rss = b"""<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <id>post-1</id>
        <title>Safe fallback</title>
        <author><name>/u/redditor</name></author>
        <link href="https://www.reddit.com/r/python/post-1"/>
      </entry>
    </feed>"""
    response = httpx.Response(
        200,
        content=rss,
        request=httpx.Request("GET", "https://www.reddit.com"),
    )
    client = AsyncMock()
    client.get.return_value = response

    posts = await reddit_briefing._fetch_rss_candidates(client, "python", "trending")

    assert posts == [
        {
            "id": "post-1",
            "title": "Safe fallback",
            "subreddit": "python",
            "author": "redditor",
            "permalink": "https://www.reddit.com/r/python/post-1",
            "metadata_available": False,
        }
    ]
    assert "↑ n/a" in reddit_briefing._format_post(posts[0], 1)


@pytest.mark.asyncio
async def test_fetch_candidates_scrapes_and_caches(monkeypatch) -> None:
    reddit_briefing._CANDIDATE_CACHE.clear()
    scraped = [
        {
            "id": "one",
            "title": "Scraped",
            "subreddit": "python",
            "author": "dev",
            "score": 5,
            "num_comments": 2,
            "permalink": "/r/python/comments/one",
        }
    ]
    scrape = AsyncMock(return_value=scraped)
    rss = AsyncMock()
    monkeypatch.setattr(reddit_briefing, "_fetch_html_candidates", scrape)
    monkeypatch.setattr(reddit_briefing, "_fetch_rss_candidates", rss)

    first = await reddit_briefing._fetch_candidates("python", "trending")
    first[0]["title"] = "mutated"
    second = await reddit_briefing._fetch_candidates("python", "trending")

    assert second[0]["title"] == "Scraped"
    scrape.assert_awaited_once()
    rss.assert_not_awaited()


@pytest.mark.asyncio
async def test_fetch_candidates_uses_rss_when_scrape_fails(monkeypatch) -> None:
    reddit_briefing._CANDIDATE_CACHE.clear()
    scrape = AsyncMock(side_effect=httpx.HTTPError("blocked"))
    fallback = [{"id": "rss", "title": "Fallback"}]
    rss = AsyncMock(return_value=fallback)
    monkeypatch.setattr(reddit_briefing, "_fetch_html_candidates", scrape)
    monkeypatch.setattr(reddit_briefing, "_fetch_rss_candidates", rss)

    assert await reddit_briefing._fetch_candidates("python", "top") == fallback
    scrape.assert_awaited_once()
    rss.assert_awaited_once()
