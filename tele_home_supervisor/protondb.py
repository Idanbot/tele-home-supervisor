"""ProtonDB and Steam API helpers for game compatibility lookup."""

from __future__ import annotations

import logging
from typing import Any, TypedDict
from urllib.parse import quote

import httpx

__all__ = [
    "search_steam_games",
    "get_protondb_summary",
    "get_steam_app_details",
    "get_steam_player_count",
    "format_tier",
    "tier_emoji",
    "TIER_INFO",
]

logger = logging.getLogger(__name__)

_CLIENT: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = httpx.AsyncClient(
            timeout=httpx.Timeout(12.0),
            transport=httpx.AsyncHTTPTransport(retries=2),
        )
    return _CLIENT


_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class SteamGame(TypedDict, total=False):
    """Steam game search result."""

    appid: str
    name: str
    icon: str
    logo: str


class ProtonDBSummary(TypedDict, total=False):
    """ProtonDB compatibility summary."""

    tier: str
    bestReportedTier: str
    confidence: str
    score: float
    total: int
    trendingTier: str


class SteamAppDetails(TypedDict, total=False):
    """Steam app details (partial)."""

    name: str
    steam_appid: int
    header_image: str
    metacritic: dict[str, Any]
    release_date: dict[str, Any]
    genres: list[dict[str, str]]


async def search_steam_games(query: str) -> list[SteamGame]:
    """Search Steam games by name.

    Args:
        query: Game name to search for.

    Returns:
        List of games with appid, name, icon, logo.
    """
    url = f"https://steamcommunity.com/actions/SearchApps/{quote(query)}"
    headers = {"User-Agent": _USER_AGENT, "Accept": "application/json"}
    client = _get_client()
    try:
        resp = await client.get(url, headers=headers)
        if resp.is_success:
            data = resp.json()
            if isinstance(data, list):
                return data[:10]
        else:
            logger.debug("Steam search failed: HTTP %d", resp.status_code)
    except Exception as exc:
        logger.debug("Steam community search failed: %s", exc)
    return await _search_steam_store(query)


async def _search_steam_store(query: str) -> list[SteamGame]:
    """Fallback search via Steam Store API."""
    url = "https://store.steampowered.com/api/storesearch"
    params = {"term": query, "l": "english", "cc": "us"}
    headers = {"User-Agent": _USER_AGENT, "Accept": "application/json"}
    client = _get_client()
    data = None
    try:
        resp = await client.get(url, headers=headers, params=params)
        if resp.is_success:
            data = resp.json()
        else:
            logger.debug("Steam store search failed: HTTP %d", resp.status_code)
    except Exception as exc:
        logger.debug("Steam store search failed: %s", exc)

    items = data.get("items") if isinstance(data, dict) else None
    if not items:
        try:
            resp = await client.get(url, headers=headers, params=params)
            if resp.is_success:
                data = resp.json()
            else:
                logger.debug(
                    "Steam store relaxed search failed: HTTP %d", resp.status_code
                )
                return []
        except Exception as exc:
            logger.debug("Steam store relaxed search failed: %s", exc)
            return []

    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    results: list[SteamGame] = []
    for item in items[:10]:
        if not isinstance(item, dict):
            continue
        appid = item.get("id")
        name = item.get("name")
        if not appid or not name:
            continue
        results.append(
            {
                "appid": str(appid),
                "name": str(name),
                "icon": str(item.get("tiny_image") or ""),
            }
        )
    return results


async def get_protondb_summary(appid: int | str) -> ProtonDBSummary | None:
    """Get ProtonDB compatibility summary for a game.

    Args:
        appid: Steam app ID.

    Returns:
        Summary with tier, confidence, score, etc. None if not found.
    """
    url = f"https://www.protondb.com/api/v1/reports/summaries/{appid}.json"
    headers = {"User-Agent": _USER_AGENT, "Accept": "application/json"}
    client = _get_client()
    try:
        resp = await client.get(url, headers=headers)
        if resp.status_code == 404:
            return None
        if not resp.is_success:
            logger.debug("ProtonDB API error: HTTP %d", resp.status_code)
            return None
        return resp.json()
    except Exception as e:
        logger.debug("ProtonDB fetch failed: %s", e)
        return None


async def get_steam_app_details(appid: int | str) -> SteamAppDetails | None:
    """Get Steam app details including images, description, metacritic.

    Args:
        appid: Steam app ID.

    Returns:
        App details dict or None if not found.
    """
    url = f"https://store.steampowered.com/api/appdetails?appids={appid}"
    headers = {"User-Agent": _USER_AGENT, "Accept": "application/json"}
    client = _get_client()
    try:
        resp = await client.get(url, headers=headers)
        if not resp.is_success:
            logger.debug("Steam appdetails error: HTTP %d", resp.status_code)
            return None
        data = resp.json()
        app_data = data.get(str(appid), {})
        if not app_data.get("success"):
            return None
        return app_data.get("data")
    except Exception as e:
        logger.debug("Steam appdetails fetch failed: %s", e)
        return None


async def get_steam_player_count(appid: int | str) -> int | None:
    """Get current player count for a Steam game.

    Args:
        appid: Steam app ID.

    Returns:
        Current player count or None if unavailable.
    """
    url = f"https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid={appid}"
    headers = {"User-Agent": _USER_AGENT, "Accept": "application/json"}
    client = _get_client()
    try:
        resp = await client.get(url, headers=headers)
        if not resp.is_success:
            return None
        data = resp.json()
        response = data.get("response", {})
        if response.get("result") != 1:
            return None
        return response.get("player_count")
    except Exception as e:
        logger.debug("Steam player count fetch failed: %s", e)
        return None


# Tier display info with colors/emojis
TIER_INFO = {
    "native": ("Native", "penguin"),
    "platinum": ("Platinum", "trophy"),
    "gold": ("Gold", "1st_place_medal"),
    "silver": ("Silver", "2nd_place_medal"),
    "bronze": ("Bronze", "3rd_place_medal"),
    "borked": ("Borked", "no_entry"),
    "pending": ("Pending", "hourglass_flowing_sand"),
}


def format_tier(tier: str | None) -> str:
    """Format tier with emoji."""
    if not tier:
        return "Unknown"
    tier_lower = tier.lower()
    if tier_lower in TIER_INFO:
        label, _ = TIER_INFO[tier_lower]
        return label
    return tier.capitalize()


def tier_emoji(tier: str | None) -> str:
    """Get emoji for tier."""
    if not tier:
        return ""
    tier_lower = tier.lower()
    emojis = {
        "native": "\U0001f427",  # penguin
        "platinum": "\U0001f3c6",  # trophy
        "gold": "\U0001f947",  # 1st place medal
        "silver": "\U0001f948",  # 2nd place medal
        "bronze": "\U0001f949",  # 3rd place medal
        "borked": "\U0001f6ab",  # no entry
        "pending": "\u23f3",  # hourglass
    }
    return emojis.get(tier_lower, "")
