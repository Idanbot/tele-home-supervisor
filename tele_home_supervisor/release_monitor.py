"""Daily one-shot release availability checks."""

from __future__ import annotations

import html
import re
from urllib.parse import quote_plus

from . import services
from .models.release_watch import VIDEO_QUALITIES, ReleaseWatch

_QUALITY_RANK = {quality: index for index, quality in enumerate(VIDEO_QUALITIES)}
_QUALITY_PATTERNS = (
    ("2160p", re.compile(r"\b(?:2160p|4k|uhd)\b", re.IGNORECASE)),
    ("1440p", re.compile(r"\b1440p\b", re.IGNORECASE)),
    ("1080p", re.compile(r"\b1080[pi]\b", re.IGNORECASE)),
    ("720p", re.compile(r"\b720[pi]\b", re.IGNORECASE)),
    ("480p", re.compile(r"\b(?:480[pi]|dvdrip)\b", re.IGNORECASE)),
)
_REJECTED_SOURCE_TOKENS = {
    "cam",
    "camrip",
    "camts",
    "hdcam",
    "hqcam",
    "ts",
    "hdts",
    "telesync",
    "tc",
    "hdtc",
    "telecine",
    "scr",
    "screener",
    "dvdscr",
    "dvdscreener",
    "workprint",
    "wp",
}
_REJECTED_TITLE_PATTERNS = (
    re.compile(r"\bxxx\b"),
    re.compile(r"\bporn\b"),
    re.compile(r"\bmaking\s+of\b"),
    re.compile(r"\bbehind\s+the\s+scenes\b"),
    re.compile(r"\bsoundtrack\b"),
    re.compile(r"\bfeaturette\b"),
    re.compile(r"\btrailer\b"),
)


def detect_video_quality(name: str) -> str | None:
    for quality, pattern in _QUALITY_PATTERNS:
        if pattern.search(name):
            return quality
    return None


def _normalized_words(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", value.lower())


def _matches_query(query: str, name: str) -> bool:
    query_words = _normalized_words(query)
    name_words = set(_normalized_words(name))
    return bool(query_words) and all(word in name_words for word in query_words)


def _is_rejected_release(name: str) -> bool:
    normalized = " ".join(_normalized_words(name))
    words = set(normalized.split())
    return bool(words & _REJECTED_SOURCE_TOKENS) or any(
        pattern.search(normalized) for pattern in _REJECTED_TITLE_PATTERNS
    )


def select_match(
    watch: ReleaseWatch, results: list[dict[str, object]]
) -> dict[str, object] | None:
    accepted = []
    for result in results:
        name = str(result.get("name") or "")
        if not _matches_query(watch.query, name) or _is_rejected_release(name):
            continue
        quality = detect_video_quality(name)
        if watch.kind != "game":
            if quality is None or watch.min_quality is None:
                continue
            if _QUALITY_RANK[quality] < _QUALITY_RANK[watch.min_quality]:
                continue
        item = dict(result)
        item["quality"] = quality
        accepted.append(item)

    if not accepted:
        return None
    return max(accepted, key=lambda item: int(item.get("seeders") or 0))


async def check_watch(watch: ReleaseWatch) -> dict[str, object] | None:
    results = await services.piratebay_site_search(watch.query)
    return select_match(watch, results)


def format_match(watch: ReleaseWatch, match: dict[str, object]) -> str:
    name = html.escape(str(match.get("name") or watch.query))
    quality = match.get("quality")
    quality_text = f" · {html.escape(str(quality))}" if quality else ""
    seeders = int(match.get("seeders") or 0)
    leechers = int(match.get("leechers") or 0)
    search_url = "https://thepiratebay.org/search.php?q=" + quote_plus(watch.query)
    return (
        "🔔 <b>Release found</b>\n"
        f"<b>{name}</b>\n"
        f"{watch.kind.title()}{quality_text} · ↑ {seeders} · ↓ {leechers}\n"
        f'<a href="{html.escape(search_url, quote=True)}">Open Pirate Bay search</a>\n'
        "This one-shot watch is now disabled."
    )
