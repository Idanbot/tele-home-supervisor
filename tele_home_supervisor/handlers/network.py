from __future__ import annotations

import asyncio

from telegram.constants import ParseMode

from .. import utils
from .common import guard


async def cmd_dns(update, context) -> None:
    if not await guard(update, context):
        return
    if not context.args:
        await update.message.reply_text("Usage: /dns &lt;name&gt;", parse_mode=ParseMode.HTML)
        return
    name = context.args[0]
    msg = await asyncio.to_thread(utils.dns_lookup, name)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_traceroute(update, context) -> None:
    if not await guard(update, context):
        return
    if not context.args:
        await update.message.reply_text("Usage: /traceroute &lt;host&gt; [max_hops]", parse_mode=ParseMode.HTML)
        return
    host = context.args[0]
    max_hops = 20
    if len(context.args) > 1 and context.args[1].isdigit():
        max_hops = max(1, min(int(context.args[1]), 50))
    msg = await asyncio.to_thread(utils.traceroute_host, host, max_hops)
    for part in utils.chunk(msg, size=4000):
        await update.message.reply_text(part, parse_mode=ParseMode.HTML)


async def cmd_speedtest(update, context) -> None:
    if not await guard(update, context):
        return
    mb = 10
    if context.args and context.args[0].isdigit():
        mb = max(1, min(int(context.args[0]), 200))
    msg = await asyncio.to_thread(utils.speedtest_download, mb)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

