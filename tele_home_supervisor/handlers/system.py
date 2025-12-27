from __future__ import annotations

import asyncio
import html

from telegram.constants import ParseMode

from .. import config, services
from .. import view
from .common import guard_sensitive, get_state


def _draw_bar(percent: float, length: int = 10) -> str:
    """Draw a simple ASCII progress bar."""
    filled = int((percent / 100.0) * length)
    empty = length - filled
    # safe clamp
    filled = max(0, min(length, filled))
    empty = max(0, min(length, empty))
    return "█" * filled + "░" * empty


async def cmd_diskusage(update, context) -> None:
    if not await guard_sensitive(update, context):
        return

    stats = await services.utils.get_disk_usage_stats(config.WATCH_PATHS)
    if not stats:
        await update.message.reply_text("No disk stats available.")
        return

    lines = ["<b>Disk Usage:</b>"]
    for s in stats:
        path = s["path"]
        pct = s["percent"]
        used = services.utils.fmt_bytes(s["used"])
        total = services.utils.fmt_bytes(s["total"])
        bar = _draw_bar(pct)
        lines.append(f"<code>{path}</code>")
        lines.append(f"<code>[{bar}] {pct}% ({used}/{total})</code>")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_remind(update, context) -> None:
    if not await guard_sensitive(update, context):
        return

    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text("Usage: /remind <minutes> <message>")
        return

    try:
        minutes = float(args[0])
        text = " ".join(args[1:])
    except ValueError:
        await update.message.reply_text("Invalid duration (must be a number).")
        return

    if minutes <= 0:
        await update.message.reply_text("Duration must be positive.")
        return

    await update.message.reply_text(f"⏰ Reminder set for {minutes} minute(s).")

    async def _wait_and_remind(chat_id, delay_s, msg_text):
        await asyncio.sleep(delay_s)
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⏰ <b>Reminder:</b> {html.escape(msg_text)}",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

    # Use create_task on the loop or application to fire and forget
    context.application.create_task(
        _wait_and_remind(update.effective_chat.id, minutes * 60, text)
    )


async def cmd_ip(update, context) -> None:
    if not await guard_sensitive(update, context):
        return
    lan = await services.utils.get_primary_ip()
    # We can invoke get_wan_ip if we want, or just let the user use the health command?
    # The original implementation showed both.
    wan = await services.utils.get_wan_ip()

    # Simple formatting inline since it's just two lines
    msg = f"<b>LAN IP:</b> <code>{html.escape(lan)}</code>\n<b>WAN IP:</b> <code>{html.escape(wan)}</code>"
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_health(update, context) -> None:
    if not await guard_sensitive(update, context):
        return

    data = await services.host_health(config.SHOW_WAN, config.WATCH_PATHS)
    msg = view.render_host_health(data, show_wan=config.SHOW_WAN)
    metrics = get_state(context.application).command_metrics
    msg = f"{msg}\n\n{view.render_command_metrics(metrics)}"
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_uptime(update, context) -> None:
    if not await guard_sensitive(update, context):
        return
    uptime = await services.get_uptime_info()
    msg = f"<b>Uptime:</b> {uptime}"
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_ping(update, context) -> None:
    if not await guard_sensitive(update, context):
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
    if not await guard_sensitive(update, context):
        return
    msg = await services.utils.get_cpu_temp()
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_top(update, context) -> None:
    if not await guard_sensitive(update, context):
        return
    raw = await services.utils.get_top_processes()
    msg = f"<b>Top Processes:</b>\n<pre>{html.escape(raw)}</pre>"
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
