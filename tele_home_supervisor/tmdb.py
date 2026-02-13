"""TMDB API helpers."""

from __future__ import annotations

import logging
from typing import Any

import requests

from . import config

logger = logging.getLogger(__name__)


def _ensure_api_key() -> None:
    if not config.settings.TMDB_API_KEY:
        raise RuntimeError("TMDB_API_KEY is not configured")


def _fetch(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    _ensure_api_key()
    url = f"{config.settings.TMDB_BASE_URL}{path}"
    payload = {"api_key": config.settings.TMDB_API_KEY, "language": "en-US"}
    if params:
        payload.update(params)
    headers = {
        "User-Agent": config.settings.TMDB_USER_AGENT,
        "Accept": "application/json",
    }
    resp = requests.get(url, params=payload, headers=headers, timeout=12)
    if not resp.ok:
        snippet = resp.text[:500].replace("\n", " ")
        raise RuntimeError(f"TMDB HTTP {resp.status_code}: {snippet}")
    return resp.json()


def trending_movies(page: int = 1) -> dict[str, Any]:
    return _fetch("/trending/movie/day", {"page": page})


def trending_shows(page: int = 1) -> dict[str, Any]:
    return _fetch("/trending/tv/day", {"page": page})


def in_cinema(page: int = 1) -> dict[str, Any]:
    return _fetch("/movie/now_playing", {"page": page})


def search_multi(query: str, page: int = 1) -> dict[str, Any]:
    return _fetch(
        "/search/multi", {"query": query, "page": page, "include_adult": False}
    )


def movie_details(movie_id: int) -> dict[str, Any]:
    return _fetch(f"/movie/{movie_id}")


def tv_details(tv_id: int) -> dict[str, Any]:
    return _fetch(f"/tv/{tv_id}")


def extract_items(
    data: dict[str, Any], default_type: str | None = None
) -> list[dict[str, Any]]:
    results = data.get("results") or []
    items: list[dict[str, Any]] = []
    for entry in results:
        if not isinstance(entry, dict):
            continue
        media_type = entry.get("media_type") or default_type
        if media_type not in {"movie", "tv"}:
            continue
        title = entry.get("title") or entry.get("name") or ""
        if not title:
            continue
        date = entry.get("release_date") or entry.get("first_air_date") or ""
        year = date.split("-")[0] if isinstance(date, str) and date else ""
        items.append(
            {
                "id": entry.get("id"),
                "title": title,
                "media_type": media_type,
                "year": year,
                "rating": entry.get("vote_average"),
            }
        )
        if len(items) >= 10:
            break
    return items
