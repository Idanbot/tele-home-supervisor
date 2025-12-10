"""Utility helpers: system info, formatting, and Docker helpers.

This module contains repeatable code and calculations used by the handlers.
"""
from __future__ import annotations

import html
import os
import socket
import subprocess
import time
import platform
from datetime import datetime
from typing import TYPE_CHECKING
import logging

import psutil
import docker

if TYPE_CHECKING:
    # Import DockerClient only for type checking; runtime import may not be
    # available in some static analysis environments.
    from docker.client import DockerClient  # type: ignore

logger = logging.getLogger(__name__)

# docker client (shared)
client: "DockerClient" = docker.from_env()


def chunk(msg: str, size: int = 3500) -> list[str]:
    lines = msg.splitlines()
    chunks: list[str] = []
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


def host_health(show_wan: bool = False, watch_paths: list[str] | None = None) -> str:
    cpu_pct = psutil.cpu_percent(interval=0.5)
    v = psutil.virtual_memory()
    try:
        load1, load5, load15 = os.getloadavg()
    except (OSError, AttributeError):
        load1 = load5 = load15 = 0.0

    if watch_paths is None:
        watch_paths = ["/", "/srv/media"]

    disks: list[str] = []
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


def format_ports(pmap: dict[str, list[dict[str, str]] | None] | None) -> str:
    if not pmap:
        return "-"
    items: list[str] = []
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
    """Get container stats using docker stats CLI (much faster than API)."""
    # Try common docker binary locations (prefer /usr/local/bin where we install it)
    docker_paths = ["/usr/local/bin/docker", "/usr/bin/docker", "docker"]
    docker_cmd = None
    
    for path in docker_paths:
        try:
            result = subprocess.run(
                [path, "--version"],
                capture_output=True,
                timeout=1,
                check=False,
            )
            if result.returncode == 0:
                docker_cmd = path
                logger.debug(f"Found docker at {path}")
                break
        except (FileNotFoundError, subprocess.SubprocessError, OSError):
            continue
    
    if not docker_cmd:
        # Only log once at warning level to avoid spam
        return "<i>Docker CLI not available in container</i>"
    
    try:
        # Use docker stats --no-stream for a single snapshot (fast)
        out = subprocess.check_output(
            [docker_cmd, "stats", "--no-stream", "--format", "{{.Name}}\t{{.CPUPerc}}\t{{.MemPerc}}\t{{.MemUsage}}"],
            text=True,
            timeout=5,
        ).strip()
        if not out:
            return "<i>No running containers.</i>"
        
        lines = ["<b>Container stats:</b>"]
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) == 4:
                name, cpu, mem_pct, mem_usage = parts
                lines.append(
                    f"<code>{html.escape(name)}</code> "
                    f"CPU {html.escape(cpu)} MEM {html.escape(mem_pct)} ({html.escape(mem_usage)})"
                )
        return "\n".join(lines)
    except subprocess.TimeoutExpired:
        logger.error("docker stats command timed out")
        return "<i>Docker stats timed out</i>"
    except subprocess.CalledProcessError as e:
        logger.exception("docker stats command failed")
        return f"<i>Docker stats error:</i> <code>{html.escape(str(e))}</code>"
    except Exception as e:
        logger.exception("Error running docker stats")
        return f"<i>Error:</i> <code>{html.escape(str(e))}</code>"

def get_container_logs(container_name: str, lines: int = 50) -> str:
    """Get recent logs from a container."""
    try:
        out = subprocess.check_output(
            ["/usr/local/bin/docker", "logs", "--tail", str(lines), container_name],
            text=True,
            stderr=subprocess.STDOUT,
            timeout=10,
        ).strip()
        if not out:
            return f"<i>Container {html.escape(container_name)} has no logs</i>"
        # Limit output to avoid message size issues
        if len(out) > 3500:
            out = out[-3500:]
            out = "...\n" + out
        return f"<b>Logs for {html.escape(container_name)}:</b>\n<pre>{html.escape(out)}</pre>"
    except subprocess.TimeoutExpired:
        return f"<i>Timeout getting logs for {html.escape(container_name)}</i>"
    except subprocess.CalledProcessError as e:
        error_msg = str(e.output) if e.output else str(e)
        if "No such container" in error_msg:
            return f"<i>Container {html.escape(container_name)} not found</i>"
        return f"<i>Error getting logs:</i> <code>{html.escape(error_msg)}</code>"
    except FileNotFoundError:
        return "<i>Docker command not found. Ensure docker is installed and accessible.</i>"
    except Exception as e:
        logger.exception("Error getting container logs")
        return f"<i>Error:</i> <code>{html.escape(str(e))}</code>"


def get_top_processes() -> str:
    """Get top processes using ps command."""
    try:
        out = subprocess.check_output(
            ["/bin/ps", "aux", "--sort=-%cpu"],
            text=True,
            timeout=5,
        ).strip()
        lines = out.splitlines()[:11]  # Header + top 10
        return f"<b>Top Processes:</b>\n<pre>{html.escape(chr(10).join(lines))}</pre>"
    except FileNotFoundError:
        return "<i>ps command not found</i>"
    except Exception as e:
        logger.exception("Error getting top processes")
        return f"<i>Error:</i> <code>{html.escape(str(e))}</code>"


def get_uptime_info() -> str:
    """Get simple uptime information."""
    return f"<b>Uptime:</b> {human_uptime()}"


def get_version_info() -> str:
    """Get version and build information."""
    lines = ["<b>Version Info:</b>"]
    
    # Try to get latest git commit date (suppress stderr to avoid logs when .git missing)
    try:
        out = subprocess.check_output(
            ["git", "log", "-1", "--format=%cd", "--date=format:%Y-%m-%d %H:%M:%S"],
            text=True,
            timeout=3,
            cwd="/app",
            stderr=subprocess.DEVNULL,
        ).strip()
        if out:
            lines.append(f"<b>Last Commit:</b> {html.escape(out)}")
    except Exception:
        pass
    
    # Try to get git commit hash (suppress stderr)
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            text=True,
            timeout=3,
            cwd="/app",
            stderr=subprocess.DEVNULL,
        ).strip()
        if out:
            lines.append(f"<b>Commit:</b> <code>{html.escape(out)}</code>")
    except Exception:
        pass
    
    # Python version
    import sys
    lines.append(f"<b>Python:</b> {sys.version.split()[0]}")
    
    # Package info
    lines.append("<b>Package:</b> tele-home-supervisor")
    
    # Startup time
    try:
        from . import main
        startup = main.STARTUP_TIME.strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"<b>Started:</b> {startup}")
    except Exception:
        pass
    
    if len(lines) == 1:
        return "<i>Version information not available</i>"
    
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
    "get_container_logs",
    "get_top_processes",
    "get_uptime_info",
    "get_version_info",
]
