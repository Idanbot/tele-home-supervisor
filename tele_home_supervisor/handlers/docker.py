from __future__ import annotations

import asyncio

from telegram.constants import ParseMode
import logging

from .. import utils
from ..state import BotState
from .common import guard, get_state, reply_usage_with_suggestions

logger = logging.getLogger(__name__)


async def cmd_docker(update, context) -> None:
    if not await guard(update, context):
        return
    try:
        get_state(context.application).refresh_containers()
    except Exception as e:
        logger.debug("refresh_containers failed: %s", e)
    msg = await asyncio.to_thread(utils.list_containers_basic)
    for part in utils.chunk(msg):
        await update.message.reply_text(part, parse_mode=ParseMode.HTML)


async def cmd_dockerstats(update, context) -> None:
    if not await guard(update, context):
        return
    msg = await asyncio.to_thread(utils.container_stats_summary)
    for part in utils.chunk(msg):
        await update.message.reply_text(part, parse_mode=ParseMode.HTML)


async def cmd_dstats_rich(update, context) -> None:
    if not await guard(update, context):
        return
    msg = await asyncio.to_thread(utils.container_stats_rich)
    for part in utils.chunk(msg):
        await update.message.reply_text(part, parse_mode=ParseMode.HTML)


async def cmd_dlogs(update, context) -> None:
    """Fetch container logs. Supports positive (tail) and negative (head) line counts.

    Examples:
        /dlogs mycontainer        - Last 50 lines (default)
        /dlogs mycontainer 100    - Last 100 lines
        /dlogs mycontainer -50    - First 50 lines
    """
    if not await guard(update, context):
        return

    state: BotState = get_state(context.application)
    state.maybe_refresh("containers")

    if not context.args:
        await reply_usage_with_suggestions(
            update,
            "/dlogs &lt;container&gt; [lines]",
            state.suggest("containers", limit=5),
        )
        return

    container_name = context.args[0]
    lines = 50  # Default: last 50 lines

    if len(context.args) > 1:
        try:
            # Parse line count (supports negative numbers for head)
            lines = int(context.args[1])
            # Clamp to reasonable bounds
            if lines > 0:
                lines = min(lines, 500)  # Max 500 lines from tail
            else:
                lines = max(lines, -500)  # Max 500 lines from head
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid line count. Use a positive number (tail) or negative (head).\n"
                "Example: /dlogs mycontainer -100"
            )
            return

    msg = await asyncio.to_thread(utils.get_container_logs, container_name, lines)
    for part in utils.chunk(msg, size=4000):
        await update.message.reply_text(part, parse_mode=ParseMode.HTML)


async def cmd_dhealth(update, context) -> None:
    if not await guard(update, context):
        return
    state: BotState = get_state(context.application)
    state.maybe_refresh("containers")
    if not context.args:
        await reply_usage_with_suggestions(
            update, "/dhealth &lt;container&gt;", state.suggest("containers", limit=5)
        )
        return
    name = context.args[0]
    msg = await asyncio.to_thread(utils.healthcheck_container, name)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_ports(update, context) -> None:
    if not await guard(update, context):
        return
    msg = await asyncio.to_thread(utils.get_listening_ports)
    for part in utils.chunk(msg, size=4000):
        await update.message.reply_text(part, parse_mode=ParseMode.HTML)
