from __future__ import annotations
from telegram.constants import ParseMode

from .. import services, view
from .common import guard


async def cmd_dns(update, context) -> None:
    if not await guard(update, context):
        return
    if not context.args:
        await update.message.reply_text("Usage: /dns <name>", parse_mode=ParseMode.HTML)
        return
    name = context.args[0]
    result = await services.dns_lookup(name)
    # Result is already a multi-line string from utils, wrap it
    msg = f"{view.bold('DNS ' + name + ':')}\n{view.pre(result)}"
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_traceroute(update, context) -> None:
    if not await guard(update, context):
        return
    if not context.args:
        await update.message.reply_text(
            "Usage: /traceroute <host> [max_hops]", parse_mode=ParseMode.HTML
        )
        return
    host = context.args[0]
    max_hops = 20
    if len(context.args) > 1 and context.args[1].isdigit():
        max_hops = max(1, min(int(context.args[1]), 50))

    result = await services.traceroute_host(host, max_hops)

    title = f"Traceroute {host}:"
    msg = f"{view.bold(title)}\n{view.pre(result)}"

    for part in view.chunk(msg, size=4000):
        await update.message.reply_text(part, parse_mode=ParseMode.HTML)


async def cmd_speedtest(update, context) -> None:
    if not await guard(update, context):
        return
    mb = 10
    if context.args and context.args[0].isdigit():
        mb = max(1, min(int(context.args[0]), 200))

    await update.message.reply_text(
        "🏃 Running speedtest...", parse_mode=ParseMode.HTML
    )

    result = await services.speedtest_download(mb)
    msg = f"{view.bold('Speedtest (download):')}\n{result}"
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
