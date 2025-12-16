from __future__ import annotations

import asyncio
import html

from telegram.constants import ParseMode

from .. import services, utils
from ..background import ensure_started
from ..state import BotState
from .common import guard, get_state, reply_usage_with_suggestions


async def cmd_torrent_add(update, context) -> None:
    """Add a torrent to qBittorrent (magnet/URL).

    Usage: /tadd <torrent> [save_path]
    """
    if not await guard(update, context):
        return
    if not context.args:
        await update.message.reply_text(
            "Usage: /tadd &lt;torrent&gt; [save_path]", parse_mode=ParseMode.HTML
        )
        return
    torrent = context.args[0]
    save_path = context.args[1] if len(context.args) > 1 else "/downloads"
    res = await asyncio.to_thread(services.torrent_add, torrent, save_path)
    await update.message.reply_text(res, parse_mode=ParseMode.HTML)


async def cmd_torrent_status(update, context) -> None:
    if not await guard(update, context):
        return
    try:
        get_state(context.application).refresh_torrents()
    except Exception:
        pass
    msg = await asyncio.to_thread(services.torrent_status)
    for part in utils.chunk(msg, size=4000):
        await update.message.reply_text(part, parse_mode=ParseMode.HTML)


async def cmd_torrent_stop(update, context) -> None:
    if not await guard(update, context):
        return
    state: BotState = get_state(context.application)
    state.maybe_refresh("torrents")
    if not context.args:
        await reply_usage_with_suggestions(
            update, "/tstop &lt;torrent&gt;", state.suggest("torrents", limit=5)
        )
        return
    name = " ".join(context.args)
    res = await asyncio.to_thread(services.torrent_stop, name)
    await update.message.reply_text(res, parse_mode=ParseMode.HTML)


async def cmd_torrent_start(update, context) -> None:
    if not await guard(update, context):
        return
    state: BotState = get_state(context.application)
    state.maybe_refresh("torrents")
    if not context.args:
        await reply_usage_with_suggestions(
            update, "/tstart &lt;torrent&gt;", state.suggest("torrents", limit=5)
        )
        return
    name = " ".join(context.args)
    res = await asyncio.to_thread(services.torrent_start, name)
    await update.message.reply_text(res, parse_mode=ParseMode.HTML)


async def cmd_torrent_delete(update, context) -> None:
    if not await guard(update, context):
        return
    state: BotState = get_state(context.application)
    state.maybe_refresh("torrents")
    if not context.args:
        await reply_usage_with_suggestions(
            update, "/tdelete &lt;torrent&gt; yes", state.suggest("torrents", limit=5)
        )
        return

    confirm_tokens = {"yes", "--yes", "confirm", "--confirm"}
    confirm = bool(context.args and context.args[-1].strip().lower() in confirm_tokens)
    name = " ".join(context.args[:-1] if confirm else context.args).strip()
    if not name:
        await reply_usage_with_suggestions(
            update, "/tdelete &lt;torrent&gt; yes", state.suggest("torrents", limit=5)
        )
        return

    if not confirm:
        matches_msg = await asyncio.to_thread(services.torrent_preview, name)
        hint_names = state.suggest("torrents", query=name, limit=5)
        hint = ""
        if hint_names:
            hint = "\n\n<i>Suggestions:</i>\n" + "\n".join(
                f"• <code>{html.escape(n)}</code>" for n in hint_names
            )
        msg = (
            f"{matches_msg}\n\n"
            f"⚠️ This will <b>delete files</b>. Re-run to confirm:\n"
            f"<code>/tdelete {html.escape(name)} yes</code>"
            f"{hint}"
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
        return

    res = await asyncio.to_thread(services.torrent_delete, name)
    await update.message.reply_text(res, parse_mode=ParseMode.HTML)


async def cmd_subscribe(update, context) -> None:
    if not await guard(update, context):
        return
    chat_id = update.effective_chat.id if update and update.effective_chat else None
    if chat_id is None:
        return

    try:
        ensure_started(context.application)
    except Exception:
        pass

    args = [a.strip().lower() for a in (context.args or []) if a.strip()]
    if args and args[0] in {"torrent", "torrents", "t"}:
        args = args[1:]
    action = args[0] if args else "toggle"

    state: BotState = get_state(context.application)
    if action == "status":
        is_on = state.torrent_completion_enabled(chat_id)
        await update.message.reply_text(
            f"Torrent completion notifications: <b>{'ON' if is_on else 'OFF'}</b>",
            parse_mode=ParseMode.HTML,
        )
        return

    enable: bool | None
    if action in {"toggle"}:
        enable = None
    elif action in {"on", "yes", "true", "1"}:
        enable = True
    elif action in {"off", "no", "false", "0"}:
        enable = False
    else:
        await update.message.reply_text(
            "Usage: /subscribe [on|off|status]", parse_mode=ParseMode.HTML
        )
        return

    is_on = state.set_torrent_completion_subscription(chat_id, enable)
    await update.message.reply_text(
        f"Torrent completion notifications: <b>{'ON' if is_on else 'OFF'}</b>",
        parse_mode=ParseMode.HTML,
    )
