from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from tele_home_supervisor import scheduled


class FakeResponse:
    def __init__(self, data, status_code: int = 200) -> None:
        self._data = data
        self.status_code = status_code

    def json(self):
        return self._data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def game_offer(title: str, *, active: bool = True, upcoming: bool = False):
    now = datetime.now(UTC)
    offer = {
        "startDate": (now - timedelta(days=1)).isoformat().replace("+00:00", "Z"),
        "endDate": (now + timedelta(days=1)).isoformat().replace("+00:00", "Z"),
        "discountSetting": {"discountPercentage": 0},
    }
    upcoming_offer = {
        "startDate": (now + timedelta(days=7)).isoformat().replace("+00:00", "Z"),
        "endDate": (now + timedelta(days=8)).isoformat().replace("+00:00", "Z"),
        "discountSetting": {"discountPercentage": 0},
    }
    return {
        "title": title,
        "description": "A" * 180,
        "keyImages": [{"type": "Thumbnail", "url": "https://img.example/game.jpg"}],
        "promotions": {
            "promotionalOffers": [
                {
                    "promotionalOffers": [
                        offer
                        if active
                        else {**offer, "discountSetting": {"discountPercentage": 50}}
                    ]
                }
            ],
            "upcomingPromotionalOffers": [
                {
                    "promotionalOffers": [
                        upcoming_offer
                        if upcoming
                        else {
                            **upcoming_offer,
                            "discountSetting": {"discountPercentage": 50},
                        }
                    ]
                }
            ],
        },
    }


@pytest.mark.asyncio
async def test_cached_fetch_uses_backoff_and_cached_value():
    async with scheduled._cache_lock:
        scheduled._cache.clear()

    calls = 0

    async def fetcher():
        nonlocal calls
        calls += 1
        if calls == 1:
            return "good"
        return "❌ broken"

    assert await scheduled._cached_fetch("key", 0, fetcher) == "good"
    assert await scheduled._cached_fetch("key", 0, fetcher) == "good"
    assert calls == 2


def test_offer_helpers_cover_active_upcoming_and_invalid_dates():
    now = datetime.now(UTC)
    active_game = game_offer("Active")
    upcoming_game = game_offer("Soon", active=False, upcoming=True)
    no_offer_game = {"promotions": {}}

    assert scheduled._is_active_free_offer(active_game, now)[0] is True
    assert scheduled._find_upcoming_free_offer(upcoming_game, now)[0] is not None
    assert scheduled._is_active_free_offer(no_offer_game, now)[0] is False
    assert scheduled._find_upcoming_free_offer(no_offer_game, now) == (None, None)
    assert scheduled._fmt_dt(None) == "unknown"
    assert "UTC" in scheduled._fmt_dt(now)


@pytest.mark.asyncio
async def test_fetch_epic_free_games_uncached_formats_active_and_upcoming(monkeypatch):
    client = MagicMock()
    client.get = AsyncMock(
        return_value=FakeResponse(
            {
                "data": {
                    "Catalog": {
                        "searchStore": {
                            "elements": [
                                game_offer("Free Game", active=True),
                                game_offer("Next Game", active=False, upcoming=True),
                            ]
                        }
                    }
                }
            }
        )
    )
    monkeypatch.setattr(scheduled, "_get_client", lambda: client)

    message, images = await scheduled._fetch_epic_free_games_uncached()

    assert "Free Game" in message
    assert "Coming Soon" in message
    assert images == ["https://img.example/game.jpg"]


@pytest.mark.asyncio
async def test_fetch_steam_gog_and_humble_uncached(monkeypatch):
    client = MagicMock()

    async def fake_get(url, **kwargs):
        if "steampowered" in url:
            return FakeResponse(
                {
                    "specials": {
                        "items": [
                            {
                                "name": "Steam Free",
                                "id": 10,
                                "price": {
                                    "initial": 100,
                                    "final": 0,
                                    "discount_percent": 100,
                                },
                                "small_capsule_image": "https://img.example/steam.jpg",
                            }
                        ]
                    }
                }
            )
        if "gog.com" in url:
            return FakeResponse(
                {
                    "products": [
                        {
                            "title": "GOG Free",
                            "slug": "gog_free",
                            "image": "//img.example/gog.jpg",
                            "price": {"isFree": True},
                        }
                    ]
                }
            )
        return FakeResponse(
            {
                "results": [
                    {
                        "human_name": "Humble Free",
                        "human_url": "humble-free",
                        "icon": "/humble.jpg",
                        "current_price": {"amount": 0},
                    }
                ]
            }
        )

    client.get = AsyncMock(side_effect=fake_get)
    monkeypatch.setattr(scheduled, "_get_client", lambda: client)

    steam_msg, steam_images = await scheduled._fetch_steam_free_games_uncached(5)
    gog_msg, gog_images = await scheduled._fetch_gog_free_games_uncached()
    humble_msg, humble_images = await scheduled._fetch_humble_free_games_uncached()

    assert "Steam Free" in steam_msg
    assert steam_images == ["https://img.example/steam.jpg"]
    assert "GOG Free" in gog_msg
    assert gog_images == ["https://img.example/gog.jpg"]
    assert "Humble Free" in humble_msg
    assert humble_images == ["https://hb.imgix.net/humble.jpg"]


@pytest.mark.asyncio
async def test_humble_fallback_lookup(monkeypatch):
    client = MagicMock()
    responses = [
        FakeResponse({"results": []}),
        FakeResponse(
            {
                "mosaic": {
                    "human_name": "Fallback Free",
                    "human_url": "fallback",
                    "icon": "https://img.example/fallback.jpg",
                    "current_price": {"amount": 0},
                }
            }
        ),
    ]
    client.get = AsyncMock(side_effect=responses)
    monkeypatch.setattr(scheduled, "_get_client", lambda: client)

    message, images = await scheduled._fetch_humble_free_games_uncached()

    assert "Fallback Free" in message
    assert images == ["https://img.example/fallback.jpg"]


@pytest.mark.asyncio
async def test_fetchers_return_error_messages(monkeypatch):
    client = MagicMock()
    client.get = AsyncMock(side_effect=RuntimeError("offline"))
    monkeypatch.setattr(scheduled, "_get_client", lambda: client)
    monkeypatch.setattr(scheduled.asyncio, "sleep", AsyncMock())

    assert (await scheduled._fetch_epic_free_games_uncached())[0].startswith("❌")
    assert (await scheduled.fetch_hackernews_top(limit=1)).startswith("❌")
    assert (await scheduled._fetch_steam_free_games_uncached(1))[0].startswith("❌")
    assert (await scheduled._fetch_gog_free_games_uncached())[0].startswith("❌")
    assert (await scheduled._fetch_humble_free_games_uncached())[0].startswith("❌")
