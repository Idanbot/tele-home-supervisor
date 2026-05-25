"""Scheduled notification fetchers (Epic Games, Hacker News, GOG, Steam, GamerPower giveaways).

Also provides a combined game offers builder for daily digests.
"""

from __future__ import annotations

import asyncio
import html
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote_plus

import httpx

from .models.scheduled_cache import ScheduledCacheEntry

logger = logging.getLogger(__name__)

_GAME_OFFERS_TTL_S = 24 * 60 * 60
_CACHE_BASE_BACKOFF_S = 15 * 60
_CACHE_MAX_BACKOFF_S = 6 * 60 * 60

_cache_lock = asyncio.Lock()
_cache: dict[str, ScheduledCacheEntry] = {}

_CLIENT: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            transport=httpx.AsyncHTTPTransport(retries=2),
        )
    return _CLIENT


def _is_error_value(value: object | None) -> bool:
    if isinstance(value, tuple) and value:
        msg = value[0]
    else:
        msg = value
    return isinstance(msg, str) and msg.strip().startswith("❌")


async def _cached_fetch(
    key: str,
    ttl_s: float,
    fetcher: Callable[[], Any],
) -> Any:
    now = time.monotonic()
    async with _cache_lock:
        entry = _cache.get(key)
        if entry and entry.value is not None and (now - entry.fetched_at) < ttl_s:
            return entry.value
        if entry and now < entry.next_retry_at:
            return entry.value if entry.value is not None else entry.last_error

    value: object | None = None
    try:
        # Check if fetcher is async
        if asyncio.iscoroutinefunction(fetcher):
            value = await fetcher()
        else:
            value = fetcher()

        if _is_error_value(value):
            raise RuntimeError("fetch returned error value")
    except Exception as exc:
        async with _cache_lock:
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
            _cache[key] = ScheduledCacheEntry(
                value=None,
                fetched_at=0.0,
                error_count=error_count,
                next_retry_at=next_retry_at,
                last_error=value,
            )
        if value is not None:
            return value
        raise

    async with _cache_lock:
        _cache[key] = ScheduledCacheEntry(value=value, fetched_at=now)
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
    return dt.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


async def fetch_epic_free_games() -> tuple[str, list[str]]:
    return await _cached_fetch(
        "epic",
        _GAME_OFFERS_TTL_S,
        _fetch_epic_free_games_uncached,
    )


async def _fetch_epic_free_games_uncached() -> tuple[str, list[str]]:
    """Fetch current free games from Epic Games Store."""
    try:
        url = "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions"
        params = {"locale": "en-US", "country": "US", "allowCountries": "US"}

        client = _get_client()
        response = await client.get(url, params=params)
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
        now = datetime.now(UTC)
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
            if len(description) > 150:
                description = description[:147] + "..."

            image_url = None
            key_images = game.get("keyImages", [])
            for img in key_images:
                img_type = img.get("type", "")
                if img_type in ("DieselStoreFrontWide", "OfferImageWide", "Thumbnail"):
                    image_url = img.get("url")
                    break

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

        if not free_games:
            return ("🎮 <b>Epic Games</b>\n\nNo free games available right now.", [])

        free_games = free_games[:1]

        if upcoming_games:
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

    except Exception as e:
        logger.exception("Failed to fetch Epic Games free games")
        return (f"❌ Failed to fetch Epic Games: {html.escape(str(e))}", [])


async def fetch_hackernews_top(limit: int = 10) -> str:
    """Fetch top stories from Hacker News."""
    client = _get_client()
    last_error = None
    for attempt in range(2):
        try:
            top_url = "https://hacker-news.firebaseio.com/v0/topstories.json"
            response = await client.get(top_url)
            response.raise_for_status()
            story_ids = response.json()[:limit]

            stories: list[dict[str, Any]] = []
            for story_id in story_ids:
                story_url = (
                    f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
                )
                try:
                    story_response = await client.get(story_url)
                    story_response.raise_for_status()
                    story_data = story_response.json()
                    if story_data:
                        stories.append(
                            {
                                "title": story_data.get("title", "No title"),
                                "url": story_data.get(
                                    "url",
                                    f"https://news.ycombinator.com/item?id={story_id}",
                                ),
                                "score": story_data.get("score", 0),
                                "comments": story_data.get("descendants", 0),
                            }
                        )
                except Exception:
                    logger.warning("Failed to fetch HN story %s", story_id)
                    continue

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

        except Exception as e:
            last_error = e
            logger.warning("HN fetch attempt %d failed: %s", attempt + 1, e)
            if attempt == 0:
                await asyncio.sleep(5)

    logger.exception("Failed to fetch Hacker News stories after retries")
    return f"❌ Failed to fetch Hacker News: {html.escape(str(last_error))}"


async def fetch_steam_free_games(limit: int = 5) -> tuple[str, list[str]]:
    return await _cached_fetch(
        f"steam:{limit}",
        _GAME_OFFERS_TTL_S,
        lambda: _fetch_steam_free_games_uncached(limit),
    )


async def _fetch_steam_free_games_uncached(limit: int) -> tuple[str, list[str]]:
    """Fetch currently free-to-keep Steam games."""
    try:
        url = "https://store.steampowered.com/api/featuredcategories"
        client = _get_client()
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()

        specials = (data.get("specials") or {}).get("items") or []
        freebies: list[dict[str, Any]] = []

        for item in specials:
            price = item.get("price") or {}
            initial = price.get("initial", price.get("original_price", 0)) or 0
            final = price.get("final", price.get("final_price", 0)) or 0
            discount = price.get("discount_percent") or item.get("discount_percent")

            if initial > 0 and final == 0 and (discount is None or discount >= 100):
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

    except Exception as e:
        logger.exception("Failed to fetch Steam free games")
        return (f"❌ Failed to fetch Steam freebies: {html.escape(str(e))}", [])


async def fetch_gog_free_games() -> tuple[str, list[str]]:
    return await _cached_fetch(
        "gog",
        _GAME_OFFERS_TTL_S,
        _fetch_gog_free_games_uncached,
    )


async def _fetch_gog_free_games_uncached() -> tuple[str, list[str]]:
    """Fetch current GOG giveaway games."""
    try:
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

        client = _get_client()
        response = await client.get(url, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()

        products = data.get("products", [])
        free_games: list[dict[str, Any]] = []

        for product in products:
            price = product.get("price", {})
            is_free = price.get("isFree", False) or price.get("finalAmount") == "0.00"

            if is_free:
                title = product.get("title", "Unknown")
                slug = product.get("slug", "")
                image = product.get("image", "")
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

    except Exception as e:
        logger.exception("Failed to fetch GOG free games")
        return (f"❌ Failed to fetch GOG games: {html.escape(str(e))}", [])


async def fetch_humble_free_games() -> tuple[str, list[str]]:
    """Fetch active PC game giveaways via GamerPower (replaces defunct Humble Bundle API)."""
    return await _cached_fetch(
        "gamerpower",
        _GAME_OFFERS_TTL_S,
        _fetch_gamerpower_giveaways_uncached,
    )


async def _fetch_gamerpower_giveaways_uncached() -> tuple[str, list[str]]:
    """Fetch active PC game giveaways from GamerPower public API.

    Covers giveaways across Steam, itch.io, IndieGala, and other platforms.
    Excludes Epic Games and GOG which are fetched separately.
    """
    # Platforms already covered by dedicated fetchers – skip them here.
    _SKIP_PLATFORMS = {"epic games store", "gog"}

    try:
        url = "https://www.gamerpower.com/api/giveaways"
        params: dict[str, str] = {
            "platform": "pc",
            "type": "game",
            "sort-by": "value",
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; TeleHomeSupervisor/1.0)",
            "Accept": "application/json",
        }

        client = _get_client()
        response = await client.get(url, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()

        if not isinstance(data, list):
            return ("🎮 <b>Other Giveaways</b>\n\nNo active giveaways right now.", [])

        free_games: list[dict[str, Any]] = []
        now = datetime.now(UTC)

        for item in data:
            # Skip platforms already shown in other sections
            platforms_raw = item.get("platforms", "").lower()
            if any(skip in platforms_raw for skip in _SKIP_PLATFORMS):
                continue

            status = item.get("status", "").lower()
            if status != "active":
                continue

            # Parse expiry and skip already-expired entries
            end_date_str = item.get("end_date", "N/A")
            expiry_str = "ongoing"
            if end_date_str and end_date_str != "N/A":
                try:
                    expiry_dt = datetime.strptime(
                        end_date_str, "%Y-%m-%d %H:%M:%S"
                    ).replace(tzinfo=UTC)
                    if expiry_dt < now:
                        continue  # Already expired
                    expiry_str = expiry_dt.strftime("%Y-%m-%d")
                except ValueError:
                    pass

            title = item.get("title", "Unknown")
            url_game = item.get("open_giveaway", item.get("gamerpower_url", ""))
            thumbnail = item.get("thumbnail", "")
            worth = item.get("worth", "")

            free_games.append(
                {
                    "title": title,
                    "url": url_game,
                    "image": thumbnail,
                    "expiry": expiry_str,
                    "worth": worth,
                    "platforms": item.get("platforms", ""),
                }
            )

        if not free_games:
            return ("🎮 <b>Other Giveaways</b>\n\nNo active giveaways right now.", [])

        free_games = free_games[:5]
        lines = ["🎮 <b>Other Giveaways</b>\n"]
        image_urls: list[str] = []

        for game in free_games:
            title = html.escape(game["title"])
            game_url = game.get("url", "https://www.gamerpower.com")
            expiry = game.get("expiry", "ongoing")
            worth = game.get("worth", "")
            platforms = html.escape(game.get("platforms", ""))

            worth_str = f" ({html.escape(worth)})" if worth and worth != "N/A" else ""
            date_str = f" · ends {expiry}" if expiry != "ongoing" else ""
            lines.append(
                f"🎁 <a href='{game_url}'>{title}</a>{worth_str}\n"
                f"   📦 {platforms}{date_str}"
            )

            if game.get("image") and not image_urls:
                image_urls.append(game["image"])

        lines.append("")
        lines.append(
            '<a href="https://www.gamerpower.com/free-games-for-pc">View all PC giveaways</a>'
        )
        return ("\n".join(lines), image_urls[:1])

    except Exception as e:
        logger.exception("Failed to fetch GamerPower giveaways")
        return (f"❌ Failed to fetch giveaways: {html.escape(str(e))}", [])


async def build_combined_game_offers(limit_steam: int = 5) -> tuple[str, str | None]:
    """Combine Epic, Steam, GOG, and GamerPower giveaways into one HTML message."""
    sections: list[str] = []
    epic_image: str | None = None

    try:
        epic_msg, epic_images = await fetch_epic_free_games()
        if epic_msg:
            sections.append(epic_msg)
        if epic_images:
            epic_image = epic_images[0]
    except Exception:
        logger.exception("Failed to include Epic section")

    try:
        steam_msg, _ = await fetch_steam_free_games(limit_steam)
        if steam_msg:
            sections.append(steam_msg)
    except Exception:
        logger.exception("Failed to include Steam section")

    try:
        gog_msg, _ = await fetch_gog_free_games()
        if gog_msg:
            sections.append(gog_msg)
    except Exception:
        logger.exception("Failed to include GOG section")

    try:
        humble_msg, _ = await fetch_humble_free_games()
        if humble_msg:
            sections.append(humble_msg)
    except Exception:
        logger.exception("Failed to include Humble section")

    if not sections:
        return ("🎮 <b>Game Offers</b>\n\nNo current free offers found.", None)

    return ("\n\n".join(sections), epic_image)
