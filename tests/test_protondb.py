"""Tests for ProtonDB module."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from tele_home_supervisor import protondb


def _mock_client(data: object, status: int = 200):
    response = MagicMock()
    response.status_code = status
    response.is_success = 200 <= status < 300
    response.json.return_value = data
    client = MagicMock()
    client.get = AsyncMock(return_value=response)
    return client


def test_format_tier_known_tiers() -> None:
    assert protondb.format_tier("platinum") == "Platinum"
    assert protondb.format_tier("gold") == "Gold"
    assert protondb.format_tier("silver") == "Silver"
    assert protondb.format_tier("bronze") == "Bronze"
    assert protondb.format_tier("borked") == "Borked"
    assert protondb.format_tier("native") == "Native"
    assert protondb.format_tier("pending") == "Pending"


def test_format_tier_unknown() -> None:
    assert protondb.format_tier("unknown") == "Unknown"
    assert protondb.format_tier(None) == "Unknown"


def test_tier_emoji_known_tiers() -> None:
    assert protondb.tier_emoji("platinum") == "\U0001f3c6"  # trophy
    assert protondb.tier_emoji("gold") == "\U0001f947"  # 1st place
    assert protondb.tier_emoji("borked") == "\U0001f6ab"  # no entry
    assert protondb.tier_emoji("native") == "\U0001f427"  # penguin


def test_tier_emoji_unknown() -> None:
    assert protondb.tier_emoji("unknown") == ""
    assert protondb.tier_emoji(None) == ""


@pytest.mark.asyncio
async def test_search_steam_games_success(monkeypatch) -> None:
    fake_data = [
        {"appid": "123", "name": "Test Game", "icon": "http://example.com/icon.jpg"},
        {
            "appid": "456",
            "name": "Another Game",
            "icon": "http://example.com/icon2.jpg",
        },
    ]

    monkeypatch.setattr(protondb, "_get_client", lambda: _mock_client(fake_data))

    results = await protondb.search_steam_games("test")
    assert len(results) == 2
    assert results[0]["appid"] == "123"
    assert results[0]["name"] == "Test Game"


@pytest.mark.asyncio
async def test_search_steam_games_limits_results(monkeypatch) -> None:
    fake_data = [{"appid": str(i), "name": f"Game {i}"} for i in range(20)]

    monkeypatch.setattr(protondb, "_get_client", lambda: _mock_client(fake_data))

    results = await protondb.search_steam_games("game")
    assert len(results) == 10  # Limited to 10


@pytest.mark.asyncio
async def test_search_steam_games_http_error(monkeypatch) -> None:
    monkeypatch.setattr(protondb, "_get_client", lambda: _mock_client({}, status=500))

    results = await protondb.search_steam_games("test")
    assert results == []


@pytest.mark.asyncio
async def test_get_protondb_summary_success(monkeypatch) -> None:
    fake_data = {
        "tier": "gold",
        "confidence": "strong",
        "score": 0.77,
        "total": 100,
        "trendingTier": "platinum",
    }

    monkeypatch.setattr(protondb, "_get_client", lambda: _mock_client(fake_data))

    result = await protondb.get_protondb_summary(123456)
    assert result["tier"] == "gold"
    assert result["total"] == 100


@pytest.mark.asyncio
async def test_get_protondb_summary_not_found(monkeypatch) -> None:
    monkeypatch.setattr(protondb, "_get_client", lambda: _mock_client({}, status=404))

    result = await protondb.get_protondb_summary(999999)
    assert result is None


@pytest.mark.asyncio
async def test_get_steam_player_count_success(monkeypatch) -> None:
    fake_data = {"response": {"result": 1, "player_count": 50000}}

    monkeypatch.setattr(protondb, "_get_client", lambda: _mock_client(fake_data))

    count = await protondb.get_steam_player_count(123456)
    assert count == 50000


@pytest.mark.asyncio
async def test_get_steam_player_count_no_data(monkeypatch) -> None:
    fake_data = {"response": {"result": 42}}  # result != 1 means no data

    monkeypatch.setattr(protondb, "_get_client", lambda: _mock_client(fake_data))

    count = await protondb.get_steam_player_count(123456)
    assert count is None
