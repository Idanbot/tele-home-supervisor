from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from tele_home_supervisor import release_monitor
from tele_home_supervisor.models.release_watch import ReleaseWatch


def _watch(kind: str = "movie", quality: str | None = "1080p") -> ReleaseWatch:
    return ReleaseWatch(
        id="abc123",
        chat_id=1,
        kind=kind,
        query="Example",
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


@pytest.mark.asyncio
async def test_check_watch_and_format(monkeypatch) -> None:
    monkeypatch.setattr(
        release_monitor.services,
        "piratebay_search",
        AsyncMock(
            return_value=[{"name": "Example 2160p", "seeders": 4, "leechers": 1}]
        ),
    )
    watch = _watch()

    match = await release_monitor.check_watch(watch)
    assert match is not None
    text = release_monitor.format_match(watch, match)
    assert "Release found" in text
    assert "2160p" in text
    assert "thepiratebay.org" in text
    assert "now disabled" in text
