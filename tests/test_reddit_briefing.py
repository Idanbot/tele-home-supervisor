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
