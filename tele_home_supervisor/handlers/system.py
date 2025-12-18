from __future__ import annotations

import asyncio
import html

from telegram.constants import ParseMode

from .. import config, services
from .. import view
from .common import guard


async def cmd_ip(update, context) -> None:
    if not await guard(update, context):
        return
    lan = await services.utils.get_primary_ip()
    # We can invoke get_wan_ip if we want, or just let the user use the health command?
    # The original implementation showed both.
    wan = await services.utils.get_wan_ip()

    # Simple formatting inline since it's just two lines
    msg = f"<b>LAN IP:</b> <code>{html.escape(lan)}</code>\n<b>WAN IP:</b> <code>{html.escape(wan)}</code>"
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_health(update, context) -> None:
    if not await guard(update, context):
        return

    data = await services.host_health(config.SHOW_WAN, config.WATCH_PATHS)
    msg = view.render_host_health(data, show_wan=config.SHOW_WAN)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_uptime(update, context) -> None:
    if not await guard(update, context):
        return
    uptime = await services.get_uptime_info()
    msg = f"<b>Uptime:</b> {uptime}"
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_ping(update, context) -> None:
    if not await guard(update, context):
        return
    if not context.args or len(context.args) == 0:
        await update.message.reply_text(
            "Usage: /ping <ip_or_host> [count]", parse_mode=ParseMode.HTML
        )
        return
    host = context.args[0]
    count = 3
    if len(context.args) > 1 and context.args[1].isdigit():
        count = min(int(context.args[1]), 10)

    msg = await services.utils.ping_host(host, count)
    # Simple formatting: wrapping in pre
    formatted = f"<b>Ping {html.escape(host)}:</b>\n<pre>{html.escape(msg)}</pre>"
    await update.message.reply_text(formatted, parse_mode=ParseMode.HTML)


async def cmd_temp(update, context) -> None:
    if not await guard(update, context):
        return
    msg = await services.utils.get_cpu_temp()
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_top(update, context) -> None:
    if not await guard(update, context):
        return
    raw = await services.utils.get_top_processes()
    msg = f"<b>Top Processes:</b>\n<pre>{html.escape(raw)}</pre>"
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
