#!/usr/bin/env python3
import os
import asyncio
import time
import platform
import socket
import subprocess
from datetime import datetime
from typing import List
import html

import psutil
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes
import docker  # Docker SDK for Python

TOKEN = os.environ["BOT_TOKEN"]

ALLOWED = set()
for part in os.environ.get("ALLOWED_CHAT_IDS", "").replace(" ", "").split(","):
    if part.isdigit():
        ALLOWED.add(int(part))

SHOW_WAN = os.environ.get("SHOW_WAN", "false").lower() in {"1", "true", "yes"}
WATCH_PATHS = [
    p.strip()
    for p in os.environ.get("WATCH_PATHS", "/,/srv/media").split(",")
    if p.strip()
]

if not ALLOWED:
    # Fail-closed: no one is allowed until ALLOWED_CHAT_IDS is configured.
    print(
        "WARNING: ALLOWED_CHAT_IDS is empty; all guarded commands will be unauthorized."
    )

client = docker.from_env()


def allowed(update: Update) -> bool:
    """Return True if this chat is allowed. Fail-closed when ALLOWED is empty."""
    if not ALLOWED:
        return False
    chat_id = update.effective_chat.id if update.effective_chat else None
    return chat_id in ALLOWED


def chunk(msg: str, size: int = 3500) -> List[str]:
    """Split message into chunks on line boundaries to keep HTML intact."""
    lines = msg.splitlines()
    chunks: List[str] = []
    current = ""
    for line in lines:
        # +1 for the newline if current is not empty
        added_length = len(line) + (1 if current else 0)
        if len(current) + added_length > size and current:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks


def fmt_bytes(n: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    i = 0
    f = float(n)
    while f >= 1024 and i < len(units) - 1:
        f /= 1024
        i += 1
    return f"{f:.1f} {units[i]}"


def get_primary_ip() -> str:
    # Robust way inside host network namespace; falls back otherwise
    try:
        out = subprocess.check_output(
            ["bash", "-lc", "ip route get 1.1.1.1 | awk '{print $7; exit}'"],
            text=True,
            timeout=2,
        ).strip()
        if out:
            return out
    except Exception:
        pass
    # Fallback: first non-loopback IPv4
    try:
        for iface, addrs in psutil.net_if_addrs().items():
            for a in addrs:
                if a.family == socket.AF_INET and not a.address.startswith("127."):
                    return a.address
    except Exception:
        pass
    return "unknown"


def get_wan_ip() -> str:
    try:
        out = subprocess.check_output(
            [
                "bash",
                "-lc",
                "curl -fsS https://ipinfo.io/ip || curl -fsS https://ifconfig.me",
            ],
            text=True,
            timeout=4,
        ).strip()
        return out
    except Exception:
        return "n/a"


def get_temp() -> str:
    # Raspberry Pi thermal (multiple fallbacks)
    # 1) sysfs
    for path in [
        "/sys/class/thermal/thermal_zone0/temp",
        "/sys/class/thermal/thermal_zone1/temp",
    ]:
        try:
            with open(path) as f:
                t = f.read().strip()
            if t and t.isdigit():
                return f"{int(t) / 1000:.1f}°C"
        except Exception:
            pass
    # 2) vcgencmd (if available)
    try:
        out = subprocess.check_output(
            ["bash", "-lc", "vcgencmd measure_temp 2>/dev/null | cut -d= -f2"],
            text=True,
            timeout=2,
        ).strip()
        if out:
            return out
    except Exception:
        pass
    return "n/a"


def human_uptime() -> str:
    boot = psutil.boot_time()
    secs = int(time.time() - boot)
    d, r = divmod(secs, 86400)
    h, r = divmod(r, 3600)
    m, _ = divmod(r, 60)
    return f"{d}d {h}h {m}m"


def host_health() -> str:
    cpu_pct = psutil.cpu_percent(interval=0.5)
    v = psutil.virtual_memory()
    try:
        load1, load5, load15 = os.getloadavg()
    except (AttributeError, OSError):
        load1 = load5 = load15 = 0.0

    disks = []
    for path in WATCH_PATHS:
        try:
            du = psutil.disk_usage(path)
            disks.append(
                f"{path}: {
                    fmt_bytes(du.used)}/{fmt_bytes(du.total)} ({du.percent:.0f}%)"
            )
        except Exception:
            disks.append(f"{path}: n/a")
    temp = get_temp()
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

    host = html.escape(platform.node())
    system = html.escape(platform.system())
    release = html.escape(platform.release())
    lan_ip = html.escape(get_primary_ip())
    wan_ip = html.escape(get_wan_ip()) if SHOW_WAN else ""

    disks_html = " | ".join(html.escape(d) for d in disks) if disks else "n/a"

    lines = [
        f"<b>Host:</b> <code>{host}</code> <i>{system} {release}</i>",
        f"<b>Time:</b> {html.escape(now)}",
        f"<b>LAN IP:</b> <code>{lan_ip}</code>",
    ]
    if SHOW_WAN:
        lines.append(f"<b>WAN IP:</b> <code>{wan_ip}</code>")
    lines.extend(
        [
            f"<b>Uptime:</b> {human_uptime()
                              } | <b>Load:</b> {load1:.2f} {load5:.2f} {load15:.2f}",
            f"<b>CPU:</b> {cpu_pct:.0f}% | "
            f"<b>Mem:</b> {fmt_bytes(v.used)}/{fmt_bytes(v.total)
                                               } ({v.percent:.0f}%) | "
            f"<b>Temp:</b> {html.escape(temp)}",
            f"<b>Disks:</b> {disks_html}",
        ]
    )
    return "\n".join(lines)


def format_ports(pmap) -> str:
    if not pmap:
        return "-"
    items = []
    for k, v in pmap.items():
        if v is None:
            items.append(k)
        else:
            for b in v:
                hp = b.get("HostPort", "")
                items.append(f"{hp}->{k}")
    return ", ".join(items) if items else "-"


def list_containers_basic() -> str:
    try:
        cs = client.containers.list(all=True)
    except Exception as e:
        return f"<i>Docker API error:</i> <code>{html.escape(str(e))}</code>"

    if not cs:
        return "<i>No containers found.</i>"

    lines = ["<b>Containers:</b>"]
    for c in cs:
        try:
            name = html.escape(c.name)
            image = html.escape(
                c.image.tags[0] if c.image.tags else c.image.short_id)
            status = html.escape(c.status)
            ports = html.escape(
                format_ports(c.attrs.get("NetworkSettings", {}).get("Ports"))
            )
            lines.append(
                f"<code>{name}</code> • {status} • <code>{image}</code> • {ports}"
            )
        except Exception as e:
            lines.append(
                f"<code>{html.escape(
                    c.name)}</code> • error: <code>{html.escape(str(e))}</code>"
            )
    return "\n".join(lines)


def container_stats_summary() -> str:
    try:
        cs = client.containers.list()
    except Exception as e:
        return f"<i>Docker API error:</i> <code>{html.escape(str(e))}</code>"

    if not cs:
        return "<i>No running containers.</i>"

    lines = ["<b>Container stats (no-stream):</b>"]
    for c in cs:
        try:
            s = c.stats(stream=False)
            cpu_stats = s.get("cpu_stats", {}) or {}
            precpu = s.get("precpu_stats", {}) or {}

            cpu_total = cpu_stats.get("cpu_usage", {}).get("total_usage", 0)
            precpu_total = precpu.get("cpu_usage", {}).get("total_usage", 0)
            cpu_delta = cpu_total - precpu_total

            system_cpu = cpu_stats.get("system_cpu_usage", 0)
            pre_system_cpu = precpu.get("system_cpu_usage", 0)
            system_delta = system_cpu - pre_system_cpu

            percpu = cpu_stats.get("cpu_usage", {}).get("percpu_usage") or []
            online = cpu_stats.get("online_cpus") or len(percpu) or 1

            cpu_pct = 0.0
            if cpu_delta > 0 and system_delta > 0:
                cpu_pct = (cpu_delta / system_delta) * online * 100.0

            mem_stats = s.get("memory_stats", {}) or {}
            mem_usage = float(mem_stats.get("usage", 0.0))
            mem_limit = float(mem_stats.get("limit", 1.0)) or 1.0
            mem_pct = (mem_usage / mem_limit) * 100.0

            name = html.escape(c.name)
            mem_usage_h = fmt_bytes(int(mem_usage))
            mem_limit_h = fmt_bytes(int(mem_limit))

            lines.append(
                f"<code>{name}</code> CPU {cpu_pct:5.1f}%  "
                f"MEM {mem_pct:5.1f}% ({mem_usage_h}/{mem_limit_h})"
            )
        except Exception as e:
            lines.append(
                f"<code>{html.escape(
                    c.name)}</code> stats error: <code>{html.escape(str(e))}</code>"
            )

    return "\n".join(lines)


async def guard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if allowed(update):
        return True
    if update and update.effective_chat:
        await update.effective_chat.send_message("⛔ Not authorized")
    return False


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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


async def cmd_whoami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    c = update.effective_chat
    u = update.effective_user
    msg = f"chat_id: {c.id}\nchat_type: {
        c.type}\nuser: @{getattr(u, 'username', None)}"
    await update.message.reply_text(msg)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update, context):
        return
    await cmd_start(update, context)


async def cmd_ip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update, context):
        return
    lan = html.escape(get_primary_ip())
    msg_lines = [f"<b>LAN IP:</b> <code>{lan}</code>"]
    if SHOW_WAN:
        wan = html.escape(get_wan_ip())
        msg_lines.append(f"<b>WAN IP:</b> <code>{wan}</code>")
    await update.message.reply_text("\n".join(msg_lines), parse_mode=ParseMode.HTML)


async def cmd_health(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update, context):
        return
    msg = await asyncio.to_thread(host_health)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_docker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update, context):
        return
    msg = await asyncio.to_thread(list_containers_basic)
    for part in chunk(msg):
        await update.message.reply_text(part, parse_mode=ParseMode.HTML)


async def cmd_dockerstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update, context):
        return
    msg = await asyncio.to_thread(container_stats_summary)
    for part in chunk(msg):
        await update.message.reply_text(part, parse_mode=ParseMode.HTML)


def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler(["start"], cmd_start))
    app.add_handler(CommandHandler(["whoami"], cmd_whoami))
    app.add_handler(CommandHandler(["help"], cmd_help))
    app.add_handler(CommandHandler(["ip"], cmd_ip))
    app.add_handler(CommandHandler(["health"], cmd_health))
    app.add_handler(CommandHandler(["docker"], cmd_docker))
    app.add_handler(CommandHandler(["dockerstats"], cmd_dockerstats))

    app.run_polling(stop_signals=None)


if __name__ == "__main__":
    main()
