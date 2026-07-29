from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from tele_home_supervisor import release_monitor
from tele_home_supervisor.models.release_watch import ReleaseWatch


def _watch(
    kind: str = "movie",
    quality: str | None = "1080p",
    query: str = "Example",
) -> ReleaseWatch:
    return ReleaseWatch(
        id="abc123",
        chat_id=1,
        kind=kind,
        query=query,
        min_quality=quality,
        enabled=True,
        created_at=1.0,
    )


def test_detect_video_quality_and_minimum_filter() -> None:
    assert release_monitor.detect_video_quality("Film.4K.UHD.WEB") == "2160p"
    assert release_monitor.detect_video_quality("Film.1080p.BluRay") == "1080p"
    assert release_monitor.detect_video_quality("Film.DVDRip") == "480p"
    assert release_monitor.detect_video_quality("Film unknown") is None

    result = release_monitor.select_match(
        _watch(),
        [
            {"name": "Example 720p", "seeders": 500},
            {"name": "Example unknown", "seeders": 400},
            {"name": "Example 1080p", "seeders": 20},
            {"name": "Example 2160p", "seeders": 10},
        ],
    )
    assert result is not None
    assert result["name"] == "Example 1080p"
    assert result["quality"] == "1080p"


def test_game_match_does_not_require_video_quality() -> None:
    result = release_monitor.select_match(
        _watch("game", None),
        [
            {"name": "Example PC", "seeders": 2},
            {"name": "Example Deluxe", "seeders": 5},
        ],
    )
    assert result is not None
    assert result["name"] == "Example Deluxe"


@pytest.mark.parametrize(
    "name",
    [
        "The.Odyssey.2026.2160p.TELESYNC.HEVC-SPLiCE",
        "The Odyssey 2026 2160p TS x265",
        "The.Odyssey.2026.2160p.HDTS.x265-MAZE",
        "The Odyssey 2026 4K HDCAM",
        "The.Odyssey.2026.2160p.CAMRip",
        "The Odyssey 2026 2160p TELECINE",
        "The.Odyssey.2026.2160p.DVDSCR",
    ],
)
def test_rejects_low_quality_release_sources(name: str) -> None:
    watch = _watch(quality="2160p", query="The Odyssey (2026)")

    assert release_monitor.select_match(watch, [{"name": name, "seeders": 50}]) is None


def test_rejects_unrelated_and_supplemental_movie_results() -> None:
    watch = _watch(quality="1080p", query="The Odyssey (2026)")
    results = [
        {"name": "The Odyssey XXX Part 1 2026 WEB-DL 2160p", "seeders": 50},
        {
            "name": "The Odyssey The Making Of An Epic 2026 2160p WEBRip",
            "seeders": 40,
        },
        {"name": "Odyssey Soundtrack 2026 FLAC 2160p", "seeders": 30},
        {"name": "A Different Odyssey 2026 2160p WEBRip", "seeders": 20},
    ]

    assert release_monitor.select_match(watch, results) is None


def test_odyssey_live_page_results_do_not_trigger_2160p_watch() -> None:
    watch = _watch(quality="2160p", query="The Odyssey (2026)")
    results = [
        {
            "name": "The.Odyssey.2026.1080p.TELESYNC.HEVC.AAC2.0-SPLiCE",
            "seeders": 7270,
        },
        {
            "name": "The Odyssey XXX Part 1 (Cosplayground) 2026 WEB-DL 720p",
            "seeders": 140,
        },
        {
            "name": "The Odyssey (2026) 1080P HQ HDTS x265 AAC2.0 MULTI",
            "seeders": 46,
        },
        {
            "name": "The Odyssey The Making Of An Epic (2026) 1080p WEBRip",
            "seeders": 10,
        },
        {
            "name": "Ludwig Goransson - The Odyssey Soundtrack 2026 FLAC",
            "seeders": 6,
        },
    ]

    assert release_monitor.select_match(watch, results) is None


@pytest.mark.asyncio
async def test_check_watch_and_format(monkeypatch) -> None:
    general_search = AsyncMock(
        side_effect=AssertionError("fallback search must not run")
    )
    monkeypatch.setattr(
        release_monitor.services,
        "piratebay_search",
        general_search,
    )
    monkeypatch.setattr(
        release_monitor.services,
        "piratebay_site_search",
        AsyncMock(
            return_value=[{"name": "Example 2160p", "seeders": 4, "leechers": 1}]
        ),
        raising=False,
    )
    watch = _watch()

    match = await release_monitor.check_watch(watch)
    general_search.assert_not_awaited()
    assert match is not None
    text = release_monitor.format_match(watch, match)
    assert "Release found" in text
    assert "2160p" in text
    assert "thepiratebay.org" in text
    assert "now disabled" in text
