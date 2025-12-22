from __future__ import annotations

import logging

from telegram.constants import ParseMode

from .. import services, view
from ..state import BotState
from .common import guard_sensitive, get_state, reply_usage_with_suggestions
from .callbacks import DOCKER_PAGE_SIZE, build_docker_keyboard, normalize_docker_page

logger = logging.getLogger(__name__)


async def cmd_docker(update, context) -> None:
    if not await guard_sensitive(update, context):
        return
    state = get_state(context.application)
    page = 0
    if context.args and context.args[0].isdigit():
        page = max(int(context.args[0]) - 1, 0)
    try:
        await state.refresh_containers()
    except Exception as e:
        logger.debug("refresh_containers failed: %s", e)

    containers = await services.list_containers()
    containers_sorted = sorted(containers, key=lambda item: str(item.get("name", "")))
    page, total_pages = normalize_docker_page(len(containers_sorted), page)
    start = page * DOCKER_PAGE_SIZE
    end = start + DOCKER_PAGE_SIZE
    page_containers = containers_sorted[start:end]
    msg = view.render_container_list_page(page_containers, page, total_pages)

    # Get container names for inline keyboard
    container_names = sorted(state.get_cached("containers"))

    # Build inline keyboard if we have containers
    keyboard = (
        build_docker_keyboard(container_names, page=page) if container_names else None
    )

    parts = view.chunk(msg)
    for i, part in enumerate(parts):
        if i == len(parts) - 1 and keyboard:
            await update.message.reply_text(
                part, parse_mode=ParseMode.HTML, reply_markup=keyboard
            )
        else:
            await update.message.reply_text(part, parse_mode=ParseMode.HTML)


async def cmd_dockerstats(update, context) -> None:
    # Legacy command, mapped to rich stats for now or we can implement summary?
    # services.container_stats_rich returns list of dicts.
    await cmd_dstats_rich(update, context)


async def cmd_dstats_rich(update, context) -> None:
    if not await guard_sensitive(update, context):
        return
    stats = await services.container_stats_rich()
    msg = view.render_container_stats(stats)
    for part in view.chunk(msg):
        await update.message.reply_text(part, parse_mode=ParseMode.HTML)


async def cmd_dlogs(update, context) -> None:
    """Fetch container logs."""
    if not await guard_sensitive(update, context):
        return

    state: BotState = get_state(context.application)
    await state.maybe_refresh("containers")

    if not context.args:
        await reply_usage_with_suggestions(
            update,
            "/dlogs &lt;container&gt; [lines]",
            state.suggest("containers", limit=5),
        )
        return

    container_name = context.args[0]
    container_names = state.get_cached("containers")
    if container_names and container_name not in container_names:
        await reply_usage_with_suggestions(
            update,
            "/dlogs &lt;container&gt; [lines]",
            state.suggest("containers", query=container_name, limit=5),
        )
        return
    lines = 50

    if len(context.args) > 1:
        try:
            lines = int(context.args[1])
            if lines > 0:
                lines = min(lines, 500)
            else:
                lines = max(lines, -500)
        except ValueError:
            await update.message.reply_text("❌ Invalid line count.")
            return

    raw_logs = await services.get_container_logs(container_name, lines)
    direction = "head" if lines < 0 else "tail"
    msg = view.render_logs(container_name, raw_logs, direction, str(abs(lines)))

    for part in view.chunk(msg, size=4000):
        await update.message.reply_text(part, parse_mode=ParseMode.HTML)


async def cmd_dhealth(update, context) -> None:
    if not await guard_sensitive(update, context):
        return
    state: BotState = get_state(context.application)
    await state.maybe_refresh("containers")
    if not context.args:
        await reply_usage_with_suggestions(
            update, "/dhealth &lt;container&gt;", state.suggest("containers", limit=5)
        )
        return
    name = context.args[0]
    container_names = state.get_cached("containers")
    if container_names and name not in container_names:
        await reply_usage_with_suggestions(
            update,
            "/dhealth &lt;container&gt;",
            state.suggest("containers", query=name, limit=5),
        )
        return
    msg = await services.healthcheck_container(name)
    # Simple formatting
    await update.message.reply_text(f"<pre>{msg}</pre>", parse_mode=ParseMode.HTML)


async def cmd_ports(update, context) -> None:
    if not await guard_sensitive(update, context):
        return

    msg = await services.get_listening_ports()

    # Formatting

    formatted = f"{view.bold('Listening Ports:')}\n{view.pre(msg)}"

    for part in view.chunk(formatted, size=4000):
        await update.message.reply_text(part, parse_mode=ParseMode.HTML)
