"""Callback handlers for media browsing (TMDB, ProtonDB, PirateBay, games)."""

from __future__ import annotations

import asyncio
import html
import logging
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from .. import services, tmdb, view, protondb
from ..state import BotState
from .common import get_state, tracked_reply_photo
from .cb_helpers import safe_edit_message_text

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Keyboard builders
# ---------------------------------------------------------------------------


def build_tmdb_keyboard(
    key: str, items: list[dict[str, object]], page: int, total_pages: int
) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for idx, item in enumerate(items, start=1):
        title = str(item.get("title") or item.get("name") or "Unknown")
        media_type = str(item.get("media_type") or "")
        item_id = item.get("id")
        if not item_id or media_type not in {"movie", "tv"}:
            continue
        label = f"{idx}. {title}"
        if len(label) > 60:
            label = f"{label[:57]}..."
        buttons.append(
            [
                InlineKeyboardButton(
                    label, callback_data=f"tmdbinfo:{media_type}:{item_id}"
                )
            ]
        )
    nav_row: list[InlineKeyboardButton] = []
    if page > 1:
        nav_row.append(
            InlineKeyboardButton("⬅️ Prev", callback_data=f"tmdbpage:{key}:{page - 1}")
        )
    nav_row.append(
        InlineKeyboardButton(
            f"📄 {page}/{max(total_pages, 1)}",
            callback_data=f"tmdbpage:{key}:{page}",
        )
    )
    if page < total_pages:
        nav_row.append(
            InlineKeyboardButton("Next ➡️", callback_data=f"tmdbpage:{key}:{page + 1}")
        )
    if nav_row:
        buttons.append(nav_row)
    return InlineKeyboardMarkup(buttons)


def build_protondb_keyboard(key: str, games: list[dict]) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for idx, game in enumerate(games):
        name = str(game.get("name") or "Unknown")
        appid = str(game.get("appid") or "")
        if not appid:
            continue
        label = f"{idx + 1}. {name}"
        if len(label) > 60:
            label = f"{label[:57]}..."
        buttons.append(
            [InlineKeyboardButton(label, callback_data=f"protondbinfo:{key}:{idx}")]
        )
    return InlineKeyboardMarkup(buttons)


def build_free_games_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton("🎮 Epic", callback_data="games:epic"),
            InlineKeyboardButton("🎮 Steam", callback_data="games:steam"),
        ],
        [
            InlineKeyboardButton("🎮 GOG", callback_data="games:gog"),
            InlineKeyboardButton("🎮 Humble", callback_data="games:humble"),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


# ---------------------------------------------------------------------------
# Callback handlers
# ---------------------------------------------------------------------------


def _parse_tmdb_page_payload(data: str) -> tuple[str, int] | None:
    payload = data[len("tmdbpage:") :]
    parts = payload.split(":")
    if len(parts) != 2:
        return None
    key = parts[0]
    try:
        page = int(parts[1])
    except ValueError:
        return None
    return key, max(1, page)


async def handle_tmdb_page(query, context, data: str) -> None:
    payload = _parse_tmdb_page_payload(data)
    if not payload:
        await query.message.reply_text("❌ Invalid TMDB page request.")
        return
    key, page = payload
    state: BotState = get_state(context.application)
    entry = state.get_tmdb_results(key)
    if not entry:
        await query.message.reply_text("❌ TMDB results expired. Re-run command.")
        return

    try:
        if entry.kind == "movies":
            result = await services.tmdb_trending_movies(page)
            items = tmdb.extract_items(result, default_type="movie")
        elif entry.kind == "shows":
            result = await services.tmdb_trending_shows(page)
            items = tmdb.extract_items(result, default_type="tv")
        elif entry.kind == "incinema":
            result = await services.tmdb_in_cinema(page)
            items = tmdb.extract_items(result, default_type="movie")
        elif entry.kind == "search":
            result = await services.tmdb_search_multi(entry.query or "", page)
            items = tmdb.extract_items(result)
        else:
            await query.message.reply_text("❌ Unsupported TMDB list.")
            return
    except Exception as exc:
        await query.message.reply_text(f"❌ TMDB error: {html.escape(str(exc))}")
        return

    total_pages = int(result.get("total_pages") or 1)
    entry.page = page
    entry.total_pages = total_pages
    entry.items = items
    entry.updated_at = time.monotonic()
    state.tmdb_cache[key] = entry

    title = "TMDB"
    if entry.kind == "movies":
        title = "TMDB Trending Movies"
    elif entry.kind == "shows":
        title = "TMDB Trending Shows"
    elif entry.kind == "incinema":
        title = "TMDB In Cinemas"
    elif entry.kind == "search":
        title = f"TMDB Search: {entry.query}"
    msg = view.render_tmdb_list(title, items)
    keyboard = build_tmdb_keyboard(key, items, page, total_pages)
    await safe_edit_message_text(
        query, msg[:4000], parse_mode=ParseMode.HTML, reply_markup=keyboard
    )


async def handle_tmdb_info(query, context, data: str) -> None:
    payload = data[len("tmdbinfo:") :]
    parts = payload.split(":")
    if len(parts) != 2:
        await query.message.reply_text("❌ Invalid TMDB info request.")
        return
    media_type, id_str = parts
    try:
        tmdb_id = int(id_str)
    except ValueError:
        await query.message.reply_text("❌ Invalid TMDB id.")
        return
    try:
        if media_type == "movie":
            info = await services.tmdb_movie_details(tmdb_id)
        elif media_type == "tv":
            info = await services.tmdb_tv_details(tmdb_id)
        else:
            await query.message.reply_text("❌ Unknown TMDB media type.")
            return
    except Exception as exc:
        await query.message.reply_text(f"❌ TMDB error: {html.escape(str(exc))}")
        return

    title = info.get("title") or info.get("name") or "Unknown"
    overview = info.get("overview") or ""
    rating = info.get("vote_average")
    date = info.get("release_date") or info.get("first_air_date") or ""
    genres = ", ".join(g.get("name") for g in info.get("genres", []) if g.get("name"))
    poster_path = info.get("poster_path")
    url = (
        f"https://www.themoviedb.org/movie/{tmdb_id}"
        if media_type == "movie"
        else f"https://www.themoviedb.org/tv/{tmdb_id}"
    )
    lines = [
        f"<b>{html.escape(str(title))}</b>",
        f"Date: {html.escape(str(date))}" if date else "Date: -",
        f"Rating: {rating:.1f}" if isinstance(rating, (int, float)) else "Rating: -",
        f"Genres: {html.escape(genres) if genres else '-'}",
    ]
    if overview:
        lines.append("")
        max_overview = 600
        if len(overview) > max_overview:
            overview = overview[:max_overview].rsplit(" ", 1)[0] + "..."
        lines.append(html.escape(str(overview)))
    lines.append("")
    lines.append(f'<a href="{url}">TMDB</a>')
    caption = "\n".join(lines)

    if poster_path:
        image_url = f"https://image.tmdb.org/t/p/w500{poster_path}"
        try:
            state: BotState = get_state(context.application)
            await tracked_reply_photo(
                query.message,
                state,
                photo=image_url,
                caption=caption,
                parse_mode=ParseMode.HTML,
            )
            return
        except Exception as img_err:
            logger.debug("Failed to send TMDB poster image: %s", img_err)

    await query.message.reply_text(
        caption, parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )


async def handle_protondb_info(query, context, data: str) -> None:
    payload = data[len("protondbinfo:") :]
    parts = payload.split(":")
    if len(parts) != 2:
        await query.message.reply_text("❌ Invalid ProtonDB request.")
        return
    key, idx_str = parts
    try:
        idx = int(idx_str)
    except ValueError:
        await query.message.reply_text("❌ Invalid game index.")
        return

    state: BotState = get_state(context.application)
    games = state.get_protondb_results(key)
    if not games or idx >= len(games):
        await query.message.reply_text("❌ Results expired. Please search again.")
        return

    game = games[idx]
    appid = game.get("appid")
    name = game.get("name") or "Unknown"

    if not appid:
        await query.message.reply_text("❌ Invalid game data.")
        return

    protondb_data, steam_data, player_count = await asyncio.gather(
        services.protondb_summary(appid),
        services.steam_app_details(appid),
        services.steam_player_count(appid),
        return_exceptions=True,
    )

    if isinstance(protondb_data, Exception):
        logger.debug("ProtonDB fetch failed: %s", protondb_data)
        protondb_data = None
    if isinstance(steam_data, Exception):
        logger.debug("Steam details fetch failed: %s", steam_data)
        steam_data = None
    if isinstance(player_count, Exception):
        logger.debug("Steam player count fetch failed: %s", player_count)
        player_count = None

    lines = [f"<b>{html.escape(str(name))}</b>"]

    if protondb_data:
        tier = protondb_data.get("tier")
        trending_tier = protondb_data.get("trendingTier")
        confidence = protondb_data.get("confidence")
        total_reports = protondb_data.get("total")
        score = protondb_data.get("score")

        tier_emoji = protondb.tier_emoji(tier)
        tier_text = protondb.format_tier(tier)
        lines.append(f"ProtonDB: {tier_emoji} <b>{tier_text}</b>")

        if trending_tier and trending_tier != tier:
            trend_emoji = protondb.tier_emoji(trending_tier)
            trend_text = protondb.format_tier(trending_tier)
            lines.append(f"Trending: {trend_emoji} {trend_text}")

        if confidence:
            lines.append(f"Confidence: {html.escape(str(confidence))}")
        if total_reports:
            lines.append(f"Reports: {total_reports}")
        if score is not None:
            lines.append(f"Score: {score:.2f}")
    else:
        lines.append("ProtonDB: <i>No data available</i>")

    if player_count is not None:
        lines.append(f"Current Players: {player_count:,}")

    metacritic = None
    header_image = None
    if steam_data:
        metacritic = steam_data.get("metacritic", {}).get("score")
        header_image = steam_data.get("header_image")
        release_date = steam_data.get("release_date", {}).get("date")
        steam_genres = steam_data.get("genres", [])
        genre_names = ", ".join(
            g.get("name", "") for g in steam_genres[:3] if g.get("name")
        )

        if release_date:
            lines.append(f"Released: {html.escape(str(release_date))}")
        if genre_names:
            lines.append(f"Genres: {html.escape(genre_names)}")
        if metacritic:
            lines.append(f"Metacritic: {metacritic}")

    lines.append("")
    lines.append(
        f'<a href="https://www.protondb.com/app/{appid}">ProtonDB</a> | '
        f'<a href="https://store.steampowered.com/app/{appid}">Steam</a>'
    )

    caption = "\n".join(lines)

    if header_image:
        try:
            state: BotState = get_state(context.application)
            await tracked_reply_photo(
                query.message,
                state,
                photo=header_image,
                caption=caption,
                parse_mode=ParseMode.HTML,
            )
            return
        except Exception as img_err:
            logger.debug("Failed to send Steam header image: %s", img_err)

    await query.message.reply_text(
        caption, parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )


async def handle_games_callback(query, context, game_type: str) -> None:
    from .. import scheduled as scheduled_fetchers

    await query.message.reply_text(f"🔄 Fetching {game_type} free games...")

    if game_type == "epic":
        message, image_urls = await asyncio.to_thread(
            scheduled_fetchers.fetch_epic_free_games
        )
    elif game_type == "steam":
        message = await asyncio.to_thread(scheduled_fetchers.fetch_steam_free_games, 5)
        image_urls = []
    elif game_type == "gog":
        message, image_urls = await asyncio.to_thread(
            scheduled_fetchers.fetch_gog_free_games
        )
    elif game_type == "humble":
        message, image_urls = await asyncio.to_thread(
            scheduled_fetchers.fetch_humble_free_games
        )
    else:
        await query.message.reply_text("❓ Unknown game store")
        return

    if image_urls:
        state: BotState = get_state(context.application)
        await tracked_reply_photo(
            query.message,
            state,
            photo=image_urls[0],
            caption=message,
            parse_mode=ParseMode.HTML,
        )
    else:
        await query.message.reply_text(
            message, parse_mode=ParseMode.HTML, disable_web_page_preview=True
        )


async def handle_piratebay_select(query, context, key: str) -> None:
    state: BotState = get_state(context.application)
    entry = state.get_magnet(key)
    if not entry:
        await query.message.reply_text("❌ Torrent link expired.")
        return
    name, magnet, seeds, leech = entry
    safe_name = html.escape(name)

    msg = f"<b>{safe_name}</b>\n\n🌱 Seeds: {seeds}\n🐌 Leechers: {leech}"

    buttons = [
        [InlineKeyboardButton("🧲 Get Magnet", callback_data=f"pbmagnet:{key}")],
        [InlineKeyboardButton("➕ Add to qBittorrent", callback_data=f"pbadd:{key}")],
    ]
    keyboard = InlineKeyboardMarkup(buttons)

    await query.message.reply_text(
        msg, parse_mode=ParseMode.HTML, reply_markup=keyboard
    )


async def handle_piratebay_add(query, context, key: str) -> None:
    state: BotState = get_state(context.application)
    entry = state.get_magnet(key)
    if not entry:
        await query.message.reply_text("❌ Torrent link expired.")
        return
    _name, magnet, _, _ = entry

    res = await services.torrent_add(magnet)

    chat_id = query.message.chat.id
    if not state.torrent_completion_enabled(chat_id):
        state.set_torrent_completion_subscription(chat_id, True)

    await query.message.reply_text(res, parse_mode=ParseMode.HTML)


async def handle_piratebay_magnet(query, context, key: str) -> None:
    state: BotState = get_state(context.application)
    entry = state.get_magnet(key)
    if not entry:
        await query.message.reply_text("❌ Torrent link expired.")
        return
    name, magnet, _, _ = entry
    safe_name = html.escape(name)
    safe_magnet = html.escape(magnet)
    msg = f"<b>{safe_name}</b>\n<code>{safe_magnet}</code>"
    await query.message.reply_text(msg, parse_mode=ParseMode.HTML)
