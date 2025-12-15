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
from . import services

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
        "Hi! I can report this Pi's status and manage qBittorrent.\n\n"
        "/ip – private LAN IP\n"
        "/health – CPU/RAM/disk/load/uptime (and WAN if enabled)\n"
        "/docker – list containers, status, ports\n"
        "/dockerstats – CPU/MEM per running container\n"
        "/dstatsrich – detailed Docker stats (net/block IO)\n"
        "/logs <container> – recent logs from container\n"
        "/dhealth <container> – container health check\n"
        "/uptime – system uptime\n"
        "/ping <ip> [count] – ping an IP or hostname\n"
        "/temp – CPU temperature (reads /host_thermal/temp)\n"
        "/top – top CPU processes\n"
        "/ports – listening ports (inside container)\n"
        "/dns <name> – DNS lookup\n"
        "/traceroute <host> [max_hops] – trace network route\n"
        "/speedtest [MB] – quick download speed test\n"
        "/tadd <torrent> [save_path] – add torrent (magnet/URL) to qBittorrent\n"
        "/tstatus – show qBittorrent torrent status\n"
        "/tstop <torrent> – pause torrent(s) by name\n"
        "/tstart <torrent> – resume torrent(s) by name\n"
        "/tdelete <torrent> yes – delete torrent(s) and files\n"
        "/subscribe [on|off] – torrent completion notifications\n"
        "/whoami – show chat and user info\n"
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
        await update.message.reply_text("Usage: /dhealth &lt;container&gt;", parse_mode=ParseMode.HTML)
        return
    name = context.args[0]
    msg = await asyncio.to_thread(utils.healthcheck_container, name)
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
        await update.message.reply_text("Usage: /ping &lt;ip_or_host&gt; [count]", parse_mode=ParseMode.HTML)
        return
    host = context.args[0]
    count = 3
    if len(context.args) > 1 and context.args[1].isdigit():
        count = min(int(context.args[1]), 10)
    msg = await asyncio.to_thread(utils.ping_host, host, count)
    for part in utils.chunk(msg, size=4000):
        await update.message.reply_text(part, parse_mode=ParseMode.HTML)


async def cmd_temp(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
    if not await guard(update, context):
        return
    msg = await asyncio.to_thread(utils.get_cpu_temp)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_version(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
    if not await guard(update, context):
        return
    msg = await asyncio.to_thread(utils.get_version_info)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_torrent_add(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
    """Add a torrent to qBittorrent (magnet/URL).

    Usage: /tadd <torrent> [save_path]
    """
    if not await guard(update, context):
        return
    if not context.args or len(context.args) == 0:
        await update.message.reply_text("Usage: /tadd &lt;torrent&gt; [save_path]", parse_mode=ParseMode.HTML)
        return
    magnet = context.args[0]
    save_path = context.args[1] if len(context.args) > 1 else "/downloads"

    res = await asyncio.to_thread(services.torrent_add, magnet, save_path)
    await update.message.reply_text(res, parse_mode=ParseMode.HTML)


async def cmd_torrent_status(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
    """Return a formatted status of torrents in qBittorrent.

    Usage: /tstatus
    """
    if not await guard(update, context):
        return

    msg = await asyncio.to_thread(services.torrent_status)
    for part in utils.chunk(msg, size=4000):
        await update.message.reply_text(part, parse_mode=ParseMode.HTML)


async def cmd_torrent_stop(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
    """Pause/stop torrents by name substring.

    Usage: /tstop <torrent>
    """
    if not await guard(update, context):
        return
    if not context.args:
        await update.message.reply_text("Usage: /tstop &lt;torrent&gt;", parse_mode=ParseMode.HTML)
        return
    name = " ".join(context.args)
    res = await asyncio.to_thread(services.torrent_stop, name)
    await update.message.reply_text(res, parse_mode=ParseMode.HTML)


async def cmd_torrent_start(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
    """Resume/start torrents by name substring.

    Usage: /tstart <torrent>
    """
    if not await guard(update, context):
        return
    if not context.args:
        await update.message.reply_text("Usage: /tstart &lt;torrent&gt;", parse_mode=ParseMode.HTML)
        return
    name = " ".join(context.args)
    res = await asyncio.to_thread(services.torrent_start, name)
    await update.message.reply_text(res, parse_mode=ParseMode.HTML)


async def cmd_torrent_delete(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
    """Delete torrents (and their files) by name substring.

    Usage: /tdelete <name_substring> yes
    """
    if not await guard(update, context):
        return
    if not context.args:
        await update.message.reply_text("Usage: /tdelete &lt;torrent&gt; yes", parse_mode=ParseMode.HTML)
        return

    confirm_tokens = {"yes", "--yes", "confirm", "--confirm"}
    confirm = bool(context.args and context.args[-1].strip().lower() in confirm_tokens)
    name = " ".join(context.args[:-1] if confirm else context.args).strip()
    if not name:
        await update.message.reply_text("Usage: /tdelete &lt;torrent&gt; yes", parse_mode=ParseMode.HTML)
        return

    if not confirm:
        matches_msg = await asyncio.to_thread(services.torrent_preview, name)
        msg = (
            f"{matches_msg}\n\n"
            f"⚠️ This will <b>delete files</b>. Re-run to confirm:\n"
            f"<code>/tdelete {html.escape(name)} yes</code>"
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
        return

    res = await asyncio.to_thread(services.torrent_delete, name)
    await update.message.reply_text(res, parse_mode=ParseMode.HTML)


async def cmd_subscribe(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
    """Subscribe/unsubscribe to torrent completion notifications.

    Usage: /subscribe [on|off|status]
    """
    if not await guard(update, context):
        return
    chat_id = update.effective_chat.id if update and update.effective_chat else None
    if chat_id is None:
        return

    from . import notifications

    try:
        notifications.ensure_started(context.application)
    except Exception:
        pass

    args = [a.strip().lower() for a in (context.args or []) if a.strip()]
    if args and args[0] in {"torrent", "torrents", "t"}:
        args = args[1:]
    action = args[0] if args else "toggle"

    if action in {"status"}:
        is_on = notifications.is_torrent_download_subscribed(chat_id)
        await update.message.reply_text(
            f"Torrent completion notifications: <b>{'ON' if is_on else 'OFF'}</b>",
            parse_mode=ParseMode.HTML,
        )
        return

    enable: bool | None
    if action in {"toggle"}:
        enable = None
    elif action in {"on", "yes", "true", "1"}:
        enable = True
    elif action in {"off", "no", "false", "0"}:
        enable = False
    else:
        await update.message.reply_text(
            "Usage: /subscribe [on|off|status]",
            parse_mode=ParseMode.HTML,
        )
        return

    is_on = notifications.set_torrent_download_subscription(chat_id, enable)
    await update.message.reply_text(
        f"Torrent completion notifications: <b>{'ON' if is_on else 'OFF'}</b>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_top(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
    if not await guard(update, context):
        return
    msg = await asyncio.to_thread(utils.get_top_processes)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_ports(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
    if not await guard(update, context):
        return
    msg = await asyncio.to_thread(utils.get_listening_ports)
    for part in utils.chunk(msg, size=4000):
        await update.message.reply_text(part, parse_mode=ParseMode.HTML)


async def cmd_dns(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
    if not await guard(update, context):
        return
    if not context.args:
        await update.message.reply_text("Usage: /dns &lt;name&gt;", parse_mode=ParseMode.HTML)
        return
    name = context.args[0]
    msg = await asyncio.to_thread(utils.dns_lookup, name)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_traceroute(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
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


async def cmd_speedtest(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
    if not await guard(update, context):
        return
    mb = 10
    if context.args and context.args[0].isdigit():
        mb = max(1, min(int(context.args[0]), 200))
    msg = await asyncio.to_thread(utils.speedtest_download, mb)
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
    "cmd_uptime",
    "cmd_dstats_rich",
    "cmd_dhealth",
    "cmd_ping",
    "cmd_subscribe",
    "cmd_top",
    "cmd_ports",
    "cmd_dns",
    "cmd_traceroute",
    "cmd_speedtest",
    "cmd_torrent_add",
    "cmd_torrent_status",
    "cmd_torrent_stop",
    "cmd_torrent_start",
    "cmd_torrent_delete",
    "cmd_version",
]
