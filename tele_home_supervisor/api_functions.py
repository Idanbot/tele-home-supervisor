"""Handler implementations for the Telegram bot.

Handlers are async functions that perform the work and send replies. They
use utilities from `utils.py` and configuration from `core.py`.
"""
from __future__ import annotations

import logging
import html
import asyncio
from typing import TYPE_CHECKING

from telegram.constants import ParseMode

if TYPE_CHECKING:
    from telegram import Update
    from telegram.ext import ContextTypes

from . import utils

logger = logging.getLogger(__name__)


def allowed(update: "Update") -> bool:
    # import core lazily to avoid circular imports during module import
    from . import core

    if not core.ALLOWED:
        return False
    chat_id = update.effective_chat.id if update.effective_chat else None
    return chat_id in core.ALLOWED


async def guard(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> bool:
    if allowed(update):
        return True
    if update and update.effective_chat:
        await update.effective_chat.send_message("⛔ Not authorized")
    return False


async def cmd_start(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
    if not await guard(update, context):
        return
    text = (
        "Hi! I can report this Pi's status.\n\n"
        "/ip – private LAN IP\n"
        "/health – CPU/RAM/disk/load/uptime (and WAN if enabled)\n"
        "/docker – list containers, status, ports\n"
        "/dockerstats – CPU/MEM per running container\n"
            "/dstats-rich – detailed Docker stats (net/block IO)\n"
        "/logs <container> – recent logs from container\n"
        "/ps – top processes\n"
        "/uptime – system uptime\n"
            "/dhealth <container> – container health check\n"
            "/ping <ip> [count] – ping an IP or hostname\n"
        "/version – bot version and build info\n"
        "/help – this menu"
    )
    await update.message.reply_text(text)


async def cmd_whoami(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
    c = update.effective_chat
    u = update.effective_user
    username = f"@{u.username}" if u and u.username else "(no username)"
    msg = (
        f"chat_id: {c.id}\n"
        f"chat_type: {c.type}\n"
        f"user: {username}"
    )
    await update.message.reply_text(msg)


async def cmd_help(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
    if not await guard(update, context):
        return
    await cmd_start(update, context)


async def cmd_ip(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
    if not await guard(update, context):
        return
    lan = html.escape(utils.get_primary_ip())
    msg_lines = [f"<b>LAN IP:</b> <code>{lan}</code>"]
    # import core lazily to get SHOW_WAN
    from . import core

    if core.SHOW_WAN:
        wan = html.escape(utils.get_wan_ip())
        msg_lines.append(f"<b>WAN IP:</b> <code>{wan}</code>")
    await update.message.reply_text("\n".join(msg_lines), parse_mode=ParseMode.HTML)


async def cmd_health(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
    if not await guard(update, context):
        return
    from . import core

    msg = await asyncio.to_thread(utils.host_health, core.SHOW_WAN, core.WATCH_PATHS)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_docker(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
    if not await guard(update, context):
        return
    msg = await asyncio.to_thread(utils.list_containers_basic)
    for part in utils.chunk(msg):
        await update.message.reply_text(part, parse_mode=ParseMode.HTML)


async def cmd_dockerstats(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
    if not await guard(update, context):
        return
    msg = await asyncio.to_thread(utils.container_stats_summary)
    for part in utils.chunk(msg):
        await update.message.reply_text(part, parse_mode=ParseMode.HTML)


async def cmd_dstats_rich(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
    if not await guard(update, context):
        return
    msg = await asyncio.to_thread(utils.container_stats_rich)
    for part in utils.chunk(msg):
        await update.message.reply_text(part, parse_mode=ParseMode.HTML)


async def cmd_logs(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
    if not await guard(update, context):
        return
    # Extract container name from command args
    if not context.args or len(context.args) == 0:
        await update.message.reply_text(
            "<i>Usage:</i> /logs CONTAINER_NAME [lines]\n<i>Example:</i> /logs my-container 100",
            parse_mode=ParseMode.HTML
        )
        return
    
    container_name = context.args[0]
    lines = 50
    if len(context.args) > 1 and context.args[1].isdigit():
        lines = min(int(context.args[1]), 200)  # Cap at 200 lines
    
    msg = await asyncio.to_thread(utils.get_container_logs, container_name, lines)
    for part in utils.chunk(msg, size=4000):
        await update.message.reply_text(part, parse_mode=ParseMode.HTML)


async def cmd_dhealth(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
    if not await guard(update, context):
        return
    if not context.args or len(context.args) == 0:
        await update.message.reply_text("Usage: /dhealth <container>", parse_mode=ParseMode.HTML)
        return
    name = context.args[0]
    msg = await asyncio.to_thread(utils.healthcheck_container, name)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_ps(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
    if not await guard(update, context):
        return
    msg = await asyncio.to_thread(utils.get_top_processes)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_uptime(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
    if not await guard(update, context):
        return
    msg = await asyncio.to_thread(utils.get_uptime_info)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_ping(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
    if not await guard(update, context):
        return
    if not context.args or len(context.args) == 0:
        await update.message.reply_text("Usage: /ping <ip_or_host> [count]", parse_mode=ParseMode.HTML)
        return
    host = context.args[0]
    count = 3
    if len(context.args) > 1 and context.args[1].isdigit():
        count = min(int(context.args[1]), 10)
    msg = await asyncio.to_thread(utils.ping_host, host, count)
    for part in utils.chunk(msg, size=4000):
        await update.message.reply_text(part, parse_mode=ParseMode.HTML)


async def cmd_version(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
    if not await guard(update, context):
        return
    msg = await asyncio.to_thread(utils.get_version_info)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


__all__ = [
    "cmd_start",
    "cmd_help",
    "cmd_ip",
    "cmd_health",
    "cmd_docker",
    "cmd_dockerstats",
    "cmd_whoami",
    "cmd_logs",
    "cmd_ps",
    "cmd_uptime",
    "cmd_dstats_rich",
    "cmd_dhealth",
    "cmd_ping",
    "cmd_version",
]
