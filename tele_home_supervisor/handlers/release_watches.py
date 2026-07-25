"""Commands for persisted one-shot release watches."""

from __future__ import annotations

import html

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from .. import background
from ..models.release_watch import VIDEO_QUALITIES, WATCH_KINDS
from ..state import BOT_STATE_KEY, BotState
from .common import guard_sensitive


def _usage() -> str:
    qualities = "|".join(VIDEO_QUALITIES)
    return (
        "<b>Release Watches</b>\n"
        f"<code>/releasewatch add movie {qualities} &lt;title&gt;</code>\n"
        f"<code>/releasewatch add episode {qualities} &lt;show S01E01&gt;</code>\n"
        "<code>/releasewatch add game &lt;title&gt;</code>\n"
        "<code>/releasewatch remove &lt;id&gt;</code>\n"
        "<code>/releasewatch enable &lt;id&gt;</code>\n"
        "<code>/releasewatch check</code>"
    )


def _list_text(state: BotState, chat_id: int) -> str:
    watches = state.get_release_watches(chat_id)
    if not watches:
        return f"{_usage()}\n\nNo release watches configured."

    lines = [_usage(), "", "<b>Configured:</b>"]
    for watch in watches:
        status = "active" if watch.enabled else "disabled"
        quality = f" · {watch.min_quality}+" if watch.min_quality else ""
        lines.append(
            f"<code>{watch.id}</code> · {status} · {watch.kind}{quality} · "
            f"{html.escape(watch.query)}"
        )
    return "\n".join(lines)


async def cmd_releasewatch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard_sensitive(update, context):
        return

    state: BotState = context.application.bot_data.setdefault(BOT_STATE_KEY, BotState())
    chat_id = update.effective_chat.id
    args = context.args

    if not args:
        await update.message.reply_text(
            _list_text(state, chat_id), parse_mode=ParseMode.HTML
        )
        return

    action = args[0].lower()
    if action == "add":
        await _add_watch(update, state, chat_id, args[1:])
        return
    if action == "remove" and len(args) == 2:
        removed = state.remove_release_watch(chat_id, args[1])
        text = "✅ Release watch removed." if removed else "❌ Release watch not found."
        await update.message.reply_text(text)
        return
    if action == "enable" and len(args) == 2:
        enabled = state.set_release_watch_enabled(chat_id, args[1], True)
        text = "✅ Release watch enabled." if enabled else "❌ Release watch not found."
        await update.message.reply_text(text)
        return
    if action == "check" and len(args) == 1:
        count = await background.check_release_watches(
            context.application, chat_id=chat_id
        )
        await update.message.reply_text(
            f"✅ Release check complete. {count} watch(es) triggered."
        )
        return

    await update.message.reply_text(_usage(), parse_mode=ParseMode.HTML)


async def _add_watch(
    update: Update, state: BotState, chat_id: int, args: list[str]
) -> None:
    if not args or args[0].lower() not in WATCH_KINDS:
        await update.message.reply_text(_usage(), parse_mode=ParseMode.HTML)
        return

    kind = args[0].lower()
    quality: str | None = None
    query_start = 1
    if kind != "game":
        if len(args) < 3 or args[1].lower() not in VIDEO_QUALITIES:
            await update.message.reply_text(_usage(), parse_mode=ParseMode.HTML)
            return
        quality = args[1].lower()
        query_start = 2

    query = " ".join(args[query_start:]).strip()
    watch = state.add_release_watch(chat_id, kind, query, quality)
    if watch is None:
        await update.message.reply_text(_usage(), parse_mode=ParseMode.HTML)
        return

    quality_text = f" at {watch.min_quality} or better" if watch.min_quality else ""
    await update.message.reply_text(
        f"✅ Watching <b>{html.escape(watch.query)}</b>{quality_text}.\n"
        f"ID: <code>{watch.id}</code>",
        parse_mode=ParseMode.HTML,
    )
