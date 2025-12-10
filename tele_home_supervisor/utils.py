"""Utility helpers: system info, formatting, and Docker helpers.

This module contains repeatable code and calculations used by the handlers.
"""
from __future__ import annotations

import html
import socket
import subprocess
import time
import platform
from datetime import datetime
from typing import List, Optional
import logging

import psutil
import docker

logger = logging.getLogger(__name__)

# docker client (shared)
client = docker.from_env()


def chunk(msg: str, size: int = 3500) -> List[str]:
    lines = msg.splitlines()
    chunks: List[str] = []
    current = ""
    for line in lines:
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
    try:
        out = subprocess.check_output(
            ["bash", "-lc", "ip route get 1.1.1.1 | awk '{print $7; exit}'"],
            text=True,
            timeout=2,
        ).strip()
        if out:
            return out
    except Exception:
        logger.debug("primary ip via ip route failed", exc_info=True)
    try:
        for iface, addrs in psutil.net_if_addrs().items():
            for a in addrs:
                if a.family == socket.AF_INET and not a.address.startswith("127."):
                    return a.address
    except Exception:
        logger.debug("primary ip via psutil failed", exc_info=True)
    return "unknown"


def get_wan_ip() -> str:
    try:
        out = subprocess.check_output(
            ["bash", "-lc", "curl -fsS https://ipinfo.io/ip || curl -fsS https://ifconfig.me"],
            text=True,
            timeout=4,
        ).strip()
        return out
    except Exception:
        logger.debug("WAN IP check failed", exc_info=True)
        return "n/a"


def get_temp() -> str:
    for path in ["/sys/class/thermal/thermal_zone0/temp", "/sys/class/thermal/thermal_zone1/temp"]:
        try:
            with open(path) as f:
                t = f.read().strip()
            if t and t.isdigit():
                return f"{int(t) / 1000:.1f}°C"
        except Exception:
            pass
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


def host_health(show_wan: bool = False, watch_paths: Optional[List[str]] = None) -> str:
    cpu_pct = psutil.cpu_percent(interval=0.5)
    v = psutil.virtual_memory()
    try:
        load1, load5, load15 = os.getloadavg()  # type: ignore
    except Exception:
        load1 = load5 = load15 = 0.0

    if watch_paths is None:
        watch_paths = ["/", "/srv/media"]

    disks = []
    for path in watch_paths:
        try:
            du = psutil.disk_usage(path)
            disks.append(f"{path}: {fmt_bytes(du.used)}/{fmt_bytes(du.total)} ({du.percent:.0f}%)")
        except Exception:
            disks.append(f"{path}: n/a")
    temp = get_temp()
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

    host = html.escape(platform.node())
    system = html.escape(platform.system())
    release = html.escape(platform.release())
    lan_ip = html.escape(get_primary_ip())
    wan_ip = html.escape(get_wan_ip()) if show_wan else ""

    disks_html = " | ".join(html.escape(d) for d in disks) if disks else "n/a"

    lines = [
        f"<b>Host:</b> <code>{host}</code> <i>{system} {release}</i>",
        f"<b>Time:</b> {html.escape(now)}",
        f"<b>LAN IP:</b> <code>{lan_ip}</code>",
    ]
    if show_wan:
        lines.append(f"<b>WAN IP:</b> <code>{wan_ip}</code>")
    lines.extend(
        [
            f"<b>Uptime:</b> {human_uptime()} | <b>Load:</b> {load1:.2f} {load5:.2f} {load15:.2f}",
            f"<b>CPU:</b> {cpu_pct:.0f}% | "
            f"<b>Mem:</b> {fmt_bytes(v.used)}/{fmt_bytes(v.total)} ({v.percent:.0f}%) | "
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
        logger.exception("Docker API error while listing containers")
        return f"<i>Docker API error:</i> <code>{html.escape(str(e))}</code>"

    if not cs:
        return "<i>No containers found.</i>"

    lines = ["<b>Containers:</b>"]
    for c in cs:
        try:
            name = html.escape(c.name)
            image = html.escape(c.image.tags[0] if c.image.tags else c.image.short_id)
            status = html.escape(c.status)
            ports = html.escape(format_ports(c.attrs.get("NetworkSettings", {}).get("Ports")))
            lines.append(f"<code>{name}</code> • {status} • <code>{image}</code> • {ports}")
        except Exception:
            logger.exception("Error while formatting container %s", getattr(c, 'name', '<unknown>'))
            lines.append(f"<code>{html.escape(getattr(c, 'name', 'unknown'))}</code> • error")
    return "\n".join(lines)


def container_stats_summary() -> str:
    try:
        cs = client.containers.list()
    except Exception as e:
        logger.exception("Docker API error while getting stats")
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
        except Exception:
            logger.exception("Error computing stats for container %s", getattr(c, 'name', '<unknown>'))
            lines.append(f"<code>{html.escape(getattr(c, 'name', 'unknown'))}</code> stats error")

    return "\n".join(lines)

__all__ = [
    "chunk",
    "fmt_bytes",
    "get_primary_ip",
    "get_wan_ip",
    "get_temp",
    "human_uptime",
    "host_health",
    "format_ports",
    "list_containers_basic",
    "container_stats_summary",
]
