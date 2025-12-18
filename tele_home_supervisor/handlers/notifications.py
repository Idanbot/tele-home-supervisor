"""Notification command handlers (Epic Games, Hacker News, etc.)."""

from __future__ import annotations

import asyncio
import html
import logging

from telegram.constants import ParseMode

from .. import scheduled as scheduled_fetchers
from ..state import BOT_STATE_KEY, BotState
from .common import guard

logger = logging.getLogger(__name__)


async def cmd_mute_epicgames(update, context) -> None:
    """Toggle Epic Games daily notifications."""
    if not await guard(update, context):
        return

    state: BotState = context.application.bot_data.setdefault(BOT_STATE_KEY, BotState())
    chat_id = update.effective_chat.id

    is_muted = state.toggle_epic_games_mute(chat_id)

    if is_muted:
        msg = "🔕 Epic Games daily notifications are now <b>muted</b>.\nYou will no longer receive the 8 PM update."
    else:
        msg = "🔔 Epic Games daily notifications are now <b>enabled</b>.\nYou will receive updates at 8 PM Israel time."

    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_mute_hackernews(update, context) -> None:
    """Toggle Hacker News daily digest."""
    if not await guard(update, context):
        return

    state: BotState = context.application.bot_data.setdefault(BOT_STATE_KEY, BotState())
    chat_id = update.effective_chat.id

    is_muted = state.toggle_hackernews_mute(chat_id)

    if is_muted:
        msg = "🔕 Hacker News daily digest is now <b>muted</b>.\nYou will no longer receive the 8 AM update."
    else:
        msg = "🔔 Hacker News daily digest is now <b>enabled</b>.\nYou will receive updates at 8 AM Israel time."

    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_epicgames_now(update, context) -> None:
    """Fetch and display current Epic Games free games on demand."""
    if not await guard(update, context):
        return

    msg = await update.message.reply_text("🔄 Fetching Epic Games free games...")

    try:
        message, image_urls = await asyncio.to_thread(
            scheduled_fetchers.fetch_epic_free_games
        )

        # Try to send with image first, fallback to text-only if image fails
        if image_urls:
            try:
                await msg.delete()
                await update.message.reply_photo(
                    photo=image_urls[0],
                    caption=message,
                    parse_mode=ParseMode.HTML,
                )
                return
            except Exception as img_err:
                logger.warning(
                    f"Failed to send Epic image, falling back to text: {img_err}"
                )
                # Message was deleted, need to send a new one
                await update.message.reply_text(
                    message,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
                return

        # No images available, edit existing message
        await msg.edit_text(
            message,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.exception("Epic Games fetch failed")
        try:
            await msg.edit_text(f"❌ Error: {html.escape(str(e))}")
        except Exception:
            # If edit fails (message deleted), send new message
            await update.message.reply_text(f"❌ Error: {html.escape(str(e))}")


async def cmd_hackernews_now(update, context) -> None:
    """Fetch and display top Hacker News stories on demand."""
    if not await guard(update, context):
        return

    # Parse optional limit argument
    limit = 5
    if context.args:
        try:
            limit = int(context.args[0])
            limit = max(1, min(limit, 10))  # Clamp between 1-10
        except ValueError:
            await update.message.reply_text(
                "Usage: /hackernews [n]\nWhere n is between 1-10"
            )
            return

    msg = await update.message.reply_text(
        f"🔄 Fetching top {limit} Hacker News stories..."
    )

    try:
        result = await asyncio.to_thread(scheduled_fetchers.fetch_hackernews_top, limit)
        await msg.edit_text(
            result, parse_mode=ParseMode.HTML, disable_web_page_preview=True
        )
    except Exception as e:
        await msg.edit_text(f"❌ Error: {e}")


async def cmd_steamfree_now(update, context) -> None:
    """Fetch and display current Steam free-to-keep games on demand."""
    if not await guard(update, context):
        return

    limit = 5
    if context.args:
        try:
            limit = max(1, min(int(context.args[0]), 10))
        except ValueError:
            await update.message.reply_text(
                "Usage: /steamfree [n]\nWhere n is between 1-10",
                parse_mode=ParseMode.HTML,
            )
            return

    msg = await update.message.reply_text("🔄 Fetching Steam free-to-keep games...")

    try:
        result = await asyncio.to_thread(
            scheduled_fetchers.fetch_steam_free_games, limit
        )
        await msg.edit_text(
            result, parse_mode=ParseMode.HTML, disable_web_page_preview=True
        )
    except Exception as e:
        await msg.edit_text(f"❌ Error: {e}")


async def cmd_gogfree_now(update, context) -> None:
    """Fetch and display current GOG free games on demand."""
    if not await guard(update, context):
        return

    msg = await update.message.reply_text("🔄 Fetching GOG free games...")

    try:
        message, image_urls = await asyncio.to_thread(
            scheduled_fetchers.fetch_gog_free_games
        )

        # Delete the "fetching" message
        await msg.delete()

        # Send as photo with caption if image available, otherwise text
        if image_urls:
            await update.message.reply_photo(
                photo=image_urls[0],
                caption=message,
                parse_mode=ParseMode.HTML,
            )
        else:
            await update.message.reply_text(
                message,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
    except Exception as e:
        await msg.edit_text(f"❌ Error: {e}")


async def cmd_humblefree_now(update, context) -> None:
    """Fetch and display current Humble Bundle free games on demand."""
    if not await guard(update, context):
        return

    msg = await update.message.reply_text("🔄 Fetching Humble Bundle free games...")

    try:
        message, image_urls = await asyncio.to_thread(
            scheduled_fetchers.fetch_humble_free_games
        )

        # Delete the "fetching" message
        await msg.delete()

        # Send as photo with caption if image available, otherwise text
        if image_urls:
            await update.message.reply_photo(
                photo=image_urls[0],
                caption=message,
                parse_mode=ParseMode.HTML,
            )
        else:
            await update.message.reply_text(
                message,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
    except Exception as e:
        await msg.edit_text(f"❌ Error: {e}")
