"""Scheduled notification fetchers (Epic Games, Hacker News, GOG, Steam, Humble).

Also provides a combined game offers builder for daily digests.
"""

from __future__ import annotations

import html
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Callable
from urllib.parse import quote_plus

import requests

logger = logging.getLogger(__name__)

_GAME_OFFERS_TTL_S = 24 * 60 * 60
_CACHE_BASE_BACKOFF_S = 15 * 60
_CACHE_MAX_BACKOFF_S = 6 * 60 * 60


@dataclass
class _CacheEntry:
    value: object | None
    fetched_at: float
    error_count: int = 0
    next_retry_at: float = 0.0
    last_error: object | None = None


_cache_lock = Lock()
_cache: dict[str, _CacheEntry] = {}


def _is_error_value(value: object | None) -> bool:
    if isinstance(value, tuple) and value:
        msg = value[0]
    else:
        msg = value
    return isinstance(msg, str) and msg.strip().startswith("❌")


def _cached_fetch(
    key: str,
    ttl_s: float,
    fetcher: Callable[[], object],
) -> object:
    now = time.monotonic()
    with _cache_lock:
        entry = _cache.get(key)
        if entry and entry.value is not None and (now - entry.fetched_at) < ttl_s:
            return entry.value
        if entry and now < entry.next_retry_at:
            return entry.value if entry.value is not None else entry.last_error

    value: object | None = None
    try:
        value = fetcher()
        if _is_error_value(value):
            raise RuntimeError("fetch returned error value")
    except Exception as exc:
        with _cache_lock:
            entry = _cache.get(key)
            error_count = (entry.error_count if entry else 0) + 1
            backoff = min(
                _CACHE_MAX_BACKOFF_S, _CACHE_BASE_BACKOFF_S * (2 ** (error_count - 1))
            )
            next_retry_at = now + backoff
            if entry:
                entry.error_count = error_count
                entry.next_retry_at = next_retry_at
                entry.last_error = value
                _cache[key] = entry
                if entry.value is not None:
                    logger.warning("Using cached %s after fetch error: %s", key, exc)
                    return entry.value
            _cache[key] = _CacheEntry(
                value=None,
                fetched_at=0.0,
                error_count=error_count,
                next_retry_at=next_retry_at,
                last_error=value,
            )
        if value is not None:
            return value
        raise

    with _cache_lock:
        _cache[key] = _CacheEntry(value=value, fetched_at=now)
    return value


def _is_active_free_offer(
    game: dict[str, Any], now: datetime
) -> tuple[bool, datetime | None, datetime | None]:
    """Return (is_active, start, end) for a current free promotional offer."""

    promotions = game.get("promotions") or {}
    current_offers = promotions.get("promotionalOffers") or []

    if not current_offers:
        return (False, None, None)

    offers = current_offers[0].get("promotionalOffers") or []
    for offer in offers:
        start = offer.get("startDate")
        end = offer.get("endDate")
        discount = (offer.get("discountSetting") or {}).get("discountPercentage")

        try:
            start_dt = (
                datetime.fromisoformat(start.replace("Z", "+00:00")) if start else None
            )
            end_dt = datetime.fromisoformat(end.replace("Z", "+00:00")) if end else None
        except Exception:
            start_dt = end_dt = None

        if start_dt and start_dt > now:
            continue
        if end_dt and end_dt < now:
            continue
        if discount == 0:
            return (True, start_dt, end_dt)

    return (False, None, None)


def _find_upcoming_free_offer(
    game: dict[str, Any], now: datetime
) -> tuple[datetime | None, datetime | None]:
    """Return the start/end of the next upcoming free offer, if any."""

    promotions = game.get("promotions") or {}
    upcoming = promotions.get("upcomingPromotionalOffers") or []

    if not upcoming:
        return (None, None)

    offers = upcoming[0].get("promotionalOffers") or []
    for offer in offers:
        start = offer.get("startDate")
        end = offer.get("endDate")
        discount = (offer.get("discountSetting") or {}).get("discountPercentage")

        try:
            start_dt = (
                datetime.fromisoformat(start.replace("Z", "+00:00")) if start else None
            )
            end_dt = datetime.fromisoformat(end.replace("Z", "+00:00")) if end else None
        except Exception:
            start_dt = end_dt = None

        if start_dt and start_dt <= now:
            continue
        if discount == 0:
            return (start_dt, end_dt)

    return (None, None)


def _fmt_dt(dt: datetime | None) -> str:
    if not dt:
        return "unknown"
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def fetch_epic_free_games() -> tuple[str, list[str]]:
    return _cached_fetch(
        "epic",
        _GAME_OFFERS_TTL_S,
        _fetch_epic_free_games_uncached,
    )


def _fetch_epic_free_games_uncached() -> tuple[str, list[str]]:
    """Fetch current free games from Epic Games Store.

    Returns tuple of (formatted HTML message, list of image URLs).
    """
    try:
        # Epic Games free games API endpoint
        url = "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions"
        params = {"locale": "en-US", "country": "US", "allowCountries": "US"}

        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        games = (
            data.get("data", {})
            .get("Catalog", {})
            .get("searchStore", {})
            .get("elements", [])
        )

        free_games: list[dict[str, Any]] = []
        upcoming_games: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)
        for game in games:
            is_active, active_start, active_end = _is_active_free_offer(game, now)
            if not is_active:
                start_dt, end_dt = _find_upcoming_free_offer(game, now)
                if start_dt:
                    upcoming_games.append(
                        {
                            "title": game.get("title", "Unknown"),
                            "start": start_dt,
                            "end": end_dt,
                        }
                    )
                continue

            title = game.get("title", "Unknown")
            description = game.get("description", "")
            # Limit description length
            if len(description) > 150:
                description = description[:147] + "..."

            # Extract image URL - prefer wide/landscape images
            image_url = None
            key_images = game.get("keyImages", [])
            for img in key_images:
                img_type = img.get("type", "")
                # Prefer these image types in order
                if img_type in (
                    "DieselStoreFrontWide",
                    "OfferImageWide",
                    "Thumbnail",
                ):
                    image_url = img.get("url")
                    break

            # Fallback to first available image
            if not image_url and key_images:
                image_url = key_images[0].get("url")

            free_games.append(
                {
                    "title": title,
                    "description": description,
                    "image_url": image_url,
                    "start": active_start,
                    "end": active_end,
                }
            )

        # Show only currently active freebies (Epic typically has one active at a time)
        if not free_games:
            return ("🎮 <b>Epic Games</b>\n\nNo free games available right now.", [])

        free_games = free_games[:1]

        if upcoming_games:
            # Sort by start date and take the next one
            upcoming_games = [g for g in upcoming_games if g.get("start")]
            upcoming_games.sort(key=lambda g: g["start"])
            next_up = upcoming_games[:1]
        else:
            next_up = []

        lines = ["🎮 <b>Epic Games - Free This Week</b>\n"]
        image_urls: list[str] = []

        for game in free_games:
            title = html.escape(game["title"])
            desc = (
                html.escape(game["description"])
                if game["description"]
                else "<i>No description</i>"
            )
            start_fmt = _fmt_dt(game.get("start"))
            end_fmt = _fmt_dt(game.get("end"))
            store_url = (
                f"https://store.epicgames.com/en-US/browse?q={quote_plus(game['title'])}"
                if game.get("title")
                else "https://store.epicgames.com/free-games"
            )
            lines.append(
                f"🎁 <a href='{store_url}'><b>{title}</b></a>\n{desc}\n🗓️ {start_fmt} → {end_fmt}\n"
            )

            if game["image_url"]:
                image_urls.append(game["image_url"])

        if next_up:
            lines.append("<b>Coming Soon</b>")
            for up in next_up:
                title = html.escape(up["title"])
                start_fmt = _fmt_dt(up.get("start"))
                end_fmt = _fmt_dt(up.get("end"))
                store_url = (
                    f"https://store.epicgames.com/en-US/browse?q={quote_plus(up['title'])}"
                    if up.get("title")
                    else "https://store.epicgames.com/free-games"
                )
                lines.append(
                    f"🗓️ <a href='{store_url}'>{title}</a>\n   {start_fmt} → {end_fmt}"
                )

        lines.append('<a href="https://store.epicgames.com/free-games">View Store</a>')
        return ("\n".join(lines), image_urls)

    except requests.RequestException as e:
        logger.exception("Failed to fetch Epic Games free games")
        return (f"❌ Failed to fetch Epic Games: {html.escape(str(e))}", [])
    except Exception as e:
        logger.exception("Error processing Epic Games data")
        return (f"❌ Error processing Epic Games data: {html.escape(str(e))}", [])


def fetch_hackernews_top(limit: int = 3) -> str:
    """Fetch top stories from Hacker News.

    Args:
        limit: Number of top stories to fetch (default: 3)

    Returns formatted HTML message or error string.
    """
    try:
        # Fetch top story IDs
        top_url = "https://hacker-news.firebaseio.com/v0/topstories.json"
        response = requests.get(top_url, timeout=10)
        response.raise_for_status()
        story_ids = response.json()[:limit]

        stories: list[dict[str, Any]] = []
        for story_id in story_ids:
            story_url = f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
            story_response = requests.get(story_url, timeout=10)
            story_response.raise_for_status()
            story_data = story_response.json()

            if story_data:
                stories.append(
                    {
                        "title": story_data.get("title", "No title"),
                        "url": story_data.get(
                            "url", f"https://news.ycombinator.com/item?id={story_id}"
                        ),
                        "score": story_data.get("score", 0),
                        "comments": story_data.get("descendants", 0),
                    }
                )

        if not stories:
            return "📰 <b>Hacker News</b>\n\nNo stories available."

        lines = ["📰 <b>Hacker News - Top Stories</b>\n"]
        for i, story in enumerate(stories, 1):
            title = html.escape(story["title"])
            url = html.escape(story["url"])
            score = story["score"]
            comments = story["comments"]

            lines.append(
                f"{i}. <a href='{url}'>{title}</a>\n"
                f"   ⬆️ {score} points • 💬 {comments} comments\n"
            )

        return "\n".join(lines)

    except requests.RequestException as e:
        logger.exception("Failed to fetch Hacker News stories")
        return f"❌ Failed to fetch Hacker News: {html.escape(str(e))}"
    except Exception as e:
        logger.exception("Error processing Hacker News data")
        return f"❌ Error processing Hacker News data: {html.escape(str(e))}"


def fetch_steam_free_games(limit: int = 5) -> tuple[str, list[str]]:
    return _cached_fetch(
        f"steam:{limit}",
        _GAME_OFFERS_TTL_S,
        lambda: _fetch_steam_free_games_uncached(limit),
    )


def _fetch_steam_free_games_uncached(limit: int) -> tuple[str, list[str]]:
    """Fetch currently free-to-keep Steam games (filtering for 100% discount).

    Returns tuple of (formatted HTML message, list of image URLs). Dates are not
    provided by the endpoint; show 'unknown' availability.
    """

    try:
        url = "https://store.steampowered.com/api/featuredcategories"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        specials = (data.get("specials") or {}).get("items") or []
        freebies: list[dict[str, Any]] = []

        for item in specials:
            price = item.get("price") or {}
            initial = price.get("initial", price.get("original_price", 0)) or 0
            final = price.get("final", price.get("final_price", 0)) or 0
            discount = price.get("discount_percent") or item.get("discount_percent")

            # Free-to-keep if price drops to zero from a positive initial price
            if initial > 0 and final == 0 and (discount is None or discount >= 100):
                # Try to extract an image URL if present
                image = None
                for key in (
                    "small_capsule_image",
                    "capsule_image",
                    "large_capsule_image",
                    "header_image",
                    "tiny_image",
                ):
                    val = item.get(key)
                    if isinstance(val, str) and val:
                        image = val
                        break

                freebies.append(
                    {
                        "name": item.get("name", "Unknown"),
                        "id": item.get("id") or item.get("appid"),
                        "discount": discount,
                        "image": image,
                    }
                )

        if not freebies:
            return (
                "🎮 <b>Steam</b>\n\nNo limited-time free-to-keep games right now.",
                [],
            )

        freebies = freebies[: max(1, min(limit, 10))]
        lines = ["🎮 <b>Steam - Free to Keep</b>\n"]
        image_urls: list[str] = []
        for idx, game in enumerate(freebies, 1):
            name = html.escape(game["name"])
            appid = game.get("id")
            link = (
                f"https://store.steampowered.com/app/{appid}"
                if appid
                else "https://store.steampowered.com/"
            )
            discount_txt = (
                f"- {game['discount']}%" if game.get("discount") is not None else ""
            )
            lines.append(
                f"{idx}. <a href='{link}'>{name}</a> {discount_txt}\n🗓️ unknown → unknown"
            )

            if game.get("image"):
                image_urls.append(game["image"])

        return ("\n".join(lines), image_urls[:1])

    except requests.RequestException as e:
        logger.exception("Failed to fetch Steam free games")
        return (f"❌ Failed to fetch Steam freebies: {html.escape(str(e))}", [])
    except Exception as e:
        logger.exception("Error processing Steam free games data")
        return (f"❌ Error processing Steam freebies: {html.escape(str(e))}", [])


def fetch_gog_free_games() -> tuple[str, list[str]]:
    return _cached_fetch(
        "gog",
        _GAME_OFFERS_TTL_S,
        _fetch_gog_free_games_uncached,
    )


def _fetch_gog_free_games_uncached() -> tuple[str, list[str]]:
    """Fetch current GOG giveaway games.

    Returns tuple of (formatted HTML message, list of image URLs).
    """
    try:
        # GOG giveaway endpoint - checks for active giveaways
        url = "https://www.gog.com/games/ajax/filtered"
        params = {
            "mediaType": "game",
            "page": 1,
            "price": "free",
            "sort": "popularity",
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; TeleHomeSupervisor/1.0)",
            "Accept": "application/json",
        }

        response = requests.get(url, params=params, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()

        products = data.get("products", [])
        free_games: list[dict[str, Any]] = []

        for product in products:
            # Check if it's actually free (price is 0 or has a giveaway)
            price = product.get("price", {})
            is_free = price.get("isFree", False) or price.get("finalAmount") == "0.00"

            if is_free:
                title = product.get("title", "Unknown")
                slug = product.get("slug", "")
                image = product.get("image", "")

                # Build full image URL if relative
                if image and not image.startswith("http"):
                    image = f"https:{image}"

                free_games.append(
                    {
                        "title": title,
                        "slug": slug,
                        "image": image,
                        "url": f"https://www.gog.com/game/{slug}" if slug else "",
                    }
                )

        if not free_games:
            return ("🎮 <b>GOG</b>\n\nNo free games available right now.", [])

        # Limit to first 3 games
        free_games = free_games[:3]

        lines = ["🎮 <b>GOG - Free Games</b>\n"]
        image_urls: list[str] = []

        for game in free_games:
            title = html.escape(game["title"])
            url = game.get("url", "https://www.gog.com")
            lines.append(f"🎁 <a href='{url}'>{title}</a>\n🗓️ unknown → unknown")

            if game.get("image"):
                image_urls.append(game["image"])

        lines.append("")
        lines.append(
            '<a href="https://www.gog.com/games?price=free">View GOG Store</a>'
        )
        return ("\n".join(lines), image_urls[:1])

    except requests.RequestException as e:
        logger.exception("Failed to fetch GOG free games")
        return (f"❌ Failed to fetch GOG games: {html.escape(str(e))}", [])
    except Exception as e:
        logger.exception("Error processing GOG data")
        return (f"❌ Error processing GOG data: {html.escape(str(e))}", [])


def fetch_humble_free_games() -> tuple[str, list[str]]:
    return _cached_fetch(
        "humble",
        _GAME_OFFERS_TTL_S,
        _fetch_humble_free_games_uncached,
    )


def _fetch_humble_free_games_uncached() -> tuple[str, list[str]]:
    """Fetch current Humble Bundle free games/giveaways.

    Returns tuple of (formatted HTML message, list of image URLs).
    """
    try:
        # Humble Bundle storefront API for free content
        url = "https://www.humblebundle.com/store/api/search"
        params = {
            "sort": "discount",
            "filter": "all",
            "search": "",
            "request": 1,
            "page_size": 100,
            "page": 0,
        }
        # Use browser-like headers; Humble often blocks generic clients
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "Chrome/120.0 Safari/537.36"
            ),
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": "https://www.humblebundle.com/store",
            "Origin": "https://www.humblebundle.com",
            "X-Requested-With": "XMLHttpRequest",
        }

        session = requests.Session()
        session.headers.update(headers)
        response = session.get(url, params=params, timeout=15)
        if response.status_code == 403:
            # Retry once with alternate UA (some edges are picky)
            session.headers.update(
                {
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 Chrome/122.0 Safari/537.36"
                    )
                }
            )
            response = session.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()

        results = data.get("results", [])
        free_games: list[dict[str, Any]] = []

        for item in results:
            # Check for 100% discount or free items
            current_price = item.get("current_price", {})
            price_amount = current_price.get("amount", 1)

            # Also check for giveaway flag
            is_giveaway = item.get("is_giveaway", False)

            if price_amount == 0 or is_giveaway:
                title = item.get("human_name", "Unknown")
                slug = item.get("human_url", "")
                icon = item.get("icon", "")

                # Build full image URL
                if icon and not icon.startswith("http"):
                    icon = f"https://hb.imgix.net{icon}"

                free_games.append(
                    {
                        "title": title,
                        "url": (
                            f"https://www.humblebundle.com/store/{slug}"
                            if slug
                            else "https://www.humblebundle.com/store"
                        ),
                        "image": icon,
                    }
                )

        # Also check the main page for featured freebies
        if not free_games:
            # Try fetching the main page for giveaways
            giveaway_url = "https://www.humblebundle.com/store/api/lookup"
            giveaway_params = {"products[]": "mosaic"}
            try:
                gw_resp = session.get(
                    giveaway_url,
                    params=giveaway_params,
                    timeout=10,
                )
                if gw_resp.status_code == 200:
                    gw_data = gw_resp.json()
                    for key, item in gw_data.items():
                        if isinstance(item, dict):
                            price = item.get("current_price", {}).get("amount", 1)
                            if price == 0:
                                free_games.append(
                                    {
                                        "title": item.get("human_name", "Unknown"),
                                        "url": f"https://www.humblebundle.com/store/{item.get('human_url', '')}",
                                        "image": item.get("icon", ""),
                                    }
                                )
            except Exception as fallback_error:
                logger.warning(f"Humble Bundle fallback API failed: {fallback_error}")

        if not free_games:
            return (
                "🎮 <b>Humble Bundle</b>\n\nNo free games available right now.",
                [],
            )

        # Limit to first 3 games
        free_games = free_games[:3]

        lines = ["🎮 <b>Humble Bundle - Free Games</b>\n"]
        image_urls: list[str] = []

        for game in free_games:
            title = html.escape(game["title"])
            url = game.get("url", "https://www.humblebundle.com/store")
            lines.append(f"🎁 <a href='{url}'>{title}</a>\n🗓️ unknown → unknown")

            if game.get("image"):
                image_urls.append(game["image"])

        lines.append("")
        lines.append(
            '<a href="https://www.humblebundle.com/store/search?sort=discount&filter=all">View Humble Store</a>'
        )
        return ("\n".join(lines), image_urls[:1])

    except requests.RequestException as e:
        logger.exception("Failed to fetch Humble Bundle free games")
        return (f"❌ Failed to fetch Humble Bundle: {html.escape(str(e))}", [])
    except Exception as e:
        logger.exception("Error processing Humble Bundle data")
        return (f"❌ Error processing Humble Bundle: {html.escape(str(e))}", [])


def build_combined_game_offers(limit_steam: int = 5) -> str:
    """Combine Epic, Steam, GOG, and Humble offers into one HTML message."""
    sections: list[str] = []

    try:
        epic_msg, _ = fetch_epic_free_games()
        if epic_msg:
            sections.append(epic_msg)
    except Exception:
        logger.exception("Failed to include Epic section")

    try:
        steam_msg, _ = fetch_steam_free_games(limit_steam)
        if steam_msg:
            sections.append(steam_msg)
    except Exception:
        logger.exception("Failed to include Steam section")

    try:
        gog_msg, _ = fetch_gog_free_games()
        if gog_msg:
            sections.append(gog_msg)
    except Exception:
        logger.exception("Failed to include GOG section")

    try:
        humble_msg, _ = fetch_humble_free_games()
        if humble_msg:
            sections.append(humble_msg)
    except Exception:
        logger.exception("Failed to include Humble section")

    if not sections:
        return "🎮 <b>Game Offers</b>\n\nNo current free offers found."

    # Join sections with a clear separator
    return "\n\n".join(sections)
