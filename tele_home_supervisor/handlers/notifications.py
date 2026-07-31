"""Notification command handlers (Epic Games, Hacker News, etc.)."""

from __future__ import annotations

import html
import inspect
import logging
from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from .. import intel, reddit_briefing
from .. import scheduled as scheduled_fetchers
from ..models.reddit_settings import (
    REDDIT_FETCH_SUBREDDITS,
    REDDIT_GROUPS,
    REDDIT_MODES,
    normalize_subreddit,
)
from ..state import BOT_STATE_KEY, BotState
from .common import guard, tracked_reply_photo, tracked_reply_video, tracked_reply_voice

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


def build_intel_settings_view(
    chat_id: int, state: BotState
) -> tuple[str, InlineKeyboardMarkup]:
    now_israel = datetime.now(ZoneInfo("Asia/Jerusalem")).strftime("%H:%M")
    fire_h, fire_m = state.get_intel_fire_time(chat_id)
    fire_str = f"{fire_h:02d}:{fire_m:02d}"
    tts_on = state.is_tts_announcer_enabled(chat_id)
    tts_status = "✅ ON" if tts_on else "❌ OFF"
    disabled = state.disabled_intel_modules.get(chat_id, set())

    msg = (
        "⚙️ <b>Intel Briefing Settings</b>\n\n"
        f"🕒 <b>Current Israel Time:</b> {now_israel}\n"
        f"⏰ <b>Scheduled Fire Time:</b> {fire_str} Israel time\n"
        f"🎙️ <b>TTS Announcer:</b> {tts_status}\n\n"
        "Configure modules, scheduled fire time, or TTS audio below:"
    )

    keyboard = []
    # Module toggles (2 per row)
    mod_row = []
    for mid, label in intel.INTEL_MODULES:
        status = "❌" if mid in disabled else "✅"
        mod_row.append(
            InlineKeyboardButton(
                f"{status} {label}", callback_data=f"intel_toggle:{mid}"
            )
        )
        if len(mod_row) == 2:
            keyboard.append(mod_row)
        # TTS Announcer Toggle & TTS Section Settings Nav
    keyboard.append(
        [
            InlineKeyboardButton(
                f"🎙️ TTS Announcer: {tts_status}", callback_data="intel_toggle_tts"
            ),
            InlineKeyboardButton("🗣️ TTS Sections", callback_data="intel_nav_tts"),
        ]
    )

    # Time Adjustments
    keyboard.append(
        [
            InlineKeyboardButton("➖ 1h", callback_data="intel_time:-60"),
            InlineKeyboardButton("➖ 15m", callback_data="intel_time:-15"),
            InlineKeyboardButton("➕ 15m", callback_data="intel_time:+15"),
            InlineKeyboardButton("➕ 1h", callback_data="intel_time:+60"),
        ]
    )

    # Time Presets
    keyboard.append(
        [
            InlineKeyboardButton("07:00", callback_data="intel_time_set:07:00"),
            InlineKeyboardButton("08:00 (Def)", callback_data="intel_time_set:08:00"),
            InlineKeyboardButton("09:00", callback_data="intel_time_set:09:00"),
            InlineKeyboardButton("20:00", callback_data="intel_time_set:20:00"),
        ]
    )

    return msg, InlineKeyboardMarkup(keyboard)


def build_tts_settings_view(
    chat_id: int, state: BotState
) -> tuple[str, InlineKeyboardMarkup]:
    disabled = state.get_disabled_tts_sections(chat_id)
    tts_enabled = state.is_tts_announcer_enabled(chat_id)
    tts_status = "✅ Enabled" if tts_enabled else "❌ Disabled"

    msg = (
        "🎙️ <b>TTS Announcer Settings</b>\n\n"
        f"<b>Global TTS Announcer:</b> {tts_status}\n\n"
        "Toggle which sections are included when building speech narration for text-to-speech audio:"
    )

    keyboard = []
    sec_row = []
    for sec_id, label in intel.TTS_SECTIONS:
        status = "❌" if sec_id in disabled else "✅"
        sec_row.append(
            InlineKeyboardButton(
                f"{status} {label}", callback_data=f"tts_sec_toggle:{sec_id}"
            )
        )
        if len(sec_row) == 2:
            keyboard.append(sec_row)
            sec_row = []
    if sec_row:
        keyboard.append(sec_row)

    keyboard.append(
        [
            InlineKeyboardButton(
                f"🎙️ Toggle TTS Announcer: {tts_status}",
                callback_data="intel_toggle_tts",
            )
        ]
    )
    keyboard.append(
        [
            InlineKeyboardButton(
                "⚙️ Back to Intel Settings", callback_data="intel_nav_settings"
            )
        ]
    )

    return msg, InlineKeyboardMarkup(keyboard)


async def cmd_intel_settings(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Show Intel Briefing module settings."""
    if not await guard(update, context):
        return

    state: BotState = context.application.bot_data.setdefault(BOT_STATE_KEY, BotState())
    chat_id = update.effective_chat.id

    msg, reply_markup = build_intel_settings_view(chat_id, state)
    await update.message.reply_text(
        msg, parse_mode=ParseMode.HTML, reply_markup=reply_markup
    )


async def cmd_tts_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show TTS Announcer speech section settings."""
    if not await guard(update, context):
        return

    state: BotState = context.application.bot_data.setdefault(BOT_STATE_KEY, BotState())
    chat_id = update.effective_chat.id

    msg, reply_markup = build_tts_settings_view(chat_id, state)
    await update.message.reply_text(
        msg, parse_mode=ParseMode.HTML, reply_markup=reply_markup
    )


async def cb_intel_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle module toggle, fire time adjustment, or TTS toggle from settings keyboard."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data or (
        not data.startswith("intel_") and not data.startswith("tts_sec_toggle:")
    ):
        return

    chat_id = update.effective_chat.id
    state: BotState = context.application.bot_data.setdefault(BOT_STATE_KEY, BotState())

    view_mode = "intel"

    if data.startswith("intel_toggle:"):
        mod_id = data.split(":", 1)[1]
        disabled = state.disabled_intel_modules.setdefault(chat_id, set())
        if mod_id in disabled:
            disabled.remove(mod_id)
        else:
            disabled.add(mod_id)
        state.save()
    elif data == "intel_toggle_tts":
        state.toggle_tts_announcer(chat_id)
    elif data.startswith("tts_sec_toggle:"):
        sec_id = data.split(":", 1)[1]
        state.toggle_tts_section(chat_id, sec_id)
        view_mode = "tts"
    elif data == "intel_nav_tts":
        view_mode = "tts"
    elif data == "intel_nav_settings":
        view_mode = "intel"
    elif data.startswith("intel_time:"):
        delta_m = int(data.split(":", 1)[1])
        h, m = state.get_intel_fire_time(chat_id)
        total_m = (h * 60 + m + delta_m) % (24 * 60)
        state.set_intel_fire_time(chat_id, total_m // 60, total_m % 60)
    elif data.startswith("intel_time_set:"):
        time_part = data.split(":", 1)[1]
        parts = time_part.split(":")
        state.set_intel_fire_time(chat_id, int(parts[0]), int(parts[1]))

    if view_mode == "tts":
        msg, reply_markup = build_tts_settings_view(chat_id, state)
    else:
        msg, reply_markup = build_intel_settings_view(chat_id, state)

    try:
        res = query.edit_message_text(
            msg, parse_mode=ParseMode.HTML, reply_markup=reply_markup
        )
        if inspect.isawaitable(res):
            await res
    except AttributeError, TypeError:
        if hasattr(query, "edit_message_reply_markup"):
            res = query.edit_message_reply_markup(reply_markup=reply_markup)
            if inspect.isawaitable(res):
                await res


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

        # Check if TTS announcer is enabled for this chat
        if state.is_tts_announcer_enabled(chat_id):
            tts_status = await update.message.reply_text(
                "🎙️ Generating TTS narration audio via Cloudflare AI..."
            )
            raw_text = await intel.build_tts_announcer_raw_text(chat_id, state)
            audio_bytes = await intel.generate_tts_announcer_audio(raw_text)
            if audio_bytes:
                voice_file = BytesIO(audio_bytes)
                voice_file.name = "intel_narration.ogg"
                if tts_status:
                    try:
                        await tts_status.delete()
                    except Exception as exc:
                        logger.debug("Failed to delete tts status: %s", exc)
                await tracked_reply_voice(
                    update.message,
                    state,
                    voice=voice_file,
                    caption="🗣️ Morning Intel Briefing",
                )
            else:
                if tts_status:
                    await tts_status.edit_text("❌ Failed to generate TTS audio.")
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


async def cmd_reddit_fetch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fetch one Reddit post or show the curated subreddit picker."""
    if not await guard(update, context):
        return

    if not context.args:
        rows: list[list[InlineKeyboardButton]] = []
        for index in range(0, len(REDDIT_FETCH_SUBREDDITS), 2):
            rows.append(
                [
                    InlineKeyboardButton(
                        label,
                        callback_data=f"reddit_fetch:pick:{subreddit}",
                    )
                    for label, subreddit in REDDIT_FETCH_SUBREDDITS[index : index + 2]
                ]
            )
        await update.message.reply_text(
            "👽 Choose a subreddit",
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return

    subreddit = normalize_subreddit(context.args[0])
    mode = context.args[1].lower() if len(context.args) == 2 else "trending"
    if (
        subreddit is None
        or len(context.args) > 2
        or mode not in reddit_briefing.REDDIT_FETCH_MODES
    ):
        await update.message.reply_text(
            "Usage: /reddit_fetch <subreddit> [trending|random|top]"
        )
        return

    await _fetch_and_deliver_reddit_post(update.message, context, subreddit, mode)


async def _fetch_and_deliver_reddit_post(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    subreddit: str,
    mode: str,
) -> None:
    try:
        post = await reddit_briefing.fetch_reddit_post(subreddit, mode)
        caption = reddit_briefing.format_reddit_post(post)
        state: BotState = context.application.bot_data.setdefault(
            BOT_STATE_KEY, BotState()
        )
        media_kind = reddit_briefing.reddit_post_media_kind(post)
        if media_kind == "photo":
            try:
                await tracked_reply_photo(
                    message,
                    state,
                    photo=str(post.get("media_url") or post.get("url")),
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                )
                return
            except Exception as exc:
                logger.warning("Reddit photo delivery failed, using text: %s", exc)
        elif media_kind == "video":
            try:
                await tracked_reply_video(
                    message,
                    state,
                    video=str(post.get("media_url") or post.get("url")),
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                )
                return
            except Exception as exc:
                logger.warning("Reddit video delivery failed, using text: %s", exc)
        await message.reply_text(
            caption,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=False,
        )
    except (httpx.HTTPError, LookupError, ValueError) as exc:
        await message.reply_text(
            f"❌ Reddit fetch failed: {html.escape(str(exc))}",
            parse_mode=ParseMode.HTML,
        )


async def handle_reddit_fetch_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle the subreddit and mode pickers for ``/reddit_fetch``."""
    query = update.callback_query
    parts = str(query.data or "").split(":")
    if len(parts) == 3 and parts[:2] == ["reddit_fetch", "pick"]:
        subreddit = normalize_subreddit(parts[2])
        if subreddit is None:
            await query.edit_message_text("❌ Invalid subreddit.")
            return
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        mode.title(),
                        callback_data=f"reddit_fetch:run:{subreddit}:{mode}",
                    )
                    for mode in ("trending", "random", "top")
                ]
            ]
        )
        await query.edit_message_text(
            f"👽 Choose a mode for r/{html.escape(subreddit)}",
            reply_markup=keyboard,
        )
        return

    if len(parts) == 4 and parts[:2] == ["reddit_fetch", "run"]:
        subreddit = normalize_subreddit(parts[2])
        mode = parts[3].lower()
        if subreddit is None or mode not in reddit_briefing.REDDIT_FETCH_MODES:
            await query.edit_message_text("❌ Invalid Reddit fetch selection.")
            return
        await query.edit_message_text(
            f"🔄 Fetching r/{html.escape(subreddit)} ({html.escape(mode)})..."
        )
        await _fetch_and_deliver_reddit_post(
            query.message,
            context,
            subreddit,
            mode,
        )
