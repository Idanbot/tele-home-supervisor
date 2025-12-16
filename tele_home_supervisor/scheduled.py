"""Scheduled notification fetchers (Epic Games, Hacker News, etc.)."""

from __future__ import annotations

import html
import logging
from typing import Any
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)


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
            lines.append(f"🎁 <b>{title}</b>\n{desc}\n🗓️ {start_fmt} → {end_fmt}\n")

            if game["image_url"]:
                image_urls.append(game["image_url"])

        if next_up:
            lines.append("<b>Coming Soon</b>")
            for up in next_up:
                title = html.escape(up["title"])
                start_fmt = _fmt_dt(up.get("start"))
                end_fmt = _fmt_dt(up.get("end"))
                lines.append(f"🗓️ {title}\n   {start_fmt} → {end_fmt}")

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


def fetch_steam_free_games(limit: int = 5) -> str:
    """Fetch currently free-to-keep Steam games (filtering for 100% discount)."""

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
                freebies.append(
                    {
                        "name": item.get("name", "Unknown"),
                        "id": item.get("id") or item.get("appid"),
                        "discount": discount,
                    }
                )

        if not freebies:
            return "🎮 <b>Steam</b>\n\nNo limited-time free-to-keep games right now."

        freebies = freebies[: max(1, min(limit, 10))]
        lines = ["🎮 <b>Steam - Free to Keep</b>\n"]
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
            lines.append(f"{idx}. <a href='{link}'>{name}</a> {discount_txt}")

        return "\n".join(lines)

    except requests.RequestException as e:
        logger.exception("Failed to fetch Steam free games")
        return f"❌ Failed to fetch Steam freebies: {html.escape(str(e))}"
    except Exception as e:
        logger.exception("Error processing Steam free games data")
        return f"❌ Error processing Steam freebies: {html.escape(str(e))}"
