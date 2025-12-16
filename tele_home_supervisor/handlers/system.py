from __future__ import annotations

import asyncio
import html

from telegram.constants import ParseMode

from .. import core, utils
from .common import guard


async def cmd_ip(update, context) -> None:
    if not await guard(update, context):
        return
    lan = html.escape(utils.get_primary_ip())
    wan_raw = utils.get_wan_ip()
    wan = html.escape(wan_raw) if wan_raw else "unknown"
    msg_lines = [f"<b>LAN IP:</b> <code>{lan}</code>"]
    msg_lines.append(f"<b>WAN IP:</b> <code>{wan}</code>")
    await update.message.reply_text("\n".join(msg_lines), parse_mode=ParseMode.HTML)


async def cmd_health(update, context) -> None:
    if not await guard(update, context):
        return
    msg = await asyncio.to_thread(utils.host_health, core.SHOW_WAN, core.WATCH_PATHS)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_uptime(update, context) -> None:
    if not await guard(update, context):
        return
    msg = await asyncio.to_thread(utils.get_uptime_info)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_ping(update, context) -> None:
    if not await guard(update, context):
        return
    if not context.args or len(context.args) == 0:
        await update.message.reply_text(
            "Usage: /ping &lt;ip_or_host&gt; [count]", parse_mode=ParseMode.HTML
        )
        return
    host = context.args[0]
    count = 3
    if len(context.args) > 1 and context.args[1].isdigit():
        count = min(int(context.args[1]), 10)
    msg = await asyncio.to_thread(utils.ping_host, host, count)
    for part in utils.chunk(msg, size=4000):
        await update.message.reply_text(part, parse_mode=ParseMode.HTML)


async def cmd_temp(update, context) -> None:
    if not await guard(update, context):
        return
    msg = await asyncio.to_thread(utils.get_cpu_temp)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_top(update, context) -> None:
    if not await guard(update, context):
        return
    msg = await asyncio.to_thread(utils.get_top_processes)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
