"""Handler implementations for the Telegram bot.

Handlers are async functions that perform the work and send replies. They
use utilities from `utils.py` and configuration from `core.py`.
"""
from __future__ import annotations

import logging
import html
import asyncio
from typing import Any

# Silence unresolved-import in editors/CI where telegram package may not be
# installed; use `Any` for runtime typing where necessary.
from telegram import Update  # type: ignore[import]
from telegram.constants import ParseMode  # type: ignore[import]
from telegram.ext import ContextTypes  # type: ignore[import]

from . import utils

logger = logging.getLogger(__name__)


def allowed(update: Any) -> bool:
    # import core lazily to avoid circular imports during module import
    from . import core

    if not core.ALLOWED:
        return False
    chat_id = update.effective_chat.id if update.effective_chat else None
    return chat_id in core.ALLOWED


async def guard(update: Any, context: Any) -> bool:
    if allowed(update):
        return True
    if update and update.effective_chat:
        await update.effective_chat.send_message("⛔ Not authorized")
    return False


async def cmd_start(update: Any, context: Any):
    if not await guard(update, context):
        return
    text = (
        "Hi! I can report this Pi's status.\n\n"
        "/ip – private LAN IP\n"
        "/health – CPU/RAM/disk/load/uptime (and WAN if enabled)\n"
        "/docker – list containers, status, ports\n"
        "/dockerstats – CPU/MEM per running container\n"
        "/help – this menu"
    )
    await update.message.reply_text(text)


async def cmd_whoami(update: Any, context: Any):
    c = update.effective_chat
    u = update.effective_user
    msg = (
        f"chat_id: {c.id}\n"
        f"chat_type: {c.type}\n"
        f"user: @{getattr(u, 'username', None)}"
    )
    await update.message.reply_text(msg)


async def cmd_help(update: Any, context: Any):
    if not await guard(update, context):
        return
    await cmd_start(update, context)


async def cmd_ip(update: Any, context: Any):
    if not await guard(update, context):
        return
    lan = html.escape(utils.get_primary_ip())
    msg_lines = [f"<b>LAN IP:</b> <code>{lan}</code>"]
    # import core lazily to get SHOW_WAN
    from . import core

    if core.SHOW_WAN:
        wan = html.escape(utils.get_wan_ip())
        msg_lines.append(f"<b>WAN IP:</b> <code>{wan}</code>")
    await update.message.reply_text("\n".join(msg_lines), parse_mode="HTML")


async def cmd_health(update: Any, context: Any):
    if not await guard(update, context):
        return
    from . import core

    msg = await asyncio.to_thread(utils.host_health, core.SHOW_WAN, core.WATCH_PATHS)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_docker(update: Any, context: Any):
    if not await guard(update, context):
        return
    msg = await asyncio.to_thread(utils.list_containers_basic)
    for part in utils.chunk(msg):
        await update.message.reply_text(part, parse_mode=ParseMode.HTML)


async def cmd_dockerstats(update: Any, context: Any):
    if not await guard(update, context):
        return
    msg = await asyncio.to_thread(utils.container_stats_summary)
    for part in utils.chunk(msg):
        await update.message.reply_text(part, parse_mode=ParseMode.HTML)


__all__ = [
    "cmd_start",
    "cmd_help",
    "cmd_ip",
    "cmd_health",
    "cmd_docker",
    "cmd_dockerstats",
    "cmd_whoami",
]
