"""Callback query handlers for inline keyboard buttons."""

from __future__ import annotations

import asyncio
import html
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from .. import services, view, config
from ..state import BotState
from .common import get_state

logger = logging.getLogger(__name__)


def build_docker_keyboard(containers: list[str]) -> InlineKeyboardMarkup:
    """Build inline keyboard with container action buttons."""
    buttons = []
    for name in containers[:8]:
        buttons.append(
            [
                InlineKeyboardButton(
                    f"📜 {name[:12]}", callback_data=f"dlogs:{name[:30]}"
                ),
                InlineKeyboardButton("❤️", callback_data=f"dhealth:{name[:30]}"),
                InlineKeyboardButton("📊", callback_data=f"dstats:{name[:30]}"),
            ]
        )
    buttons.append([InlineKeyboardButton("🔄 Refresh", callback_data="docker:refresh")])
    return InlineKeyboardMarkup(buttons)


def build_torrent_keyboard(torrents: list[dict]) -> InlineKeyboardMarkup:
    """Build inline keyboard with torrent action buttons."""
    buttons = []
    for t in torrents[:6]:
        name = t.get("name", "Unknown")[:20]
        torrent_hash = t.get("hash", "")[:16]
        state = t.get("state", "")

        row = [
            InlineKeyboardButton(f"📁 {name}", callback_data=f"tinfo:{torrent_hash}")
        ]

        if state in ("downloading", "uploading", "stalledDL", "stalledUP", "queuedDL"):
            row.append(InlineKeyboardButton("⏸️", callback_data=f"tstop:{torrent_hash}"))
        else:
            row.append(
                InlineKeyboardButton("▶️", callback_data=f"tstart:{torrent_hash}")
            )

        buttons.append(row)

    buttons.append(
        [InlineKeyboardButton("🔄 Refresh", callback_data="torrent:refresh")]
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


async def handle_callback_query(update, context) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data
    chat_id = update.effective_chat.id if update.effective_chat else None

    if chat_id not in config.ALLOWED:
        await query.edit_message_text("⛔ Not authorized")
        return

    try:
        if data.startswith("dlogs:"):
            container = data[6:]
            await _handle_dlogs_callback(query, container)
        elif data.startswith("dhealth:"):
            container = data[8:]
            await _handle_dhealth_callback(query, container)
        elif data.startswith("dstats:"):
            container = data[7:]
            await _handle_dstats_callback(query, container)
        elif data == "docker:refresh":
            await _handle_docker_refresh(query, context)
        elif data.startswith("tstop:"):
            torrent_hash = data[6:]
            await _handle_torrent_stop(query, torrent_hash)
        elif data.startswith("tstart:"):
            torrent_hash = data[7:]
            await _handle_torrent_start(query, torrent_hash)
        elif data.startswith("tinfo:"):
            torrent_hash = data[6:]
            await _handle_torrent_info(query, torrent_hash)
        elif data == "torrent:refresh":
            await _handle_torrent_refresh(query, context)
        elif data.startswith("games:"):
            game_type = data[6:]
            await _handle_games_callback(query, game_type)
        else:
            await query.edit_message_text("❓ Unknown action")
    except Exception as e:
        logger.exception("Callback query error")
        try:
            await query.message.reply_text(f"❌ Error: {html.escape(str(e))}")
        except Exception as notify_error:
            logger.error(f"Failed to send error notification: {notify_error}")


async def _handle_dlogs_callback(query, container: str) -> None:
    await query.message.reply_text(f"🔄 Fetching logs for {container}...")
    # Default 20 lines tail
    raw = await services.get_container_logs(container, 20)
    msg = view.render_logs(container, raw, "tail", "20")
    for part in view.chunk(msg):
        await query.message.reply_text(part, parse_mode=ParseMode.HTML)


async def _handle_dhealth_callback(query, container: str) -> None:
    msg = await services.healthcheck_container(container)
    await query.message.reply_text(f"<pre>{msg}</pre>", parse_mode=ParseMode.HTML)


async def _handle_dstats_callback(query, container: str) -> None:
    # We fetch all stats and filter? Or just show all?
    # Original logic showed all for dstats command but filtered for button?
    # Original: "Filter to show only the requested container if possible" -> comment only
    # Actually utils.container_stats_summary returns string for ALL containers.
    # To filter we would need the rich dict.

    stats = await services.container_stats_rich()
    # Filter for container
    target_stats = [s for s in stats if s["name"] == container]
    if not target_stats:
        msg = f"Stats for {container} not found."
    else:
        msg = view.render_container_stats(target_stats)

    await query.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def _handle_docker_refresh(query, context) -> None:
    state: BotState = get_state(context.application)
    state.refresh_containers()

    containers = await services.list_containers()
    msg = view.render_container_list(containers)

    container_names = list(state.get_cached("containers"))
    keyboard = build_docker_keyboard(container_names)

    await query.edit_message_text(
        msg[:4000], parse_mode=ParseMode.HTML, reply_markup=keyboard
    )


async def _handle_torrent_stop(query, torrent_hash: str) -> None:
    result = await services.torrent_stop_by_hash(torrent_hash)
    await query.message.reply_text(result, parse_mode=ParseMode.HTML)


async def _handle_torrent_start(query, torrent_hash: str) -> None:
    result = await services.torrent_start_by_hash(torrent_hash)
    await query.message.reply_text(result, parse_mode=ParseMode.HTML)


async def _handle_torrent_info(query, torrent_hash: str) -> None:
    result = await services.torrent_info_by_hash(torrent_hash)
    await query.message.reply_text(result, parse_mode=ParseMode.HTML)


async def _handle_torrent_refresh(query, context) -> None:
    state: BotState = get_state(context.application)
    state.refresh_torrents()

    torrents = await services.get_torrent_list()
    msg = view.render_torrent_list(torrents)
    keyboard = build_torrent_keyboard(torrents)

    await query.edit_message_text(
        msg[:4000], parse_mode=ParseMode.HTML, reply_markup=keyboard
    )


async def _handle_games_callback(query, game_type: str) -> None:
    from .. import scheduled as scheduled_fetchers

    await query.message.reply_text(f"🔄 Fetching {game_type} free games...")

    # scheduled fetchers are likely sync, so we wrap them
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
        await query.message.reply_photo(
            photo=image_urls[0],
            caption=message,
            parse_mode=ParseMode.HTML,
        )
    else:
        await query.message.reply_text(
            message, parse_mode=ParseMode.HTML, disable_web_page_preview=True
        )
