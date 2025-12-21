"""Pirate Bay scraping helpers for top/search lists."""

from __future__ import annotations

import html
import os
import re
from typing import Iterable

import requests

BASE_URL = os.environ.get("TPB_BASE_URL", "https://thepiratebay.org").rstrip("/")

CATEGORY_ALIASES: dict[str, int] = {
    "audio": 100,
    "music": 100,
    "video": 200,
    "movies": 200,
    "tv": 200,
    "apps": 300,
    "applications": 300,
    "software": 300,
    "games": 400,
    "porn": 500,
    "adult": 500,
    "other": 600,
}

_ROW_RE = re.compile(r"<tr[^>]*>.*?</tr>", re.IGNORECASE | re.DOTALL)
_MAGNET_RE = re.compile(r'href="(magnet:\?[^"]+)"', re.IGNORECASE)
_NAME_RE = re.compile(r'class="detLink"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
_RIGHT_TD_RE = re.compile(r'<td[^>]*align="right"[^>]*>(\d+)</td>', re.IGNORECASE)


def category_help() -> str:
    return "audio, video, apps, games, porn, other"


def resolve_category(value: str | None) -> int | None:
    if not value:
        return None
    token = value.strip().lower()
    if not token:
        return None
    if token.isdigit():
        return int(token)
    return CATEGORY_ALIASES.get(token)


def _fetch(url: str) -> str:
    headers = {
        "User-Agent": "tele-home-supervisor/1.0",
        "Accept": "text/html",
    }
    resp = requests.get(url, headers=headers, timeout=12)
    resp.raise_for_status()
    return resp.text


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


def top(category: str | None) -> list[dict[str, object]]:
    cat = resolve_category(category)
    if cat is None:
        url = f"{BASE_URL}/top/0"
    else:
        url = f"{BASE_URL}/top/{cat}"
    html_text = _fetch(url)
    return _top_n(_parse_rows(html_text), 10)


def search(query: str) -> list[dict[str, object]]:
    q = (query or "").strip()
    if not q:
        return []
    q_escaped = requests.utils.quote(q, safe="")
    url = f"{BASE_URL}/search/{q_escaped}/0/99/0"
    html_text = _fetch(url)
    return _top_n(_parse_rows(html_text), 10)
