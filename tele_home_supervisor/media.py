"""IMDB and Rotten Tomatoes scraping helpers."""

from __future__ import annotations

import html
import json
import logging
import os
import secrets
import re
from urllib.parse import urlparse
from typing import Any

import requests

logger = logging.getLogger(__name__)

IMDB_BASE_URL = os.environ.get("IMDB_BASE_URL", "https://www.imdb.com").rstrip("/")
RT_BASE_URL = os.environ.get("RT_BASE_URL", "https://www.rottentomatoes.com").rstrip(
    "/"
)
RT_ALGOLIA_APP_ID = os.environ.get("RT_ALGOLIA_APP_ID", "")
RT_ALGOLIA_API_KEY = os.environ.get("RT_ALGOLIA_API_KEY", "")
RT_ALGOLIA_INDEX = os.environ.get("RT_ALGOLIA_INDEX", "")
MEDIA_USER_AGENT = os.environ.get(
    "MEDIA_USER_AGENT",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
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
_IMDB_FIND_RE = re.compile(r'href="/title/(tt\d+)/', re.IGNORECASE)

_RT_NEXT_DATA_RE = re.compile(
    r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
_RT_DATA_JSON_RE = re.compile(r'data-json="([^"]+)"', re.IGNORECASE)
_RT_DATA_PAGE_RE = re.compile(r'data-page="([^"]+)"', re.IGNORECASE)
_RT_STATE_MARKERS = ("window.__INITIAL_STATE__", "window.__PRELOADED_STATE__")
_RT_TILE_RE = re.compile(r"<tile-dynamic[^>]+>", re.IGNORECASE)
_RT_TILE_GENERIC_RE = re.compile(
    r"<[^>]+data-title=\"[^\"]+\"[^>]+data-url=\"[^\"]+\"[^>]*>", re.IGNORECASE
)
_RT_ATTR_RE = re.compile(r'([a-zA-Z0-9_-]+)="([^"]+)"')
_RT_ALGOLIA_APP_RE = re.compile(r'algoliaAppId["\']\s*:\s*["\']([^"\']+)')
_RT_ALGOLIA_KEY_RE = re.compile(r'algoliaApiKey["\']\s*:\s*["\']([^"\']+)')
_RT_ALGOLIA_INDEX_RE = re.compile(r'indexName["\']\s*:\s*["\']([^"\']+)')

_RT_REVIEW_TEXT_RE = re.compile(
    r'data-qa="review-text"[^>]*>(.*?)</', re.IGNORECASE | re.DOTALL
)
_RT_REVIEW_ALT_RE = re.compile(
    r'class="review-text"[^>]*>(.*?)</', re.IGNORECASE | re.DOTALL
)
_RT_CONSENSUS_RE = re.compile(
    r'data-qa="critics-consensus"[^>]*>(.*?)</', re.IGNORECASE | re.DOTALL
)


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
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    if "text/html" in accept:
        headers["Upgrade-Insecure-Requests"] = "1"
    if referer:
        headers["Referer"] = referer
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


def _strip_tags(text: str) -> str:
    cleaned = re.sub(r"<[^>]+>", "", text or "")
    cleaned = html.unescape(cleaned)
    return " ".join(cleaned.split())


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
    results = imdb_suggest(query, debug_sink=debug_sink)
    if not results:
        results = _imdb_search_fallback(query, debug_sink=debug_sink)
        if not results:
            return None
    first = results[0]
    imdb_id = first.get("id")
    if not imdb_id or not _IMDB_ID_RE.fullmatch(imdb_id):
        return None
    url = f"{IMDB_BASE_URL}/title/{imdb_id}/"
    html_text = _fetch(url, debug_sink=debug_sink, debug_label="imdb title")
    _ensure_not_blocked(
        html_text, "IMDB", debug_sink=debug_sink, debug_label="imdb blocked"
    )
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


def rt_trending(kind: str, debug_sink=None) -> list[dict[str, Any]]:
    api_paths = [
        "/napi/browse/tv_series_browse"
        if kind == "shows"
        else "/napi/browse/movies_in_theaters",
        "/napi/browse/tv_series_browse?page=1"
        if kind == "shows"
        else "/napi/browse/movies_in_theaters?page=1",
    ]
    for path in api_paths:
        url = f"{RT_BASE_URL}{path}"
        try:
            text = _fetch(
                url,
                accept="application/json",
                debug_sink=debug_sink,
                debug_label="rt trending api",
            )
            data = json.loads(text)
            items = _rt_extract_items(data)
            if items:
                return items
        except Exception as exc:
            if debug_sink:
                debug_sink(f"rt trending api failed: {url}", str(exc))

    browse_path = (
        "/browse/tv_series_browse" if kind == "shows" else "/browse/movies_in_theaters"
    )
    html_text = _fetch(
        f"{RT_BASE_URL}{browse_path}",
        debug_sink=debug_sink,
        debug_label="rt trending page",
    )
    _ensure_not_blocked(
        html_text,
        "Rotten Tomatoes",
        debug_sink=debug_sink,
        debug_label="rt blocked",
    )
    try:
        data = _rt_extract_next_data(html_text)
        items = _rt_extract_items(data)
        if items:
            return items
    except Exception as exc:
        if debug_sink:
            debug_sink("rt trending next data parse failed", str(exc))
        logger.debug("rt trending next data parse failed: %s", exc)

    items = _rt_extract_tiles(html_text)
    if not items:
        raise RuntimeError("Rotten Tomatoes trending parse failed")
    return items


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


def rt_search(query: str, debug_sink=None) -> list[dict[str, Any]]:
    q = (query or "").strip()
    if not q:
        return []
    url = f"{RT_BASE_URL}/napi/search/?query={requests.utils.quote(q)}"
    try:
        text = _fetch(
            url,
            accept="application/json",
            debug_sink=debug_sink,
            debug_label="rt search api",
        )
        data = json.loads(text)
    except Exception:
        data = None
    results: list[dict[str, Any]] = []
    if data:
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
        if results:
            return results

    html_text = _fetch(
        f"{RT_BASE_URL}/search?search={requests.utils.quote(q)}",
        debug_sink=debug_sink,
        debug_label="rt search page",
    )
    _ensure_not_blocked(
        html_text,
        "Rotten Tomatoes",
        debug_sink=debug_sink,
        debug_label="rt blocked",
    )
    try:
        data = _rt_extract_next_data(html_text)
        results = _rt_extract_search_items(data)
        if results:
            return results[:10]
    except Exception as exc:
        if debug_sink:
            debug_sink("rt search next data parse failed", str(exc))
        logger.debug("rt search next data parse failed: %s", exc)

    results = _rt_search_algolia(q, html_text)
    if not results:
        raise RuntimeError("Rotten Tomatoes search parse failed")
    return results[:10]


def rt_random_critic_quote(url_path: str, debug_sink=None) -> str | None:
    if not url_path:
        return None
    if not url_path.startswith("/"):
        url_path = f"/{url_path}"
    reviews_url = f"{RT_BASE_URL}{url_path}/reviews?type=top_critics"
    try:
        html_text = _fetch(
            reviews_url, debug_sink=debug_sink, debug_label="rt reviews page"
        )
    except Exception:
        html_text = _fetch(
            f"{RT_BASE_URL}{url_path}",
            debug_sink=debug_sink,
            debug_label="rt title page",
        )
    _ensure_not_blocked(
        html_text,
        "Rotten Tomatoes",
        debug_sink=debug_sink,
        debug_label="rt blocked",
    )

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


def _extract_json_object(text: str, start_idx: int) -> str | None:
    brace_idx = text.find("{", start_idx)
    if brace_idx == -1:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(brace_idx, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[brace_idx : i + 1]
    return None


def _rt_extract_next_data(html_text: str) -> dict[str, Any]:
    match = _RT_NEXT_DATA_RE.search(html_text)
    if match:
        payload = match.group(1).strip()
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Rotten Tomatoes next data parse failed") from exc

    data_match = _RT_DATA_JSON_RE.search(html_text)
    if data_match:
        payload = html.unescape(data_match.group(1))
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Rotten Tomatoes data-json parse failed") from exc

    page_match = _RT_DATA_PAGE_RE.search(html_text)
    if page_match:
        payload = html.unescape(page_match.group(1))
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Rotten Tomatoes data-page parse failed") from exc

    for marker in _RT_STATE_MARKERS:
        idx = html_text.find(marker)
        if idx == -1:
            continue
        payload = _extract_json_object(html_text, idx)
        if not payload:
            continue
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Rotten Tomatoes state parse failed") from exc

    logger.debug(
        "rt next data missing: next=%s data-json=%s data-page=%s state=%s",
        bool(_RT_NEXT_DATA_RE.search(html_text)),
        bool(_RT_DATA_JSON_RE.search(html_text)),
        bool(_RT_DATA_PAGE_RE.search(html_text)),
        any(marker in html_text for marker in _RT_STATE_MARKERS),
    )
    snippet = html_text[:500].replace("\n", " ")
    raise RuntimeError(f"Rotten Tomatoes page missing next data: {snippet}")


def _rt_extract_search_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    def add_item(obj: dict[str, Any]) -> None:
        title = obj.get("title") or obj.get("name")
        url = obj.get("url") or obj.get("urlPath") or ""
        if not title or not url:
            return
        results.append({"title": str(title), "url": str(url)})

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            if "title" in obj or "name" in obj:
                add_item(obj)
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)

    walk(data)
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in results:
        key = f"{item.get('title')}|{item.get('url')}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= 10:
            break
    return deduped


def _rt_extract_tiles(html_text: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    tags = _RT_TILE_RE.findall(html_text)
    if not tags:
        tags = _RT_TILE_GENERIC_RE.findall(html_text)
    for tag in tags:
        attrs = dict(_RT_ATTR_RE.findall(tag))
        title = attrs.get("data-title") or attrs.get("title") or ""
        url = attrs.get("data-url") or attrs.get("data-href") or ""
        if title:
            items.append({"title": html.unescape(title), "url": url})
        if len(items) >= 10:
            break
    return items


def _rt_search_algolia(query: str, html_text: str) -> list[dict[str, Any]]:
    app_id = RT_ALGOLIA_APP_ID
    api_key = RT_ALGOLIA_API_KEY
    index = RT_ALGOLIA_INDEX

    if not (app_id and api_key and index):
        app_match = _RT_ALGOLIA_APP_RE.search(html_text)
        key_match = _RT_ALGOLIA_KEY_RE.search(html_text)
        idx_match = _RT_ALGOLIA_INDEX_RE.search(html_text)
        app_id = app_id or (app_match.group(1) if app_match else "")
        api_key = api_key or (key_match.group(1) if key_match else "")
        index = index or (idx_match.group(1) if idx_match else "")

    if not (app_id and api_key and index):
        return []

    url = f"https://{app_id}-dsn.algolia.net/1/indexes/{index}/query"
    headers = {
        "X-Algolia-Application-Id": app_id,
        "X-Algolia-API-Key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": MEDIA_USER_AGENT,
    }
    body = {"params": f"query={requests.utils.quote(query)}&hitsPerPage=10"}
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=12)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.debug("rt algolia search failed: %s", exc)
        return []

    hits = data.get("hits") or []
    results: list[dict[str, Any]] = []
    for hit in hits:
        title = hit.get("title") or hit.get("name")
        url_path = hit.get("url") or hit.get("urlPath") or ""
        if not title:
            continue
        results.append({"title": str(title), "url": str(url_path)})
        if len(results) >= 10:
            break
    return results
