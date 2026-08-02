"""Reddit module for the morning Intel briefing."""

from __future__ import annotations

import asyncio
import html
import logging
import random
import time
from html.parser import HTMLParser
from typing import Any

import httpx
from defusedxml import ElementTree

from .models.reddit_settings import RedditBriefingSettings, normalize_subreddit

logger = logging.getLogger(__name__)

_REDDIT_BASE_URL = "https://www.reddit.com"
_REDDIT_SCRAPE_BASE_URL = "https://old.reddit.com"
_USER_AGENT = (
    "Mozilla/5.0 (compatible; tele-home-supervisor/0.1; low-volume personal use)"
)
_TIMEOUT = httpx.Timeout(10.0, connect=3.5)
_CACHE_TTL_SECONDS = 30 * 60
_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
_CANDIDATE_CACHE: dict[tuple[str, str], tuple[float, tuple[dict[str, Any], ...]]] = {}
REDDIT_FETCH_MODES = {"top", "trending", "random"}
_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")
_VIDEO_SUFFIXES = (".mp4", ".webm", ".mov")


class _OldRedditParser(HTMLParser):
    """Extract post metadata from an old Reddit listing."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.posts: list[dict[str, Any]] = []
        self._post: dict[str, Any] | None = None
        self._post_depth = 0
        self._capture_title = False
        self._title_parts: list[str] = []
        self._body_container_depth: int | None = None
        self._body_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key: value or "" for key, value in attrs}
        classes = set(attributes.get("class", "").split())

        if tag == "div" and self._post is None and "thing" in classes:
            self._post = {
                "id": attributes.get("data-fullname", "").removeprefix("t3_"),
                "subreddit": attributes.get("data-subreddit", ""),
                "author": attributes.get("data-author", ""),
                "score": _parse_int(attributes.get("data-score")),
                "num_comments": _parse_int(attributes.get("data-comments-count")),
                "permalink": attributes.get("data-permalink", ""),
                "url": attributes.get("data-url", ""),
                "domain": attributes.get("data-domain", ""),
                "_skip": (
                    "stickied" in classes
                    or attributes.get("data-promoted") == "true"
                    or attributes.get("data-nsfw") == "true"
                ),
            }
            self._post_depth = 1
            return

        if self._post is None:
            return
        if tag == "div":
            self._post_depth += 1
            if "usertext-body" in classes:
                self._body_container_depth = self._post_depth
                self._body_parts = []
        if tag == "a" and "title" in classes:
            self._capture_title = True
            self._title_parts = []
        if (
            tag == "source"
            and attributes.get("type", "").startswith("video/")
            and attributes.get("src", "").startswith("https://")
            and not self._post.get("media_url")
        ):
            self._post["media_url"] = attributes["src"]

    def handle_data(self, data: str) -> None:
        if self._capture_title:
            self._title_parts.append(data)
        elif self._body_container_depth is not None:
            self._body_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._post is None:
            return
        if tag == "a" and self._capture_title:
            self._post["title"] = "".join(self._title_parts).strip()
            self._capture_title = False
        if tag == "p" and self._body_container_depth is not None:
            self._body_parts.append("\n")
        if tag != "div":
            return

        if self._body_container_depth == self._post_depth:
            paragraphs = [
                " ".join(paragraph.split())
                for paragraph in "".join(self._body_parts).splitlines()
                if paragraph.strip()
            ]
            if paragraphs:
                self._post["selftext"] = "\n".join(paragraphs)
            self._body_container_depth = None
            self._body_parts = []
        self._post_depth -= 1
        if self._post_depth == 0:
            post = self._post
            if (
                not post.pop("_skip")
                and post.get("id")
                and post.get("title")
                and post.get("permalink")
            ):
                self.posts.append(post)
            self._post = None


def _parse_int(value: str | None) -> int:
    try:
        return int(value or 0)
    except ValueError:
        return 0


def _mode_for(settings: RedditBriefingSettings, index: int) -> str:
    if settings.mode != "mixed":
        return settings.mode
    return ("top", "trending", "random")[index % 3]


def _parse_old_reddit(content: str) -> list[dict[str, Any]]:
    parser = _OldRedditParser()
    parser.feed(content)
    parser.close()
    return parser.posts


async def _get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, str] | None = None,
) -> httpx.Response:
    for attempt in range(3):
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response
        except (
            httpx.TimeoutException,
            httpx.NetworkError,
            httpx.HTTPStatusError,
        ):
            if attempt == 2:
                raise
            await asyncio.sleep(0.5 * (attempt + 1))
    raise RuntimeError("Reddit request retry loop ended unexpectedly")


async def _fetch_html_candidates(
    client: httpx.AsyncClient, subreddit: str, mode: str
) -> list[dict[str, Any]]:
    sort = "top" if mode == "top" else "hot"
    params = {"sort": "top", "t": "day"} if sort == "top" else None
    response = await _get_with_retry(
        client,
        f"{_REDDIT_SCRAPE_BASE_URL}/r/{subreddit}/{sort}/",
        params=params,
    )
    posts = _parse_old_reddit(response.text)
    if not posts:
        raise ValueError("Reddit public listing contained no posts")
    return posts


async def _fetch_rss_candidates(
    client: httpx.AsyncClient, subreddit: str, mode: str
) -> list[dict[str, Any]]:
    sort = "top" if mode == "top" else "hot"
    params = {"t": "day"} if sort == "top" else None
    response = await _get_with_retry(
        client,
        f"{_REDDIT_BASE_URL}/r/{subreddit}/{sort}/.rss",
        params=params,
    )
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
    sort = "top" if mode == "top" else "hot"
    cache_key = (subreddit, sort)
    cached = _CANDIDATE_CACHE.get(cache_key)
    now = time.monotonic()
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        return [dict(post) for post in cached[1]]

    async with httpx.AsyncClient(
        headers={"User-Agent": _USER_AGENT},
        timeout=_TIMEOUT,
        follow_redirects=True,
        transport=httpx.AsyncHTTPTransport(retries=2),
    ) as client:
        try:
            posts = await _fetch_html_candidates(client, subreddit, mode)
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(
                "Reddit HTML scrape failed for r/%s (%s), using RSS: %s",
                subreddit,
                mode,
                exc,
            )
            posts = await _fetch_rss_candidates(client, subreddit, mode)

    _CANDIDATE_CACHE[cache_key] = (now, tuple(dict(post) for post in posts))
    return [dict(post) for post in posts]


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


def format_reddit_post(post: dict[str, Any]) -> str:
    """Format one Reddit post for a Telegram message or media caption."""
    summary = _format_post(post, 1).removeprefix("1. ")
    body = str(post.get("selftext") or "").strip()
    if body:
        summary = f"{summary}\n\n{html.escape(body[:500])}"
    return summary


def reddit_post_media_kind(post: dict[str, Any]) -> str:
    """Return the Telegram delivery kind for a scraped post."""
    media_url = str(post.get("media_url") or post.get("url") or "").lower()
    path = media_url.split("?", 1)[0]
    if path.endswith(_IMAGE_SUFFIXES):
        return "photo"
    if path.endswith(_VIDEO_SUFFIXES):
        return "video"
    return "text"


async def fetch_reddit_post(subreddit: str, mode: str = "trending") -> dict[str, Any]:
    """Fetch one safe post from a subreddit using the requested ordering."""
    normalized = normalize_subreddit(subreddit)
    normalized_mode = mode.lower()
    if normalized is None:
        raise ValueError("Invalid subreddit name")
    if normalized_mode not in REDDIT_FETCH_MODES:
        raise ValueError("Mode must be trending, random, or top")

    posts = await _fetch_candidates(normalized, normalized_mode)
    if not posts:
        raise LookupError(f"No posts found in r/{normalized}")
    if normalized_mode == "random":
        return dict(
            random.choice(posts)  # noqa: S311  # nosec B311
        )
    return dict(posts[0])


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
