from __future__ import annotations

import asyncio

from telegram.constants import ParseMode

from .. import utils
from ..state import BOT_STATE_KEY, BotState
from .common import guard, get_state, reply_usage_with_suggestions


async def cmd_docker(update, context) -> None:
    if not await guard(update, context):
        return
    try:
        get_state(context.application).refresh_containers()
    except Exception:
        pass
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
    if not await guard(update, context):
        return
    state: BotState = get_state(context.application)
    state.maybe_refresh("containers")
    if not context.args:
        await reply_usage_with_suggestions(update, "/dlogs &lt;container&gt; [lines]", state.suggest("containers", limit=5))
        return

    container_name = context.args[0]
    lines = 50
    if len(context.args) > 1 and context.args[1].isdigit():
        lines = min(int(context.args[1]), 200)

    msg = await asyncio.to_thread(utils.get_container_logs, container_name, lines)
    for part in utils.chunk(msg, size=4000):
        await update.message.reply_text(part, parse_mode=ParseMode.HTML)


async def cmd_dhealth(update, context) -> None:
    if not await guard(update, context):
        return
    state: BotState = get_state(context.application)
    state.maybe_refresh("containers")
    if not context.args:
        await reply_usage_with_suggestions(update, "/dhealth &lt;container&gt;", state.suggest("containers", limit=5))
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
