from __future__ import annotations

import html
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from .. import piratebay, services, view
from ..background import ensure_started
from ..state import BotState
from .common import guard_sensitive, get_state, reply_usage_with_suggestions
from .callbacks import build_torrent_keyboard

logger = logging.getLogger(__name__)


def _has_torrent_match(names: set[str], query: str) -> bool:
    if not names:
        return True
    target = query.strip().lower()
    if not target:
        return False
    return any(target in n.lower() for n in names)


async def cmd_torrent_add(update, context) -> None:
    """Add a torrent to qBittorrent (magnet/URL)."""
    if not await guard_sensitive(update, context):
        return
    if not context.args:
        await update.message.reply_text(
            "Usage: /tadd <torrent> [save_path]", parse_mode=ParseMode.HTML
        )
        return
    torrent = context.args[0]
    save_path = context.args[1] if len(context.args) > 1 else "/downloads"
    res = await services.torrent_add(torrent, save_path)
    await update.message.reply_text(res, parse_mode=ParseMode.HTML)


async def cmd_torrent_status(update, context) -> None:
    if not await guard_sensitive(update, context):
        return
    try:
        await get_state(context.application).refresh_torrents()
    except Exception as e:
        logger.debug("refresh_torrents failed: %s", e)

    torrents = await services.get_torrent_list()
    msg = view.render_torrent_list(torrents)
    keyboard = build_torrent_keyboard(torrents) if torrents else None

    parts = view.chunk(msg)
    for i, part in enumerate(parts):
        if i == len(parts) - 1 and keyboard:
            await update.message.reply_text(
                part, parse_mode=ParseMode.HTML, reply_markup=keyboard
            )
        else:
            await update.message.reply_text(part, parse_mode=ParseMode.HTML)


async def cmd_torrent_stop(update, context) -> None:
    if not await guard_sensitive(update, context):
        return
    state: BotState = get_state(context.application)
    await state.maybe_refresh("torrents")
    if not context.args:
        await reply_usage_with_suggestions(
            update, "/tstop <torrent>", state.suggest("torrents", limit=5)
        )
        return
    name = " ".join(context.args)
    if not _has_torrent_match(state.get_cached("torrents"), name):
        await reply_usage_with_suggestions(
            update, "/tstop <torrent>", state.suggest("torrents", query=name, limit=5)
        )
        return
    res = await services.torrent_stop(name)
    await update.message.reply_text(res, parse_mode=ParseMode.HTML)


async def cmd_torrent_start(update, context) -> None:
    if not await guard_sensitive(update, context):
        return
    state: BotState = get_state(context.application)
    await state.maybe_refresh("torrents")
    if not context.args:
        await reply_usage_with_suggestions(
            update, "/tstart <torrent>", state.suggest("torrents", limit=5)
        )
        return
    name = " ".join(context.args)
    if not _has_torrent_match(state.get_cached("torrents"), name):
        await reply_usage_with_suggestions(
            update, "/tstart <torrent>", state.suggest("torrents", query=name, limit=5)
        )
        return
    res = await services.torrent_start(name)
    await update.message.reply_text(res, parse_mode=ParseMode.HTML)


async def cmd_torrent_delete(update, context) -> None:
    if not await guard_sensitive(update, context):
        return
    state: BotState = get_state(context.application)
    await state.maybe_refresh("torrents")
    if not context.args:
        await reply_usage_with_suggestions(
            update, "/tdelete <torrent> yes", state.suggest("torrents", limit=5)
        )
        return

    confirm_tokens = {"yes", "--yes", "confirm", "--confirm"}
    confirm = bool(context.args and context.args[-1].strip().lower() in confirm_tokens)
    name = " ".join(context.args[:-1] if confirm else context.args).strip()
    if not name:
        await reply_usage_with_suggestions(
            update, "/tdelete <torrent> yes", state.suggest("torrents", limit=5)
        )
        return

    if not confirm:
        matches_msg = await services.torrent_preview(name)
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

    if not _has_torrent_match(state.get_cached("torrents"), name):
        await reply_usage_with_suggestions(
            update,
            "/tdelete <torrent> yes",
            state.suggest("torrents", query=name, limit=5),
        )
        return
    res = await services.torrent_delete(name)
    await update.message.reply_text(res, parse_mode=ParseMode.HTML)


async def cmd_subscribe(update, context) -> None:
    if not await guard_sensitive(update, context):
        return
    chat_id = update.effective_chat.id if update and update.effective_chat else None
    if chat_id is None:
        return

    try:
        ensure_started(context.application)
    except Exception as e:
        logger.debug("ensure_started failed: %s", e)

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


def _build_piratebay_keyboard(
    state: BotState, results: list[dict[str, object]]
) -> InlineKeyboardMarkup | None:
    buttons = []
    for idx, item in enumerate(results, start=1):
        name = str(item.get("name", "Unknown"))
        seeds = int(item.get("seeders", 0))
        magnet = str(item.get("magnet", ""))
        if not magnet:
            continue
        key = state.store_magnet(name, magnet)
        label = f"{idx}. {name} ({seeds})"
        if len(label) > 60:
            label = f"{label[:57]}..."
        buttons.append([InlineKeyboardButton(label, callback_data=f"pbmagnet:{key}")])
    if not buttons:
        return None
    return InlineKeyboardMarkup(buttons)


def _format_piratebay_list(title: str, results: list[dict[str, object]]) -> str:
    lines = [f"<b>{html.escape(title)}</b>"]
    for idx, item in enumerate(results, start=1):
        name = html.escape(str(item.get("name", "Unknown")))
        seeds = int(item.get("seeders", 0))
        leech = int(item.get("leechers", 0))
        lines.append(f"{idx}. {name} - {seeds} seeds / {leech} leech")
    return "\n".join(lines)


async def cmd_pbtop(update, context) -> None:
    if not await guard_sensitive(update, context):
        return
    category = context.args[0] if context.args else None
    if category and piratebay.resolve_category(category) is None:
        usage = f"Usage: /pbtop [category]\nCategories: {piratebay.category_help()}"
        await update.message.reply_text(usage, parse_mode=ParseMode.HTML)
        return

    try:
        results = await services.piratebay_top(category)
    except Exception as e:
        logger.exception("Pirate Bay top failed")
        await update.message.reply_text(f"❌ Error: {html.escape(str(e))}")
        return

    if not results:
        await update.message.reply_text("No results found.")
        return

    state = get_state(context.application)
    title = "Pirate Bay Top 10"
    if category:
        title = f"Pirate Bay Top 10 ({category})"
    msg = _format_piratebay_list(title, results)
    keyboard = _build_piratebay_keyboard(state, results)
    await update.message.reply_text(
        msg, parse_mode=ParseMode.HTML, reply_markup=keyboard
    )


async def cmd_pbsearch(update, context) -> None:
    if not await guard_sensitive(update, context):
        return
    if not context.args:
        await update.message.reply_text(
            "Usage: /pbsearch <query>", parse_mode=ParseMode.HTML
        )
        return
    query = " ".join(context.args).strip()
    if not query:
        await update.message.reply_text(
            "Usage: /pbsearch <query>", parse_mode=ParseMode.HTML
        )
        return

    try:
        results = await services.piratebay_search(query)
    except Exception as e:
        logger.exception("Pirate Bay search failed")
        await update.message.reply_text(f"❌ Error: {html.escape(str(e))}")
        return

    if not results:
        await update.message.reply_text("No results found.")
        return

    state = get_state(context.application)
    title = f"Pirate Bay Search: {query}"
    msg = _format_piratebay_list(title, results)
    keyboard = _build_piratebay_keyboard(state, results)
    await update.message.reply_text(
        msg, parse_mode=ParseMode.HTML, reply_markup=keyboard
    )
