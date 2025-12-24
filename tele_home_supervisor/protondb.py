"""ProtonDB and Steam API helpers for game compatibility lookup."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, TypedDict
from urllib.parse import quote

import requests

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

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_TIMEOUT = int(os.environ.get("PROTONDB_TIMEOUT", "12"))
_MAX_RETRIES = int(os.environ.get("PROTONDB_MAX_RETRIES", "2"))
_RETRY_DELAY = float(os.environ.get("PROTONDB_RETRY_DELAY", "0.5"))


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


def _request_with_retry(
    url: str,
    headers: dict[str, str],
    max_retries: int = _MAX_RETRIES,
) -> requests.Response:
    """Make HTTP GET request with retry logic for transient failures."""
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=_TIMEOUT)
            # Retry on 5xx errors
            if resp.status_code >= 500 and attempt < max_retries:
                time.sleep(_RETRY_DELAY * (attempt + 1))
                continue
            return resp
        except requests.exceptions.Timeout as e:
            last_error = e
            if attempt < max_retries:
                time.sleep(_RETRY_DELAY * (attempt + 1))
                continue
            raise
        except requests.exceptions.ConnectionError as e:
            last_error = e
            if attempt < max_retries:
                time.sleep(_RETRY_DELAY * (attempt + 1))
                continue
            raise
    # Should not reach here, but just in case
    if last_error:
        raise last_error
    raise RuntimeError("Request failed after retries")


def search_steam_games(query: str) -> list[SteamGame]:
    """Search Steam games by name.

    Args:
        query: Game name to search for.

    Returns:
        List of games with appid, name, icon, logo.

    Raises:
        RuntimeError: If Steam search API returns an error.
    """
    url = f"https://steamcommunity.com/actions/SearchApps/{quote(query)}"
    headers = {"User-Agent": _USER_AGENT, "Accept": "application/json"}
    resp = _request_with_retry(url, headers)
    if not resp.ok:
        raise RuntimeError(f"Steam search failed: HTTP {resp.status_code}")
    data = resp.json()
    if not isinstance(data, list):
        return []
    return data[:10]  # Limit to 10 results


def get_protondb_summary(appid: int | str) -> ProtonDBSummary | None:
    """Get ProtonDB compatibility summary for a game.

    Args:
        appid: Steam app ID.

    Returns:
        Summary with tier, confidence, score, etc. None if not found.
    """
    url = f"https://www.protondb.com/api/v1/reports/summaries/{appid}.json"
    headers = {"User-Agent": _USER_AGENT, "Accept": "application/json"}
    try:
        resp = _request_with_retry(url, headers)
        if resp.status_code == 404:
            return None
        if not resp.ok:
            logger.debug("ProtonDB API error: HTTP %d", resp.status_code)
            return None
        return resp.json()
    except Exception as e:
        logger.debug("ProtonDB fetch failed: %s", e)
        return None


def get_steam_app_details(appid: int | str) -> SteamAppDetails | None:
    """Get Steam app details including images, description, metacritic.

    Args:
        appid: Steam app ID.

    Returns:
        App details dict or None if not found.
    """
    url = f"https://store.steampowered.com/api/appdetails?appids={appid}"
    headers = {"User-Agent": _USER_AGENT, "Accept": "application/json"}
    try:
        resp = _request_with_retry(url, headers)
        if not resp.ok:
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


def get_steam_player_count(appid: int | str) -> int | None:
    """Get current player count for a Steam game.

    Args:
        appid: Steam app ID.

    Returns:
        Current player count or None if unavailable.
    """
    url = f"https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid={appid}"
    headers = {"User-Agent": _USER_AGENT, "Accept": "application/json"}
    try:
        resp = _request_with_retry(url, headers)
        if not resp.ok:
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
