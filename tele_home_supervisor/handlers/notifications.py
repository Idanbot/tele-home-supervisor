"""Notification command handlers (Epic Games, Hacker News, etc.)."""

from __future__ import annotations

import html
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from .. import intel
from .. import scheduled as scheduled_fetchers
from ..models.reddit_settings import REDDIT_GROUPS, REDDIT_MODES
from ..state import BOT_STATE_KEY, BotState
from .common import guard, tracked_reply_photo

logger = logging.getLogger(__name__)


async def cmd_mute_gameoffers(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Toggle combined Game Offers daily notifications (Epic/Steam/GOG/Giveaways)."""
    if not await guard(update, context):
        return

    state: BotState = context.application.bot_data.setdefault(BOT_STATE_KEY, BotState())
    chat_id = update.effective_chat.id

    is_muted = state.toggle_gameoffers_mute(chat_id)

    if is_muted:
        msg = "🔕 Game Offers daily notifications are now <b>muted</b>.\nYou will no longer receive the 8 PM update."
    else:
        msg = "🔔 Game Offers daily notifications are now <b>enabled</b>.\nYou will receive updates at 8 PM Israel time."

    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_mute_hackernews(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
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


async def cmd_gameoffers_now(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Fetch and display combined game offers on demand (Epic/Steam/GOG/Giveaways)."""
    if not await guard(update, context):
        return

    msg = await update.message.reply_text("🔄 Fetching game offers...")

    try:
        combined, image_url = await scheduled_fetchers.build_combined_game_offers(5)
        if image_url:
            try:
                await msg.delete()
                state: BotState = context.application.bot_data.setdefault(
                    BOT_STATE_KEY, BotState()
                )
                await tracked_reply_photo(
                    update.message,
                    state,
                    photo=image_url,
                    caption=combined,
                    parse_mode=ParseMode.HTML,
                )
                return
            except Exception as img_err:
                logger.warning(
                    "Failed to send game offers image, falling back to text: %s",
                    img_err,
                )
                await update.message.reply_text(
                    combined,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
                return

        await msg.edit_text(
            combined,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.exception("Game Offers fetch failed")
        try:
            await msg.edit_text(f"❌ Error: {html.escape(str(e))}")
        except Exception:
            # If edit fails (message deleted), send new message
            await update.message.reply_text(f"❌ Error: {html.escape(str(e))}")


async def cmd_hackernews_now(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
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
        result = await scheduled_fetchers.fetch_hackernews_top(limit)
        await msg.edit_text(
            result, parse_mode=ParseMode.HTML, disable_web_page_preview=True
        )
    except Exception as e:
        await msg.edit_text(f"❌ Error: {e}")


async def cmd_steamfree_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        message, image_urls = await scheduled_fetchers.fetch_steam_free_games(limit)
        if image_urls:
            await msg.delete()
            state: BotState = context.application.bot_data.setdefault(
                BOT_STATE_KEY, BotState()
            )
            await tracked_reply_photo(
                update.message,
                state,
                photo=image_urls[0],
                caption=message,
                parse_mode=ParseMode.HTML,
            )
        else:
            await msg.edit_text(
                message, parse_mode=ParseMode.HTML, disable_web_page_preview=True
            )
    except Exception as e:
        await msg.edit_text(f"❌ Error: {e}")


async def cmd_epicgames_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fetch and display current Epic Games free games on demand."""
    if not await guard(update, context):
        return

    msg = await update.message.reply_text("🔄 Fetching Epic Games free games...")

    try:
        message, image_urls = await scheduled_fetchers.fetch_epic_free_games()

        # Try to send with image first, fallback to text-only if image fails
        if image_urls:
            try:
                await msg.delete()
                state: BotState = context.application.bot_data.setdefault(
                    BOT_STATE_KEY, BotState()
                )
                await tracked_reply_photo(
                    update.message,
                    state,
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


async def cmd_gogfree_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fetch and display current GOG free games on demand."""
    if not await guard(update, context):
        return

    msg = await update.message.reply_text("🔄 Fetching GOG free games...")

    try:
        message, image_urls = await scheduled_fetchers.fetch_gog_free_games()

        # Delete the "fetching" message
        await msg.delete()

        # Send as photo with caption if image available, otherwise text
        if image_urls:
            state: BotState = context.application.bot_data.setdefault(
                BOT_STATE_KEY, BotState()
            )
            await tracked_reply_photo(
                update.message,
                state,
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


async def cmd_humblefree_now(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Fetch and display active PC game giveaways on demand."""
    if not await guard(update, context):
        return

    msg = await update.message.reply_text("🔄 Fetching game giveaways...")

    try:
        message, image_urls = await scheduled_fetchers.fetch_humble_free_games()

        # Delete the "fetching" message
        await msg.delete()

        # Send as photo with caption if image available, otherwise text
        if image_urls:
            state: BotState = context.application.bot_data.setdefault(
                BOT_STATE_KEY, BotState()
            )
            await tracked_reply_photo(
                update.message,
                state,
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


async def cmd_intel_settings(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Show Intel Briefing module settings."""
    if not await guard(update, context):
        return

    state: BotState = context.application.bot_data.setdefault(BOT_STATE_KEY, BotState())
    chat_id = update.effective_chat.id

    disabled = state.disabled_intel_modules.get(chat_id, set())

    keyboard = []
    for mod_id, label in intel.INTEL_MODULES:
        status = "❌" if mod_id in disabled else "✅"
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"{status} {label}", callback_data=f"intel_toggle:{mod_id}"
                )
            ]
        )

    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = (
        "⚙️ <b>Intel Briefing Settings</b>\n\n"
        "Configure which modules appear in your 8 AM daily report.\n"
        "Click a button to toggle a module."
    )

    await update.message.reply_text(
        msg, parse_mode=ParseMode.HTML, reply_markup=reply_markup
    )


async def cb_intel_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle module toggle from the settings keyboard."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data or not data.startswith("intel_toggle:"):
        return

    mod_id = data.split(":", 1)[1]
    chat_id = update.effective_chat.id
    state: BotState = context.application.bot_data.setdefault(BOT_STATE_KEY, BotState())

    disabled = state.disabled_intel_modules.setdefault(chat_id, set())
    if mod_id in disabled:
        disabled.remove(mod_id)
    else:
        disabled.add(mod_id)

    # Refresh keyboard
    keyboard = []
    for mid, label in intel.INTEL_MODULES:
        status = "❌" if mid in disabled else "✅"
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"{status} {label}", callback_data=f"intel_toggle:{mid}"
                )
            ]
        )

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_reply_markup(reply_markup=reply_markup)
    state.save()


async def cmd_intel_briefing(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Fetch and display Intel Briefing on demand."""
    if not await guard(update, context):
        return

    msg = await update.message.reply_text("🔄 Preparing your intel briefing...")

    try:
        chat_id = update.effective_chat.id
        state: BotState = context.application.bot_data.setdefault(
            BOT_STATE_KEY, BotState()
        )

        result = await intel.build_intel_briefing(chat_id, state)
        await msg.edit_text(
            result, parse_mode=ParseMode.HTML, disable_web_page_preview=True
        )
    except Exception as e:
        logger.exception("Intel Briefing fetch failed")
        await msg.edit_text(f"❌ Error: {html.escape(str(e))}")


def _reddit_settings_text(state: BotState, chat_id: int) -> str:
    settings = state.get_reddit_settings(chat_id)
    groups = ", ".join(
        f"{name}={'on' if name in settings.enabled_groups else 'off'}"
        for name in REDDIT_GROUPS
    )
    custom = (
        ", ".join(f"r/{name}" for name in sorted(settings.custom_subreddits)) or "none"
    )
    return (
        "👽 <b>Reddit Briefing Settings</b>\n"
        f"<b>Groups:</b> {groups}\n"
        f"<b>Custom:</b> {custom}\n"
        f"<b>Posts:</b> {settings.post_count}\n"
        f"<b>Mode:</b> {settings.mode}\n\n"
        "<code>/reddit_settings group fun|tech|devops on|off</code>\n"
        "<code>/reddit_settings add r/subreddit</code>\n"
        "<code>/reddit_settings remove r/subreddit</code>\n"
        "<code>/reddit_settings count 1-5</code>\n"
        "<code>/reddit_settings mode mixed|top|trending|random</code>"
    )


async def cmd_reddit_settings(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Show or update per-chat Reddit briefing preferences."""
    if not await guard(update, context):
        return

    state: BotState = context.application.bot_data.setdefault(BOT_STATE_KEY, BotState())
    chat_id = update.effective_chat.id
    args = context.args
    error: str | None = None

    if args:
        action = args[0].lower()
        if action == "group" and len(args) == 3:
            enabled = args[2].lower() == "on"
            if args[2].lower() not in {"on", "off"} or not state.set_reddit_group(
                chat_id, args[1], enabled
            ):
                error = "Unknown group or state."
        elif action == "add" and len(args) == 2:
            if state.add_reddit_subreddit(chat_id, args[1]) is None:
                error = "Invalid subreddit name."
        elif action == "remove" and len(args) == 2:
            if not state.remove_reddit_subreddit(chat_id, args[1]):
                error = "Custom subreddit was not found."
        elif action == "count" and len(args) == 2:
            try:
                valid = state.set_reddit_post_count(chat_id, int(args[1]))
            except ValueError:
                valid = False
            if not valid:
                error = "Post count must be between 1 and 5."
        elif action == "mode" and len(args) == 2:
            if args[1].lower() not in REDDIT_MODES or not state.set_reddit_mode(
                chat_id, args[1]
            ):
                error = "Mode must be mixed, top, trending, or random."
        else:
            error = "Invalid Reddit settings command."

    text = _reddit_settings_text(state, chat_id)
    if error:
        text = f"❌ {html.escape(error)}\n\n{text}"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)
