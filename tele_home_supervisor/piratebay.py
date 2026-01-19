"""Pirate Bay scraping helpers for top/search lists."""

from __future__ import annotations

import html
import logging
import os
import re
from typing import Iterable

import requests

logger = logging.getLogger(__name__)
BASE_URL = os.environ.get("TPB_BASE_URL", "https://thepiratebay.org").rstrip("/")
TPB_API_BASE_URL = os.environ.get("TPB_API_BASE_URL", "https://apibay.org").rstrip("/")
TPB_API_BASE_URLS = os.environ.get("TPB_API_BASE_URLS", "")
TPB_USER_AGENT = os.environ.get(
    "TPB_USER_AGENT",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
)
TPB_COOKIE = os.environ.get("TPB_COOKIE", "")
TPB_REFERER = os.environ.get("TPB_REFERER", "")

CATEGORY_ALIASES: dict[str, int] = {
    "audio": 101,
    "music": 101,
    "flac": 104,
    "video": 200,
    "movies": 200,
    "tv": 200,
    "hdmovies": 207,
    "hdtv": 208,
    "4kmovies": 211,
    "4ktv": 212,
    "apps": 300,
    "applications": 300,
    "software": 300,
    "games": 400,
    "porn": 500,
    "adult": 500,
    "ebook": 601,
    "other": 600,
}
TOP_MODES: dict[str, str] = {
    "top": "top100",
    "top100": "top100",
    "top48": "top48h",
    "top48h": "top48h",
    "48h": "top48h",
    "top100:48h": "top48h",
}

_ROW_RE = re.compile(r"<tr[^>]*>.*?</tr>", re.IGNORECASE | re.DOTALL)
_MAGNET_RE = re.compile(r'href="(magnet:\?[^"]+)"', re.IGNORECASE)
_NAME_RE = re.compile(r'class="detLink"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
_RIGHT_TD_RE = re.compile(r'<td[^>]*align="right"[^>]*>(\d+)</td>', re.IGNORECASE)
_NO_RESULTS_RE = re.compile(
    r"no results returned|no matches found|no results", re.IGNORECASE
)

_TRACKERS = [
    "udp://tracker.openbittorrent.com:80/announce",
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.stealth.si:80/announce",
]
_NO_RESULTS_RE = re.compile(
    r"no results returned|no matches found|no results", re.IGNORECASE
)


def category_help() -> str:
    return (
        "audio, music, flac, video, hdmovies, hdtv, 4kmovies, 4ktv, apps, "
        "games, porn, ebook, other, top, top48h"
    )


def resolve_category(value: str | None) -> int | None:
    if not value:
        return None
    token = value.strip().lower()
    if not token:
        return None
    if token.isdigit():
        return int(token)
    return CATEGORY_ALIASES.get(token)


def resolve_top_mode(value: str | None) -> str | None:
    if value is None:
        return "top100"
    token = value.strip().lower()
    if not token:
        return "top100"
    return TOP_MODES.get(token)


def _fetch(url: str) -> str:
    logger.debug("piratebay fetch html: %s", url)
    headers = {
        "User-Agent": TPB_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
    }
    if TPB_REFERER:
        headers["Referer"] = TPB_REFERER
    if TPB_COOKIE:
        headers["Cookie"] = TPB_COOKIE
    resp = requests.get(url, headers=headers, timeout=12)
    resp.raise_for_status()
    return resp.text


def _fetch_json(url: str) -> list[dict[str, object]]:
    logger.debug("piratebay fetch json: %s", url)
    headers = {
        "User-Agent": TPB_USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    resp = requests.get(url, headers=headers, timeout=12)
    if not resp.ok:
        snippet = resp.text[:500].replace("\n", " ")
        raise RuntimeError(f"Pirate Bay API {resp.status_code} for {url}: {snippet}")
    try:
        data = resp.json()
    except ValueError as exc:
        snippet = resp.text[:500].replace("\n", " ")
        raise RuntimeError(f"Pirate Bay API invalid JSON for {url}: {snippet}") from exc
    if isinstance(data, list):
        return data
    return []


def _ensure_not_blocked(html_text: str) -> None:
    markers = (
        "cf-chl",
        "cloudflare",
        "just a moment",
        "attention required",
        "captcha",
        "access denied",
        "enable javascript",
        "please enable",
    )
    lower = html_text.lower()
    if any(marker in lower for marker in markers):
        raise RuntimeError("Pirate Bay blocked by anti-bot protection")


def _is_no_results(html_text: str) -> bool:
    return bool(_NO_RESULTS_RE.search(html_text))


def _parse_rows(html_text: str) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for row in _ROW_RE.findall(html_text):
        magnet_match = _MAGNET_RE.search(row)
        name_match = _NAME_RE.search(row)
        nums = _RIGHT_TD_RE.findall(row)
        if not magnet_match or not name_match or len(nums) < 2:
            continue
        magnet = html.unescape(magnet_match.group(1))
        name = html.unescape(name_match.group(1)).strip()
        if not magnet or not name:
            continue
        try:
            seeders = int(nums[-2])
            leechers = int(nums[-1])
        except ValueError:
            continue
        results.append(
            {
                "name": name,
                "magnet": magnet,
                "seeders": seeders,
                "leechers": leechers,
            }
        )
    return results


def _top_n(
    results: Iterable[dict[str, object]], n: int = 10
) -> list[dict[str, object]]:
    return sorted(results, key=lambda r: int(r.get("seeders", 0)), reverse=True)[:n]


def _magnet_from_hash(info_hash: str, name: str) -> str:
    dn = requests.utils.quote(name, safe="")
    trackers = "".join(f"&tr={requests.utils.quote(t, safe='')}" for t in _TRACKERS)
    return f"magnet:?xt=urn:btih:{info_hash}&dn={dn}{trackers}"


def _api_to_results(items: list[dict[str, object]]) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        info_hash = str(item.get("info_hash") or "").strip()
        if not name or not info_hash:
            continue
        try:
            seeders = int(item.get("seeders") or 0)
            leechers = int(item.get("leechers") or 0)
        except ValueError:
            continue
        results.append(
            {
                "name": name,
                "magnet": _magnet_from_hash(info_hash, name),
                "seeders": seeders,
                "leechers": leechers,
            }
        )
    return results


def _api_top(category: str | None, debug_sink=None) -> list[dict[str, object]]:
    cat = resolve_category(category) or 0
    for base in _api_base_candidates():
        url = f"{base}/precompiled/data_top100_{cat}.json"
        try:
            items = _fetch_json(url)
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            logger.debug("piratebay api top failed for %s: %s", base, exc)
            if debug_sink:
                debug_sink(f"piratebay api top failed for {base}", str(exc))
            continue
        results = _top_n(_api_to_results(items), 10)
        if results:
            return results
    return []


def _api_search(
    query: str, category: str | None = None, debug_sink=None
) -> list[dict[str, object]]:
    q = (query or "").strip()
    if not q:
        return []
    cat = resolve_category(category) or 0
    for base in _api_base_candidates():
        url = f"{base}/q.php?q={requests.utils.quote(q)}&cat={cat}"
        try:
            items = _fetch_json(url)
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            logger.debug("piratebay api search failed for %s: %s", base, exc)
            if debug_sink:
                debug_sink(f"piratebay api search failed for {base}", str(exc))
            continue
        results = _top_n(_api_to_results(items), 10)
        if results:
            return results
    return []


def top(category: str | None, debug_sink=None) -> list[dict[str, object]]:
    top_mode = resolve_top_mode(category)
    if top_mode == "top100":
        url = f"{BASE_URL}/top.php"
    elif top_mode == "top48h":
        url = f"{BASE_URL}/search/top100:48h/0/99/0"
    else:
        cat = resolve_category(category)
        if cat is None:
            url = f"{BASE_URL}/top/0"
        else:
            url = f"{BASE_URL}/top/{cat}"
    try:
        html_text = _fetch(url)
        _ensure_not_blocked(html_text)
        results = _top_n(_parse_rows(html_text), 10)
        if results:
            return results
    except (requests.RequestException, RuntimeError, ValueError) as exc:
        logger.debug("piratebay top html failed: %s", exc)
        if debug_sink:
            debug_sink("piratebay top html failed", str(exc))

    # Try API for non-48h modes
    if top_mode != "top48h":
        if top_mode == "top100":
            results = _api_top(None, debug_sink)
        else:
            results = _api_top(category, debug_sink)
        if results:
            return results

    # Try fallback sources when PirateBay fails
    logger.debug("piratebay top api empty; trying fallback sources")
    from tele_home_supervisor import torrentsources

    fallback_results = torrentsources.fallback_top(category, debug_sink)
    if fallback_results:
        logger.debug("fallback top results: %s", len(fallback_results))
        return [r.to_dict() for r in fallback_results]

    logger.warning("All torrent sources failed for top: %s", category)
    return []  # All sources failed - return empty, don't raise


def search(query: str, debug_sink=None) -> list[dict[str, object]]:
    q = (query or "").strip()
    if not q:
        return []
    q_escaped = requests.utils.quote(q, safe="")
    url = f"{BASE_URL}/search/{q_escaped}/0/99/0"
    try:
        html_text = _fetch(url)
        _ensure_not_blocked(html_text)
        results = _top_n(_parse_rows(html_text), 10)
        if results:
            logger.debug("piratebay search html results: %s", len(results))
            return results
        if _is_no_results(html_text):
            logger.debug("piratebay search html no results")
            return []
        logger.debug("piratebay search html parse empty; falling back to api")
    except Exception as exc:
        logger.debug("piratebay search html failed: %s", exc)
        if debug_sink:
            debug_sink("piratebay search html failed", str(exc))

    results = _api_search(q, debug_sink=debug_sink)
    if results:
        logger.debug("piratebay search api results: %s", len(results))
        return results
    logger.debug("piratebay search api empty; trying fallback sources")

    # Try fallback sources when PirateBay fails
    from tele_home_supervisor import torrentsources

    fallback_results = torrentsources.fallback_search(q, debug_sink)
    if fallback_results:
        logger.debug("fallback search results: %s", len(fallback_results))
        return [r.to_dict() for r in fallback_results]

    logger.warning("All torrent sources failed for search: %s", q)
    return []  # All sources failed - return empty, don't raise


def _api_base_candidates() -> list[str]:
    bases: list[str] = []
    if TPB_API_BASE_URLS:
        for part in TPB_API_BASE_URLS.split(","):
            b = part.strip().rstrip("/")
            if b and b not in bases:
                bases.append(b)
    if TPB_API_BASE_URL and TPB_API_BASE_URL not in bases:
        bases.append(TPB_API_BASE_URL)
    expanded: list[str] = []
    for base in bases:
        expanded.append(base)
        if base.startswith("https://"):
            http_base = "http://" + base[len("https://") :]
            if http_base not in expanded:
                expanded.append(http_base)
    return expanded
