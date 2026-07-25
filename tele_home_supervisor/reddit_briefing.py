"""Reddit module for the morning Intel briefing."""

from __future__ import annotations

import html
import logging
import random
import time
from typing import Any

import httpx
from defusedxml import ElementTree

from .config import settings as app_settings
from .models.reddit_settings import RedditBriefingSettings

logger = logging.getLogger(__name__)

_REDDIT_BASE_URL = "https://www.reddit.com"
_TIMEOUT = httpx.Timeout(10.0, connect=3.5)
_OAUTH_TOKEN: str | None = None
_OAUTH_TOKEN_EXPIRES_AT = 0.0
_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


def _mode_for(settings: RedditBriefingSettings, index: int) -> str:
    if settings.mode != "mixed":
        return settings.mode
    return ("top", "trending", "random")[index % 3]


async def _get_oauth_token(client: httpx.AsyncClient) -> str | None:
    global _OAUTH_TOKEN, _OAUTH_TOKEN_EXPIRES_AT
    if not app_settings.REDDIT_CLIENT_ID or not app_settings.REDDIT_CLIENT_SECRET:
        return None
    if _OAUTH_TOKEN and time.time() < _OAUTH_TOKEN_EXPIRES_AT:
        return _OAUTH_TOKEN

    response = await client.post(
        "https://www.reddit.com/api/v1/access_token",
        data={"grant_type": "client_credentials"},
        auth=(
            app_settings.REDDIT_CLIENT_ID,
            app_settings.REDDIT_CLIENT_SECRET,
        ),
    )
    response.raise_for_status()
    payload = response.json()
    token = str(payload.get("access_token") or "")
    if not token:
        return None
    _OAUTH_TOKEN = token
    _OAUTH_TOKEN_EXPIRES_AT = time.time() + max(
        60, int(payload.get("expires_in") or 3600) - 60
    )
    return token


async def _fetch_json_candidates(
    client: httpx.AsyncClient, subreddit: str, mode: str, token: str
) -> list[dict[str, Any]]:
    sort = "top" if mode == "top" else "hot"
    params: dict[str, str | int] = {"limit": 15, "raw_json": 1}
    if sort == "top":
        params["t"] = "day"
    url = f"https://oauth.reddit.com/r/{subreddit}/{sort}"
    response = await client.get(
        url, params=params, headers={"Authorization": f"Bearer {token}"}
    )
    response.raise_for_status()
    payload = response.json()

    children = payload.get("data", {}).get("children", [])
    return [
        child["data"]
        for child in children
        if isinstance(child, dict)
        and isinstance(child.get("data"), dict)
        and not child["data"].get("over_18")
        and not child["data"].get("stickied")
    ]


async def _fetch_rss_candidates(
    client: httpx.AsyncClient, subreddit: str, mode: str
) -> list[dict[str, Any]]:
    sort = "top" if mode == "top" else "hot"
    params = {"t": "day"} if sort == "top" else None
    response = await client.get(
        f"{_REDDIT_BASE_URL}/r/{subreddit}/{sort}/.rss", params=params
    )
    response.raise_for_status()
    root = ElementTree.fromstring(response.content)
    posts: list[dict[str, Any]] = []
    for entry in root.findall("atom:entry", _ATOM_NS):
        title = entry.findtext("atom:title", default="Untitled", namespaces=_ATOM_NS)
        author = entry.findtext(
            "atom:author/atom:name", default="unknown", namespaces=_ATOM_NS
        )
        link_node = entry.find("atom:link[@rel='alternate']", _ATOM_NS)
        if link_node is None:
            link_node = entry.find("atom:link", _ATOM_NS)
        link = link_node.get("href", "") if link_node is not None else ""
        posts.append(
            {
                "id": entry.findtext("atom:id", default=link, namespaces=_ATOM_NS),
                "title": title,
                "subreddit": subreddit,
                "author": author.removeprefix("/u/"),
                "permalink": link,
                "metadata_available": False,
            }
        )
    return posts


async def _fetch_candidates(subreddit: str, mode: str) -> list[dict[str, Any]]:
    headers = {"User-Agent": app_settings.REDDIT_USER_AGENT}
    async with httpx.AsyncClient(
        headers=headers,
        timeout=_TIMEOUT,
        follow_redirects=True,
        transport=httpx.AsyncHTTPTransport(retries=2),
    ) as client:
        token = await _get_oauth_token(client)
        if token:
            return await _fetch_json_candidates(client, subreddit, mode, token)
        return await _fetch_rss_candidates(client, subreddit, mode)


def _format_post(post: dict[str, Any], index: int) -> str:
    title = html.escape(str(post.get("title") or "Untitled"))
    subreddit = html.escape(str(post.get("subreddit") or "unknown"))
    author = html.escape(str(post.get("author") or "unknown"))
    metadata_available = post.get("metadata_available", True)
    score = f"{int(post.get('score') or 0):,}" if metadata_available else "n/a"
    comments = (
        f"{int(post.get('num_comments') or 0):,}" if metadata_available else "n/a"
    )
    permalink = str(post.get("permalink") or "")
    if permalink.startswith("https://"):
        link = html.escape(permalink, quote=True)
    else:
        link = html.escape(f"https://www.reddit.com{permalink}", quote=True)
    return (
        f'{index}. <a href="{link}">{title}</a>\n'
        f"   r/{subreddit} · ↑ {score} · 💬 {comments} · u/{author}"
    )


async def get_reddit_digest(settings: RedditBriefingSettings) -> str:
    """Fetch and format the configured number of Reddit posts."""
    subreddits = settings.subreddits()
    if not subreddits:
        return (
            "👽 <b>Reddit</b>\n"
            "No subreddits configured. Use /reddit_settings to add a group or subreddit."
        )

    random.shuffle(subreddits)
    attempts = max(settings.post_count * 3, len(subreddits))
    posts: list[dict[str, Any]] = []
    seen: set[str] = set()
    failures: list[str] = []
    candidate_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}

    for index in range(attempts):
        if len(posts) >= settings.post_count:
            break
        subreddit = subreddits[index % len(subreddits)]
        mode = _mode_for(settings, index)
        cache_key = (subreddit, "top" if mode == "top" else "hot")
        if cache_key not in candidate_cache:
            try:
                candidate_cache[cache_key] = await _fetch_candidates(subreddit, mode)
            except Exception as exc:
                candidate_cache[cache_key] = []
                failures.append(str(exc))
                logger.warning(
                    "Reddit fetch failed for r/%s (%s): %s", subreddit, mode, exc
                )

        candidates = candidate_cache[cache_key]
        if mode == "random":
            random.shuffle(candidates)
        while candidates:
            candidate = candidates.pop(0)
            post_id = str(candidate.get("id") or candidate.get("permalink") or "")
            if post_id and post_id not in seen:
                seen.add(post_id)
                posts.append(candidate)
                break

    if not posts:
        reason = html.escape(failures[0] if failures else "no matching posts")
        return f"👽 <b>Reddit</b>\n❌ Reddit unavailable: {reason}"

    lines = ["👽 <b>Reddit Radar</b>"]
    lines.extend(_format_post(post, index) for index, post in enumerate(posts, 1))
    return "\n".join(lines)
