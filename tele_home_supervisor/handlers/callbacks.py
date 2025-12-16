"""Callback query handlers for inline keyboard buttons."""

from __future__ import annotations

import asyncio
import html
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from .. import services, utils
from ..state import BotState
from .common import get_state

logger = logging.getLogger(__name__)


def build_docker_keyboard(containers: list[str]) -> InlineKeyboardMarkup:
    """Build inline keyboard with container action buttons."""
    buttons = []
    for name in containers[:8]:  # Limit to 8 containers for UI clarity
        buttons.append(
            [
                InlineKeyboardButton(
                    f"📜 {name[:12]}", callback_data=f"dlogs:{name[:30]}"
                ),
                InlineKeyboardButton("❤️", callback_data=f"dhealth:{name[:30]}"),
                InlineKeyboardButton("📊", callback_data=f"dstats:{name[:30]}"),
            ]
        )
    # Add refresh button
    buttons.append([InlineKeyboardButton("🔄 Refresh", callback_data="docker:refresh")])
    return InlineKeyboardMarkup(buttons)


def build_torrent_keyboard(torrents: list[dict]) -> InlineKeyboardMarkup:
    """Build inline keyboard with torrent action buttons."""
    buttons = []
    for t in torrents[:6]:  # Limit to 6 torrents for UI clarity
        name = t.get("name", "Unknown")[:20]
        torrent_hash = t.get("hash", "")[:16]
        state = t.get("state", "")

        row = [
            InlineKeyboardButton(f"📁 {name}", callback_data=f"tinfo:{torrent_hash}")
        ]

        # Show pause or resume based on state
        if state in ("downloading", "uploading", "stalledDL", "stalledUP", "queuedDL"):
            row.append(InlineKeyboardButton("⏸️", callback_data=f"tstop:{torrent_hash}"))
        else:
            row.append(
                InlineKeyboardButton("▶️", callback_data=f"tstart:{torrent_hash}")
            )

        buttons.append(row)

    # Add refresh button
    buttons.append(
        [InlineKeyboardButton("🔄 Refresh", callback_data="torrent:refresh")]
    )
    return InlineKeyboardMarkup(buttons)


def build_free_games_keyboard() -> InlineKeyboardMarkup:
    """Build inline keyboard for free games commands."""
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
    """Handle inline keyboard button presses."""
    query = update.callback_query
    await query.answer()

    data = query.data
    chat_id = update.effective_chat.id if update.effective_chat else None

    # Check authorization
    from .. import core

    if chat_id not in core.ALLOWED:
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
        except Exception:
            pass


async def _handle_dlogs_callback(query, container: str) -> None:
    """Show last 20 lines of container logs."""
    await query.message.reply_text(f"🔄 Fetching logs for {container}...")
    msg = await asyncio.to_thread(utils.get_container_logs, container, 20)
    for part in utils.chunk(msg, size=4000):
        await query.message.reply_text(part, parse_mode=ParseMode.HTML)


async def _handle_dhealth_callback(query, container: str) -> None:
    """Show container health status."""
    msg = await asyncio.to_thread(utils.healthcheck_container, container)
    await query.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def _handle_dstats_callback(query, container: str) -> None:
    """Show container stats."""
    msg = await asyncio.to_thread(utils.container_stats_summary)
    # Filter to show only the requested container if possible
    await query.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def _handle_docker_refresh(query, context) -> None:
    """Refresh docker container list with keyboard."""
    state: BotState = get_state(context.application)
    state.refresh_containers()

    msg = await asyncio.to_thread(utils.list_containers_basic)
    containers = list(state.get_cached("containers"))

    keyboard = build_docker_keyboard(containers)
    await query.edit_message_text(
        msg[:4000], parse_mode=ParseMode.HTML, reply_markup=keyboard
    )


async def _handle_torrent_stop(query, torrent_hash: str) -> None:
    """Pause a torrent by hash."""
    result = await asyncio.to_thread(services.torrent_stop_by_hash, torrent_hash)
    await query.message.reply_text(result, parse_mode=ParseMode.HTML)


async def _handle_torrent_start(query, torrent_hash: str) -> None:
    """Resume a torrent by hash."""
    result = await asyncio.to_thread(services.torrent_start_by_hash, torrent_hash)
    await query.message.reply_text(result, parse_mode=ParseMode.HTML)


async def _handle_torrent_info(query, torrent_hash: str) -> None:
    """Show torrent info."""
    result = await asyncio.to_thread(services.torrent_info_by_hash, torrent_hash)
    await query.message.reply_text(result, parse_mode=ParseMode.HTML)


async def _handle_torrent_refresh(query, context) -> None:
    """Refresh torrent list with keyboard."""
    state: BotState = get_state(context.application)
    state.refresh_torrents()

    msg = await asyncio.to_thread(services.torrent_status)
    torrents = await asyncio.to_thread(services.get_torrent_list)

    keyboard = build_torrent_keyboard(torrents)
    await query.edit_message_text(
        msg[:4000], parse_mode=ParseMode.HTML, reply_markup=keyboard
    )


async def _handle_games_callback(query, game_type: str) -> None:
    """Handle free games button press."""
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
        await query.message.reply_photo(
            photo=image_urls[0],
            caption=message,
            parse_mode=ParseMode.HTML,
        )
    else:
        await query.message.reply_text(
            message, parse_mode=ParseMode.HTML, disable_web_page_preview=True
        )
