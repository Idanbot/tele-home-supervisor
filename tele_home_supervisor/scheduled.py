"""Scheduled notification fetchers (Epic Games, Hacker News, etc.)."""

from __future__ import annotations

import html
import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)


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
        for game in games:
            # Check if game is currently free
            promotions = game.get("promotions")
            if not promotions:
                continue

            promotional_offers = promotions.get("promotionalOffers", [])
            if not promotional_offers:
                continue

            # Game is free if it has active promotional offers
            offers = promotional_offers[0].get("promotionalOffers", [])
            if offers:
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
                    }
                )

        if not free_games:
            return ("🎮 <b>Epic Games</b>\n\nNo free games available right now.", [])

        lines = ["🎮 <b>Epic Games - Free This Week</b>\n"]
        image_urls: list[str] = []

        for game in free_games:
            title = html.escape(game["title"])
            desc = (
                html.escape(game["description"])
                if game["description"]
                else "<i>No description</i>"
            )
            lines.append(f"🎁 <b>{title}</b>\n{desc}\n")

            if game["image_url"]:
                image_urls.append(game["image_url"])

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
