"""IMDB and Rotten Tomatoes scraping helpers."""

from __future__ import annotations

import html
import json
import os
import secrets
import re
from typing import Any

import requests

IMDB_BASE_URL = os.environ.get("IMDB_BASE_URL", "https://www.imdb.com").rstrip("/")
RT_BASE_URL = os.environ.get("RT_BASE_URL", "https://www.rottentomatoes.com").rstrip(
    "/"
)

_IMDB_SUGGEST_URL = "https://v2.sg.media-imdb.com/suggestion"

_IMDB_ID_RE = re.compile(r"tt\d{5,9}")
_IMDB_LDJSON_RE = re.compile(
    r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
_IMDB_ROW_RE = re.compile(r"<tr[^>]*>.*?</tr>", re.IGNORECASE | re.DOTALL)
_IMDB_TITLE_RE = re.compile(
    r'<a href="/title/(tt\d+)/[^"]*">([^<]+)</a>', re.IGNORECASE
)
_IMDB_YEAR_RE = re.compile(r"\((\d{4})\)")

_RT_REVIEW_TEXT_RE = re.compile(
    r'data-qa="review-text"[^>]*>(.*?)</', re.IGNORECASE | re.DOTALL
)
_RT_REVIEW_ALT_RE = re.compile(
    r'class="review-text"[^>]*>(.*?)</', re.IGNORECASE | re.DOTALL
)
_RT_CONSENSUS_RE = re.compile(
    r'data-qa="critics-consensus"[^>]*>(.*?)</', re.IGNORECASE | re.DOTALL
)


def _fetch(url: str, accept: str = "text/html") -> str:
    headers = {
        "User-Agent": "tele-home-supervisor/1.0",
        "Accept": accept,
    }
    resp = requests.get(url, headers=headers, timeout=12)
    resp.raise_for_status()
    return resp.text


def _strip_tags(text: str) -> str:
    cleaned = re.sub(r"<[^>]+>", "", text or "")
    cleaned = html.unescape(cleaned)
    return " ".join(cleaned.split())


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _parse_ldjson(html_text: str) -> dict[str, Any] | None:
    match = _IMDB_LDJSON_RE.search(html_text)
    if not match:
        return None
    payload = match.group(1).strip()
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


def imdb_suggest(query: str) -> list[dict[str, Any]]:
    q = (query or "").strip()
    if not q:
        return []
    if _IMDB_ID_RE.fullmatch(q):
        return [{"id": q, "title": q, "type": "title"}]
    first = re.sub(r"[^a-z0-9]", "", q.lower())[:1] or "a"
    url = f"{_IMDB_SUGGEST_URL}/{first}/{requests.utils.quote(q)}.json"
    text = _fetch(url, accept="application/json")
    data = json.loads(text)
    return data.get("d", []) or []


def imdb_details(query: str) -> dict[str, Any] | None:
    results = imdb_suggest(query)
    if not results:
        return None
    first = results[0]
    imdb_id = first.get("id")
    if not imdb_id or not _IMDB_ID_RE.fullmatch(imdb_id):
        return None
    url = f"{IMDB_BASE_URL}/title/{imdb_id}/"
    html_text = _fetch(url)
    ld = _parse_ldjson(html_text) or {}

    title = ld.get("name") or first.get("l") or first.get("title") or imdb_id
    description = ld.get("description") or ""
    genres = _as_list(ld.get("genre"))
    content_rating = ld.get("contentRating") or ""
    runtime = ld.get("duration") or ""
    rating = (ld.get("aggregateRating") or {}).get("ratingValue")
    rating_count = (ld.get("aggregateRating") or {}).get("ratingCount")
    release = ld.get("datePublished") or ""
    cast = []
    for actor in _as_list(ld.get("actor")):
        name = actor.get("name") if isinstance(actor, dict) else str(actor)
        if name:
            cast.append(name)
        if len(cast) >= 4:
            break

    return {
        "id": imdb_id,
        "title": title,
        "description": description,
        "genres": genres,
        "content_rating": content_rating,
        "runtime": runtime,
        "rating": rating,
        "rating_count": rating_count,
        "release": release,
        "cast": cast,
        "url": url,
        "type": first.get("q") or first.get("type"),
    }


def imdb_trending(kind: str) -> list[dict[str, Any]]:
    if kind == "shows":
        url = f"{IMDB_BASE_URL}/chart/tvmeter/"
    else:
        url = f"{IMDB_BASE_URL}/chart/moviemeter/"
    html_text = _fetch(url)
    results: list[dict[str, Any]] = []
    for row in _IMDB_ROW_RE.findall(html_text):
        title_match = _IMDB_TITLE_RE.search(row)
        if not title_match:
            continue
        imdb_id = title_match.group(1)
        title = html.unescape(title_match.group(2))
        year_match = _IMDB_YEAR_RE.search(row)
        year = year_match.group(1) if year_match else ""
        results.append({"id": imdb_id, "title": title, "year": year})
        if len(results) >= 10:
            break
    return results


def rt_trending(kind: str) -> list[dict[str, Any]]:
    if kind == "shows":
        path = "/napi/browse/tv_series_browse"
    else:
        path = "/napi/browse/movies_in_theaters"
    url = f"{RT_BASE_URL}{path}?page=1"
    try:
        text = _fetch(url, accept="application/json")
        data = json.loads(text)
        return _rt_extract_items(data)
    except Exception:
        return []


def _rt_extract_items(payload: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    def add_item(obj: dict[str, Any]) -> None:
        title = obj.get("title") or obj.get("name")
        if not title:
            return
        url = obj.get("url") or obj.get("urlPath") or ""
        tomatometer = obj.get("tomatometerScore") or obj.get("tomatoScore") or {}
        audience = obj.get("audienceScore") or {}

        def score_val(score: Any) -> int | None:
            if isinstance(score, dict):
                score = score.get("score")
            try:
                return int(score)
            except Exception:
                return None

        items.append(
            {
                "title": str(title),
                "url": str(url),
                "tomatometer": score_val(tomatometer),
                "audience": score_val(audience),
            }
        )

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            if "title" in obj or "name" in obj:
                add_item(obj)
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)

    walk(payload)

    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        title = item.get("title")
        if not title or title in seen:
            continue
        seen.add(title)
        deduped.append(item)
        if len(deduped) >= 10:
            break
    return deduped


def rt_search(query: str) -> list[dict[str, Any]]:
    q = (query or "").strip()
    if not q:
        return []
    url = f"{RT_BASE_URL}/napi/search/?query={requests.utils.quote(q)}"
    try:
        text = _fetch(url, accept="application/json")
        data = json.loads(text)
    except Exception:
        return []
    results: list[dict[str, Any]] = []
    for group in ("movies", "tvSeries"):
        for item in data.get(group, []) or []:
            title = item.get("name") or item.get("title")
            if not title:
                continue
            url_path = item.get("url") or item.get("urlPath") or ""
            results.append(
                {
                    "title": str(title),
                    "url": str(url_path),
                    "type": "movie" if group == "movies" else "tv",
                }
            )
            if len(results) >= 10:
                return results
    return results


def rt_random_critic_quote(url_path: str) -> str | None:
    if not url_path:
        return None
    if not url_path.startswith("/"):
        url_path = f"/{url_path}"
    reviews_url = f"{RT_BASE_URL}{url_path}/reviews?type=top_critics"
    try:
        html_text = _fetch(reviews_url)
    except Exception:
        html_text = _fetch(f"{RT_BASE_URL}{url_path}")

    quotes = []
    for regex in (_RT_REVIEW_TEXT_RE, _RT_REVIEW_ALT_RE):
        quotes = [_strip_tags(match) for match in regex.findall(html_text)]
        quotes = [q for q in quotes if q]
        if quotes:
            break
    if quotes:
        return secrets.choice(quotes)
    consensus_match = _RT_CONSENSUS_RE.search(html_text)
    if consensus_match:
        return _strip_tags(consensus_match.group(1))
    return None
