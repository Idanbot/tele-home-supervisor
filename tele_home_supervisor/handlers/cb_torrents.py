"""Callback handlers for torrent management."""

from __future__ import annotations

import math

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from .. import services, view
from ..state import BotState
from .common import get_state
from .cb_helpers import safe_edit_message_text, build_pagination_row

TORRENT_PAGE_SIZE = 6


# ---------------------------------------------------------------------------
# Pagination helpers
# ---------------------------------------------------------------------------


def normalize_torrent_page(total_items: int, page: int) -> tuple[int, int]:
    total_pages = max(1, math.ceil(total_items / TORRENT_PAGE_SIZE))
    page = max(0, min(page, total_pages - 1))
    return page, total_pages


def paginate_torrents(torrents: list[dict], page: int) -> tuple[list[dict], int, int]:
    page, total_pages = normalize_torrent_page(len(torrents), page)
    start = page * TORRENT_PAGE_SIZE
    end = start + TORRENT_PAGE_SIZE
    return torrents[start:end], page, total_pages


# ---------------------------------------------------------------------------
# Keyboard builder
# ---------------------------------------------------------------------------


def build_torrent_keyboard(torrents: list[dict], page: int = 0) -> InlineKeyboardMarkup:
    """Build inline keyboard with torrent action buttons."""
    buttons = []
    page_torrents, page, total_pages = paginate_torrents(torrents, page)
    for t in page_torrents:
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

        row.append(InlineKeyboardButton("🗑️", callback_data=f"tdelete:{torrent_hash}"))

        buttons.append(row)

    nav_row = build_pagination_row(page, total_pages, "torrent:page")
    if nav_row:
        buttons.append(nav_row)

    buttons.append(
        [InlineKeyboardButton("🔄 Refresh", callback_data=f"torrent:refresh:{page}")]
    )
    return InlineKeyboardMarkup(buttons)


# ---------------------------------------------------------------------------
# Callback handlers
# ---------------------------------------------------------------------------


async def handle_torrent_stop(query, context, torrent_hash: str) -> None:
    if not await _validate_torrent_hash(context, torrent_hash):
        await query.message.reply_text("❌ Unknown torrent.")
        return
    result = await services.torrent_stop_by_hash(torrent_hash)
    await query.message.reply_text(result, parse_mode=ParseMode.HTML)


async def handle_torrent_start(query, context, torrent_hash: str) -> None:
    if not await _validate_torrent_hash(context, torrent_hash):
        await query.message.reply_text("❌ Unknown torrent.")
        return
    result = await services.torrent_start_by_hash(torrent_hash)
    await query.message.reply_text(result, parse_mode=ParseMode.HTML)


async def handle_torrent_info(query, context, torrent_hash: str) -> None:
    if not await _validate_torrent_hash(context, torrent_hash):
        await query.message.reply_text("❌ Unknown torrent.")
        return
    result = await services.torrent_info_by_hash(torrent_hash)
    await query.message.reply_text(result, parse_mode=ParseMode.HTML)


async def handle_torrent_delete(query, context, torrent_hash: str) -> None:
    if not await _validate_torrent_hash(context, torrent_hash):
        await query.message.reply_text("❌ Unknown torrent.")
        return
    result = await services.torrent_delete_by_hash(torrent_hash, delete_files=True)
    await query.message.reply_text(result, parse_mode=ParseMode.HTML)


async def handle_torrent_refresh(query, context, page: int) -> None:
    await _update_torrent_message(query, context, page=page, refresh=True)


async def handle_torrent_page(query, context, page: int) -> None:
    await _update_torrent_message(query, context, page=page, refresh=False)


async def _update_torrent_message(query, context, page: int, refresh: bool) -> None:
    state: BotState = get_state(context.application)
    if refresh:
        await state.refresh_torrents()
    else:
        await state.maybe_refresh("torrents")

    torrents = await services.get_torrent_list()
    page_torrents, page, total_pages = paginate_torrents(torrents, page)
    msg = view.render_torrent_list_page(page_torrents, page, total_pages)
    keyboard = build_torrent_keyboard(torrents, page=page) if torrents else None

    await safe_edit_message_text(
        query, msg[:4000], parse_mode=ParseMode.HTML, reply_markup=keyboard
    )


async def _validate_torrent_hash(context, torrent_hash: str) -> bool:
    state: BotState = get_state(context.application)
    await state.maybe_refresh("torrents")
    torrents = await services.get_torrent_list()
    return any(
        (t.get("hash") or "").startswith(torrent_hash)
        for t in torrents
        if t.get("hash")
    )
