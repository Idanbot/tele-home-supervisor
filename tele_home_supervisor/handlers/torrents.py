from __future__ import annotations

import html
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from .. import piratebay, services, torrentsources, view
from ..background import ensure_started
from ..state import BotState
from .common import (
    guard_sensitive,
    get_state,
    get_state_and_recorder,
    record_error,
    reply_usage_with_suggestions,
    set_audit_target,
)
from .callbacks import build_torrent_keyboard, paginate_torrents

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
    set_audit_target(context, "torrent_add")
    res = await services.torrent_add(torrent, save_path)

    state = get_state(context.application)
    chat_id = update.effective_chat.id
    if not state.torrent_completion_enabled(chat_id):
        state.set_torrent_completion_subscription(chat_id, True)

    await update.message.reply_text(res, parse_mode=ParseMode.HTML)


async def cmd_torrent_status(update, context) -> None:
    if not await guard_sensitive(update, context):
        return
    try:
        await get_state(context.application).refresh_torrents()
    except Exception as e:
        logger.debug("refresh_torrents failed: %s", e)

    torrents = await services.get_torrent_list()
    page_torrents, page, total_pages = paginate_torrents(torrents, 0)
    msg = view.render_torrent_list_page(page_torrents, page, total_pages)
    keyboard = build_torrent_keyboard(torrents, page=page) if torrents else None

    await update.message.reply_text(
        msg[:4000], parse_mode=ParseMode.HTML, reply_markup=keyboard
    )


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
    set_audit_target(context, name)
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
    set_audit_target(context, name)
    if not _has_torrent_match(state.get_cached("torrents"), name):
        await reply_usage_with_suggestions(
            update, "/tstart <torrent>", state.suggest("torrents", query=name, limit=5)
        )
        return
    res = await services.torrent_start(name)
    await update.message.reply_text(res, parse_mode=ParseMode.HTML)


async def cmd_torrent_clean(update, context) -> None:
    """Clean (remove) torrents with missingFiles status."""
    if not await guard_sensitive(update, context):
        return

    confirm_tokens = {"yes", "--yes", "confirm", "--confirm"}
    confirm = bool(context.args and context.args[0].strip().lower() in confirm_tokens)

    if not confirm:
        # Show preview and ask for confirmation
        preview = await services.torrent_preview_missing()
        msg = (
            f"{preview}\n\n"
            f"⚠️ This will <b>remove these torrents and their files</b>.\n"
            f"To confirm, run:\n"
            f"<code>/tclean yes</code>"
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
        return

    set_audit_target(context, "clean_missing_files")
    res = await services.torrent_clean_missing(delete_files=True)
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

    set_audit_target(context, name)
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
        leech = int(item.get("leechers", 0))
        magnet = str(item.get("magnet", ""))
        if not magnet:
            continue
        key = state.store_magnet(name, magnet, seeds, leech)
        label = f"{idx}. {name} ({seeds})"
        if len(label) > 60:
            label = f"{label[:57]}..."
        buttons.append([InlineKeyboardButton(label, callback_data=f"pbselect:{key}")])
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
    if (
        category
        and piratebay.resolve_category(category) is None
        and piratebay.resolve_top_mode(category) is None
    ):
        usage = f"Usage: /pbtop [category]\nCategories: {piratebay.category_help()}"
        await update.message.reply_text(usage, parse_mode=ParseMode.HTML)
        return

    try:
        state, recorder = get_state_and_recorder(context)
        debug_sink = recorder.capture("piratebay", "pbtop failure")
        results = await services.piratebay_top(category, debug_sink=debug_sink)
    except Exception as e:
        _, recorder = get_state_and_recorder(context)
        await record_error(
            recorder,
            "piratebay",
            "pbtop failed",
            e,
            update.message.reply_text,
        )
        return

    if not results:
        await update.message.reply_text(
            "⚠️ No results found. All torrent sources may be temporarily unavailable."
        )
        return

    state = get_state(context.application)
    provider = torrentsources.get_last_used_provider() or "Unknown"
    title = f"Pirate Bay Top 10 [via {provider}]"
    if category:
        title = f"Pirate Bay Top 10 ({category}) [via {provider}]"
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
        state, recorder = get_state_and_recorder(context)
        debug_sink = recorder.capture("piratebay", "pbsearch failure")
        results = await services.piratebay_search(query, debug_sink=debug_sink)
    except Exception as e:
        _, recorder = get_state_and_recorder(context)
        await record_error(
            recorder,
            "piratebay",
            "pbsearch failed",
            e,
            update.message.reply_text,
        )
        return

    if not results:
        await update.message.reply_text(
            "⚠️ No results found. All torrent sources may be temporarily unavailable."
        )
        return

    state = get_state(context.application)
    provider = torrentsources.get_last_used_provider() or "Unknown"
    title = f"Pirate Bay Search: {query} [via {provider}]"
    msg = _format_piratebay_list(title, results)
    keyboard = _build_piratebay_keyboard(state, results)
    await update.message.reply_text(
        msg, parse_mode=ParseMode.HTML, reply_markup=keyboard
    )


async def cmd_pbprovider(update, context) -> None:
    """Show or set the forced torrent provider."""
    if not await guard_sensitive(update, context):
        return

    if not context.args:
        # Show current provider status
        forced = torrentsources.get_forced_provider()
        last_used = torrentsources.get_last_used_provider()
        status_list = torrentsources.get_provider_status()

        lines = ["<b>🔌 Torrent Provider Status</b>"]
        lines.append("")
        if forced:
            lines.append(f"<b>Forced Provider:</b> {html.escape(forced)}")
        else:
            lines.append("<b>Forced Provider:</b> None (auto-fallback)")
        if last_used:
            lines.append(f"<b>Last Used:</b> {html.escape(last_used)}")
        lines.append("")
        lines.append("<b>Available Providers:</b>")
        for p in status_list:
            status_icon = "✅" if p["enabled"] else "❌"
            forced_icon = " 📌" if p["forced"] else ""
            lines.append(f"  {status_icon} {html.escape(p['name'])}{forced_icon}")

        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
        return

    provider_name = " ".join(context.args).strip()

    # Allow clearing the forced provider
    if provider_name.lower() in {"none", "auto", "clear", "reset"}:
        torrentsources.set_forced_provider(None)
        await update.message.reply_text(
            "✅ Forced provider cleared. Will use auto-fallback.",
            parse_mode=ParseMode.HTML,
        )
        return

    # Try to set the forced provider
    if torrentsources.set_forced_provider(provider_name):
        await update.message.reply_text(
            f"✅ Forced provider set to: <b>{html.escape(provider_name)}</b>",
            parse_mode=ParseMode.HTML,
        )
    else:
        available = torrentsources.get_available_provider_names()
        available_list = ", ".join(available) if available else "None"
        await update.message.reply_text(
            f"❌ Unknown provider: <b>{html.escape(provider_name)}</b>\n"
            f"Available: {html.escape(available_list)}",
            parse_mode=ParseMode.HTML,
        )


async def cmd_pbtoggle(update, context) -> None:
    """Toggle a torrent provider on/off."""
    if not await guard_sensitive(update, context):
        return

    status_list = torrentsources.get_provider_status()
    available = torrentsources.get_available_provider_names()

    if not context.args:
        # Show current toggle status with indices
        lines = ["<b>🔌 Torrent Provider Toggle Status</b>"]
        lines.append("")
        lines.append("Usage: <code>/pbtoggle &lt;number|name&gt;</code>")
        lines.append("")
        lines.append("<b>Providers:</b>")
        for idx, p in enumerate(status_list, start=1):
            status_icon = "✅" if p["enabled"] else "❌"
            lines.append(f"  {idx}. {status_icon} {html.escape(p['name'])}")

        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
        return

    provider_input = " ".join(context.args).strip()

    # Check if input is a number (index)
    provider_name = provider_input
    if provider_input.isdigit():
        idx = int(provider_input)
        if 1 <= idx <= len(available):
            provider_name = available[idx - 1]
        else:
            await update.message.reply_text(
                f"❌ Invalid index: <b>{idx}</b>\nValid range: 1-{len(available)}",
                parse_mode=ParseMode.HTML,
            )
            return

    found, now_enabled = torrentsources.toggle_provider(provider_name)

    if not found:
        available_list = ", ".join(f"{i + 1}={n}" for i, n in enumerate(available))
        await update.message.reply_text(
            f"❌ Unknown provider: <b>{html.escape(provider_input)}</b>\n"
            f"Available: {html.escape(available_list)}",
            parse_mode=ParseMode.HTML,
        )
        return

    status_icon = "✅ enabled" if now_enabled else "❌ disabled"
    await update.message.reply_text(
        f"Provider <b>{html.escape(provider_name)}</b> is now {status_icon}",
        parse_mode=ParseMode.HTML,
    )
