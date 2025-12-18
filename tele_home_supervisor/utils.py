"""Utility helpers: system info and Docker helpers.

This module provides async functions that return raw data (dicts/lists).
Presentation logic is handled by the view layer.
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import socket
import shutil
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any

import docker
import psutil

from . import cli

if TYPE_CHECKING:
    from docker.client import DockerClient  # type: ignore

logger = logging.getLogger(__name__)

# docker client (shared)
client: "DockerClient" = docker.from_env()


def fmt_bytes(n: int) -> str:
    """Format bytes to human readable string (e.g. 1.2 GiB)."""
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    i = 0
    f = float(n)
    while f >= 1024 and i < len(units) - 1:
        f /= 1024
        i += 1
    return f"{f:.1f} {units[i]}"


async def get_primary_ip() -> str:
    rc, out, err = await cli.run_cmd(
        ["bash", "-lc", "ip route get 1.1.1.1 | awk '{print $7; exit}'"], timeout=2
    )
    out = out.strip()
    if rc == 0 and out:
        return out

    try:

        def _get_ip():
            for iface, addrs in psutil.net_if_addrs().items():
                for a in addrs:
                    if a.family == socket.AF_INET and not a.address.startswith("127."):
                        return a.address
            return "unknown"

        return await asyncio.to_thread(_get_ip)
    except Exception:
        logger.debug("primary ip via psutil failed", exc_info=True)
    return "unknown"


async def get_wan_ip() -> str:
    rc, out, err = await cli.run_cmd(
        [
            "bash",
            "-lc",
            "curl -fsS https://checkip.amazonaws.com || curl -fsS https://ipinfo.io/ip || curl -fsS https://ifconfig.me",
        ],
        timeout=5,
    )
    out = out.strip()
    if rc == 0 and out:
        return out
    return "n/a"


async def get_temp() -> str:
    for path in [
        "/sys/class/thermal/thermal_zone0/temp",
        "/sys/class/thermal/thermal_zone1/temp",
    ]:
        try:
            if os.path.exists(path):
                with open(path) as f:
                    t = f.read().strip()
                if t and t.isdigit():
                    return f"{int(t) / 1000:.1f}°C"
        except (OSError, ValueError) as e:
            logger.debug("Error reading temp from %s: %s", path, e)

    vcgencmd = shutil.which("vcgencmd")
    if vcgencmd:
        rc, out, err = await cli.run_cmd([vcgencmd, "measure_temp"], timeout=2)
        if rc == 0 and out:
            return out.strip()

    return "n/a"


async def get_cpu_temp() -> str:
    """Read CPU temperature from a mounted host path or system thermal zone."""

    def _read():
        paths = [
            "/host_thermal/temp",
            "/sys/class/thermal/thermal_zone0/temp",
            "/sys/class/thermal/thermal_zone1/temp",
        ]
        for p in paths:
            try:
                if not os.path.exists(p):
                    continue
                with open(p, "r") as f:
                    raw = f.read().strip()
                if not raw:
                    continue
                try:
                    val = int(raw)
                    temp = val / 1000.0
                    return f"CPU Temp: {temp:.1f}°C"
                except ValueError:
                    try:
                        temp = float(raw)
                        if temp > 100:
                            temp = temp / 1000.0
                        return f"CPU Temp: {temp:.1f}°C"
                    except ValueError:
                        continue
            except Exception:
                continue
        return "Error: Could not read temperature."

    return await asyncio.to_thread(_read)


def human_uptime() -> str:
    boot = psutil.boot_time()
    secs = int(time.time() - boot)
    d, r = divmod(secs, 86400)
    h, r = divmod(r, 3600)
    m, _ = divmod(r, 60)
    return f"{d}d {h}h {m}m"


async def host_health(watch_paths: list[str] | None = None) -> dict[str, Any]:
    if watch_paths is None:
        watch_paths = ["/", "/srv/media"]

    def _collect_sync():
        cpu_pct = psutil.cpu_percent(interval=0.5)
        v = psutil.virtual_memory()
        try:
            load1, load5, load15 = os.getloadavg()
        except (OSError, AttributeError):
            load1 = load5 = load15 = 0.0

        disk_info = []
        for path in watch_paths:
            try:
                du = psutil.disk_usage(path)
                disk_info.append(
                    f"{path}: {fmt_bytes(du.used)}/{fmt_bytes(du.total)} ({du.percent:.0f}%)"
                )
            except Exception:
                disk_info.append(f"{path}: n/a")
        return cpu_pct, v, (load1, load5, load15), disk_info

    cpu_pct, v, loads, disks = await asyncio.to_thread(_collect_sync)

    temp = await get_temp()
    lan_ip = await get_primary_ip()
    wan_ip = await get_wan_ip()

    return {
        "host": platform.node(),
        "system": platform.system(),
        "release": platform.release(),
        "time": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"),
        "lan_ip": lan_ip,
        "wan_ip": wan_ip,
        "uptime": human_uptime(),
        "load": f"{loads[0]:.2f} {loads[1]:.2f} {loads[2]:.2f}",
        "cpu_pct": int(cpu_pct),
        "mem_used": fmt_bytes(v.used),
        "mem_total": fmt_bytes(v.total),
        "mem_pct": int(v.percent),
        "temp": temp,
        "disks": disks,
    }


def _format_ports(pmap: dict[str, list[dict[str, str]] | None] | None) -> str:
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


async def list_containers_basic() -> list[dict[str, Any]]:
    def _list():
        try:
            return client.containers.list(all=True)
        except Exception:
            return []

    cs = await asyncio.to_thread(_list)
    result = []
    for c in cs:
        try:
            result.append(
                {
                    "name": c.name,
                    "image": c.image.tags[0] if c.image.tags else c.image.short_id,
                    "status": c.status,
                    "ports": _format_ports(
                        c.attrs.get("NetworkSettings", {}).get("Ports")
                    ),
                }
            )
        except Exception:
            result.append({"name": getattr(c, "name", "unknown"), "error": True})
    return result


async def list_container_names() -> set[str]:
    def _list():
        try:
            return client.containers.list(all=True)
        except Exception:
            return []

    cs = await asyncio.to_thread(_list)
    names = set()
    for c in cs:
        name = getattr(c, "name", None)
        if name:
            names.add(str(name))
    return names


async def container_stats_rich() -> list[dict[str, str]]:
    docker_cmd = cli.get_docker_cmd()
    if not docker_cmd:
        return []

    fmt = "{{.Name}}\t{{.CPUPerc}}\t{{.MemPerc}}\t{{.MemUsage}}\t{{.NetIO}}\t{{.BlockIO}}\t{{.PIDs}}"
    rc, out, err = await cli.run_cmd(
        [docker_cmd, "stats", "--no-stream", "--format", fmt], timeout=6
    )

    if rc != 0 or not out:
        return []

    stats = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 7:
            name, cpu, mem_pct, mem_usage, netio, blockio, pids = parts[:7]
            stats.append(
                {
                    "name": name,
                    "cpu": cpu,
                    "mem_pct": mem_pct,
                    "mem_usage": mem_usage,
                    "netio": netio,
                    "blockio": blockio,
                    "pids": pids,
                }
            )
    return stats


async def get_container_logs(container_name: str, lines: int = 50) -> str:
    """Return raw log string."""
    docker_cmd = cli.get_docker_cmd()
    if not docker_cmd:
        return "Docker command not found."

    try:
        if lines < 0:
            rc, out, err = await cli.run_cmd(
                [docker_cmd, "logs", container_name], timeout=15
            )
            if rc != 0:
                return f"Error: {err or out}"
            combined = (out + err).strip()
            log_lines = combined.splitlines()
            requested = abs(lines)
            return "\n".join(log_lines[:requested])
        else:
            rc, out, err = await cli.run_cmd(
                [docker_cmd, "logs", "--tail", str(lines), container_name], timeout=15
            )
            if rc != 0:
                return f"Error: {err or out}"
            return (out + err).strip()

    except Exception as e:
        return f"Unexpected error: {e}"


async def healthcheck_container(container_name: str) -> str:
    docker_cmd = cli.get_docker_cmd()
    if not docker_cmd:
        return "Docker CLI not available"

    rc, out, err = await cli.run_cmd(
        [docker_cmd, "inspect", "--format", "{{json .State}}", container_name],
        timeout=4,
    )
    if rc != 0:
        return f"Error inspecting {container_name}"

    import json

    try:
        state = json.loads(out)
        health = state.get("Health")
        if health:
            return f"Health: {health.get('Status', 'unknown')}"
        status = state.get("Status") or (
            "running" if state.get("Running") else "stopped"
        )
        return f"Status: {status}"
    except Exception as e:
        return f"Error parsing state: {e}"


async def ping_host(host: str, count: int = 3) -> str:
    ping_bin = shutil.which("ping") or "/bin/ping"
    rc, out, err = await cli.run_cmd(
        [ping_bin, "-c", str(count), "-W", "2", host], timeout=10
    )
    return out.strip() if out else (err or "No output")


async def get_top_processes() -> str:
    rc, out, err = await cli.run_cmd(["/bin/ps", "aux", "--sort=-%cpu"], timeout=5)
    if rc != 0:
        return "Failed to get process list"
    return "\n".join(out.splitlines()[:11])


async def get_uptime_info() -> str:
    return human_uptime()


async def get_version_info() -> dict[str, str]:
    info = {}
    info["build"] = os.environ.get("TELE_HOME_SUPERVISOR_BUILD_VERSION", "")

    rc, out, _ = await cli.run_cmd(
        ["git", "log", "-1", "--format=%cd", "--date=format:%Y-%m-%d %H:%M:%S"],
        timeout=3,
    )
    if rc == 0:
        info["last_commit"] = out.strip()

    rc, out, _ = await cli.run_cmd(["git", "rev-parse", "--short", "HEAD"], timeout=3)
    if rc == 0:
        info["commit_hash"] = out.strip()

    import sys

    info["python"] = sys.version.split()[0]

    try:
        from .runtime import STARTUP_TIME

        info["started"] = STARTUP_TIME.strftime("%Y-%m-%d %H:%M:%S")
    except ImportError:
        pass

    return info


async def get_listening_ports() -> str:
    """List listening TCP/UDP ports."""
    ss_bin = shutil.which("ss")
    if not ss_bin:
        return "ss command not available"

    rc, out, err = await cli.run_cmd([ss_bin, "-tulpn"], timeout=6)
    if rc != 0:
        return f"Error: {err or out}"

    lines = out.strip().splitlines()
    return "\n".join(lines[:60])


async def dns_lookup(name: str) -> str:
    """Resolve a hostname."""

    def _resolve():
        try:
            start = time.monotonic()
            infos = socket.getaddrinfo(name, None)
            elapsed_ms = (time.monotonic() - start) * 1000.0

            ipv4 = set()
            ipv6 = set()
            for family, _, _, _, sockaddr in infos:
                ip = sockaddr[0]
                if family == socket.AF_INET:
                    ipv4.add(ip)
                elif family == socket.AF_INET6:
                    ipv6.add(ip)

            lines = [f"Lookup time: {elapsed_ms:.0f}ms"]
            if ipv4:
                lines.append("A:")
                lines.extend(f"  {ip}" for ip in sorted(ipv4))
            if ipv6:
                lines.append("AAAA:")
                lines.extend(f"  {ip}" for ip in sorted(ipv6))
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {e}"

    return await asyncio.to_thread(_resolve)


async def traceroute_host(host: str, max_hops: int = 20) -> str:
    """Trace route to host."""
    tracepath_bin = shutil.which("tracepath")
    traceroute_bin = shutil.which("traceroute")
    cmd = None
    if tracepath_bin:
        cmd = [tracepath_bin, "-n", "-m", str(max_hops), host]
    elif traceroute_bin:
        cmd = [traceroute_bin, "-n", "-m", str(max_hops), "-q", "1", "-w", "2", host]

    if not cmd:
        return "tracepath/traceroute not available"

    rc, out, err = await cli.run_cmd(cmd, timeout=25)
    return out.strip() or err.strip()


def _fmt_rate_bps(bytes_per_s: float) -> str:
    units = ["B/s", "KB/s", "MB/s", "GB/s"]
    value = float(max(0.0, bytes_per_s))
    unit_idx = 0
    while value >= 1000.0 and unit_idx < len(units) - 1:
        value /= 1000.0
        unit_idx += 1
    return f"{value:.2f} {units[unit_idx]}"


async def speedtest_download(mb: int = 10) -> str:
    """Download speed test using curl."""
    curl_bin = shutil.which("curl")
    if not curl_bin:
        return "curl not available"

    bytes_to_download = max(1, int(mb)) * 1_000_000
    url = f"https://speed.cloudflare.com/__down?bytes={bytes_to_download}"

    rc, out, err = await cli.run_cmd(
        [
            curl_bin,
            "-fsSL",
            "--max-time",
            "30",
            "-o",
            "/dev/null",
            "-w",
            "%{{time_total}} %{{size_download}}\n",
            url,
        ],
        timeout=35,
    )

    if rc != 0:
        return f"Speedtest failed: {err or out}"

    try:
        parts = out.strip().split()
        seconds = float(parts[0])
        downloaded = float(parts[1])
        if seconds <= 0:
            return "Invalid duration"

        bps = downloaded / seconds
        mbps = (downloaded * 8.0) / seconds / 1_000_000.0

        return (
            f"Size: {downloaded / 1_000_000.0:.1f}MB\n"
            f"Time: {seconds:.2f}s\n"
            f"Rate: {_fmt_rate_bps(bps)} ({mbps:.1f} Mbps)"
        )
    except Exception as e:
        return f"Parse error: {e}"
