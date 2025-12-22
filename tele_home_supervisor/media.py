"""IMDB scraping helpers."""

from __future__ import annotations

import html
import json
import logging
import os
import re
from typing import Any
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

IMDB_BASE_URL = os.environ.get("IMDB_BASE_URL", "https://www.imdb.com").rstrip("/")
MEDIA_USER_AGENT = os.environ.get(
    "MEDIA_USER_AGENT",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
)
IMDB_COOKIE = os.environ.get("IMDB_COOKIE", "")
IMDB_REFERER = os.environ.get("IMDB_REFERER", "")

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
_IMDB_FIND_RE = re.compile(r'href="/title/(tt\d+)/', re.IGNORECASE)


def _fetch(
    url: str,
    accept: str = "text/html",
    debug_sink=None,
    debug_label: str | None = None,
) -> str:
    accept_header = accept
    if accept == "text/html":
        accept_header = (
            "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        )
    elif accept == "application/json":
        accept_header = "application/json, text/plain, */*"
    referer = ""
    parsed = urlparse(url)
    if parsed.scheme and parsed.netloc:
        referer = f"{parsed.scheme}://{parsed.netloc}/"
    headers = {
        "User-Agent": MEDIA_USER_AGENT,
        "Accept": accept_header,
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "DNT": "1",
        "Connection": "keep-alive",
    }
    if "text/html" in accept:
        headers["Upgrade-Insecure-Requests"] = "1"
        headers["Sec-Fetch-Dest"] = "document"
        headers["Sec-Fetch-Mode"] = "navigate"
        headers["Sec-Fetch-Site"] = "none"
        headers["Sec-Fetch-User"] = "?1"
        headers["Sec-CH-UA"] = '"Chromium";v="120", "Not.A/Brand";v="8"'
        headers["Sec-CH-UA-Mobile"] = "?0"
        headers["Sec-CH-UA-Platform"] = '"Linux"'
    if referer:
        headers["Referer"] = referer
    if IMDB_REFERER and "imdb.com" in parsed.netloc:
        headers["Referer"] = IMDB_REFERER
    if IMDB_COOKIE and "imdb.com" in parsed.netloc:
        headers["Cookie"] = IMDB_COOKIE
    try:
        resp = requests.get(url, headers=headers, timeout=12)
    except requests.RequestException as exc:
        if debug_sink:
            debug_sink(f"{debug_label or 'request failed'}: {url}", str(exc))
        raise
    if not resp.ok:
        snippet = resp.text[:500].replace("\n", " ")
        detail = f"{resp.status_code} {resp.reason} {snippet}".strip()
        if debug_sink:
            debug_sink(f"{debug_label or 'http error'}: {url}", detail)
        raise RuntimeError(f"HTTP {resp.status_code} for {url}: {snippet}")
    return resp.text


def _ensure_not_blocked(
    html_text: str, source: str, debug_sink=None, debug_label: str | None = None
) -> None:
    markers = (
        "cf-chl",
        "cloudflare",
        "just a moment",
        "attention required",
        "captcha",
        "access denied",
        "enable javascript",
        "please enable",
        "are you a human",
        "automated access",
    )
    lower = html_text.lower()
    if any(marker in lower for marker in markers):
        snippet = html_text[:500].replace("\n", " ")
        if debug_sink:
            debug_sink(debug_label or f"{source} blocked", snippet)
        raise RuntimeError(f"{source} blocked by anti-bot protection: {snippet}")


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


def imdb_suggest(query: str, debug_sink=None) -> list[dict[str, Any]]:
    q = (query or "").strip()
    if not q:
        return []
    if _IMDB_ID_RE.fullmatch(q):
        return [{"id": q, "title": q, "type": "title"}]
    first = re.sub(r"[^a-z0-9]", "", q.lower())[:1] or "a"
    url = f"{_IMDB_SUGGEST_URL}/{first}/{requests.utils.quote(q)}.json"
    text = _fetch(
        url,
        accept="application/json",
        debug_sink=debug_sink,
        debug_label="imdb suggest",
    )
    data = json.loads(text)
    return data.get("d", []) or []


def imdb_details(query: str, debug_sink=None) -> dict[str, Any] | None:
    q = (query or "").strip()
    results: list[dict[str, Any]] = []
    if _IMDB_ID_RE.fullmatch(q):
        results = [{"id": q, "title": q, "type": "title"}]
    else:
        results = _imdb_search_fallback(q, debug_sink=debug_sink)
        if not results:
            results = imdb_suggest(q, debug_sink=debug_sink)
            if not results:
                return None
    first = results[0]
    imdb_id = first.get("id")
    if not imdb_id or not _IMDB_ID_RE.fullmatch(imdb_id):
        return None
    url = f"{IMDB_BASE_URL}/title/{imdb_id}/"
    try:
        html_text = _fetch(url, debug_sink=debug_sink, debug_label="imdb title")
        _ensure_not_blocked(
            html_text, "IMDB", debug_sink=debug_sink, debug_label="imdb blocked"
        )
        ld = _parse_ldjson(html_text) or {}
    except RuntimeError as exc:
        if debug_sink:
            debug_sink("imdb title blocked fallback", str(exc))
        ld = {}

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
    if not cast:
        actors = first.get("s") or ""
        if isinstance(actors, str):
            cast = [a.strip() for a in actors.split(",") if a.strip()][:4]
    if not release:
        release = str(first.get("y") or "")
    if not genres:
        genre_hint = first.get("q") or ""
        if genre_hint:
            genres = [str(genre_hint)]

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


def imdb_trending(kind: str, debug_sink=None) -> list[dict[str, Any]]:
    if kind == "shows":
        url = f"{IMDB_BASE_URL}/chart/tvmeter/"
    else:
        url = f"{IMDB_BASE_URL}/chart/moviemeter/"
    html_text = _fetch(url, debug_sink=debug_sink, debug_label="imdb trending")
    _ensure_not_blocked(
        html_text, "IMDB", debug_sink=debug_sink, debug_label="imdb blocked"
    )
    results = _imdb_trending_from_ldjson(html_text)
    if results:
        return results[:10]
    return _imdb_trending_from_table(html_text)


def _imdb_search_fallback(query: str, debug_sink=None) -> list[dict[str, Any]]:
    q = (query or "").strip()
    if not q:
        return []
    url = f"{IMDB_BASE_URL}/find/?q={requests.utils.quote(q)}&s=tt"
    html_text = _fetch(url, debug_sink=debug_sink, debug_label="imdb search")
    _ensure_not_blocked(
        html_text, "IMDB", debug_sink=debug_sink, debug_label="imdb blocked"
    )
    match = _IMDB_FIND_RE.search(html_text)
    if not match:
        return []
    return [{"id": match.group(1), "title": q, "type": "title"}]


def _imdb_trending_from_ldjson(html_text: str) -> list[dict[str, Any]]:
    ld = _parse_ldjson(html_text)
    if not ld or ld.get("@type") != "ItemList":
        return []
    items = _as_list(ld.get("itemListElement"))
    results: list[dict[str, Any]] = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        item = entry.get("item") or {}
        if isinstance(item, dict):
            name = item.get("name") or ""
            url = item.get("url") or ""
        else:
            name = ""
            url = ""
        imdb_id = ""
        if url:
            match = _IMDB_ID_RE.search(url)
            if match:
                imdb_id = match.group(0)
        if not imdb_id:
            continue
        results.append({"id": imdb_id, "title": str(name), "year": ""})
        if len(results) >= 10:
            break
    return results


def _imdb_trending_from_table(html_text: str) -> list[dict[str, Any]]:
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
    if not results:
        raise RuntimeError("IMDB trending parse failed")
    return results
