"""Utility helpers: system info and Docker helpers.

This module provides async functions that return raw data (dicts/lists).
Presentation logic is handled by the view layer.
"""

from __future__ import annotations

import asyncio
import re
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
    """Format bytes to human readable string using binary units (e.g. 1.2 GiB).

    Args:
        n: Number of bytes to format

    Returns:
        Human-readable string with appropriate unit (B, KiB, MiB, GiB, TiB)

    Example:
        >>> fmt_bytes(1536)
        '1.5 KiB'
        >>> fmt_bytes(1073741824)
        '1.0 GiB'
    """
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    i = 0
    f = float(n)
    while f >= 1024 and i < len(units) - 1:
        f /= 1024
        i += 1
    return f"{f:.1f} {units[i]}"


async def get_primary_ip() -> str:
    """Get the primary LAN IP address of this host.

    First attempts to use `ip route` command, then falls back to psutil
    to find the first non-loopback IPv4 address.

    Returns:
        IP address string, or "unknown" if not found

    Note:
        Prefers the IP used for routing to 1.1.1.1 to ensure we get
        the primary outbound interface.
    """
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
    """Get the public WAN IP address using external services.

    Tries multiple services in sequence:
    1. AWS checkip
    2. ipinfo.io
    3. ifconfig.me

    Returns:
        Public IP address string, or "n/a" if all services fail

    Note:
        Has a 5-second timeout to avoid blocking on network issues.
    """
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
            except Exception as sensor_error:
                logger.debug(
                    f"Skipping unreadable temperature sensor {p}: {sensor_error}"
                )
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
    """Collect comprehensive system health information.

    Args:
        watch_paths: List of filesystem paths to monitor for disk usage.
                    Defaults to ["/", "/srv/media"] if not specified.

    Returns:
        Dictionary containing:
        - host: hostname
        - system: OS name
        - release: OS release
        - time: current time with timezone
        - lan_ip: local IP address
        - wan_ip: public IP address
        - uptime: system uptime in human-readable format
        - load: system load averages (1m, 5m, 15m)
        - cpu_pct: CPU usage percentage
        - mem_used/mem_total/mem_pct: memory statistics
        - temp: CPU temperature
        - disks: list of disk usage strings

    Note:
        This function performs I/O operations and network requests,
        so it may take a few seconds to complete.
    """
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
    def _safe_int(value: object, default: int = 0) -> int:
        try:
            return int(value)
        except Exception:
            return default

    def _calc_cpu_pct(stats: dict) -> float:
        cpu_stats = stats.get("cpu_stats", {}) or {}
        pre_cpu = stats.get("precpu_stats", {}) or {}
        cpu_total = _safe_int((cpu_stats.get("cpu_usage", {}) or {}).get("total_usage"))
        pre_total = _safe_int((pre_cpu.get("cpu_usage", {}) or {}).get("total_usage"))
        system_total = _safe_int(cpu_stats.get("system_cpu_usage"))
        pre_system_total = _safe_int(pre_cpu.get("system_cpu_usage"))
        cpu_delta = cpu_total - pre_total
        system_delta = system_total - pre_system_total
        num_cpus = cpu_stats.get("online_cpus")
        if not num_cpus:
            per_cpu = (cpu_stats.get("cpu_usage", {}) or {}).get("percpu_usage") or []
            num_cpus = len(per_cpu)
        if cpu_delta > 0 and system_delta > 0 and num_cpus:
            return (cpu_delta / system_delta) * float(num_cpus) * 100.0
        return 0.0

    def _sum_network_io(stats: dict) -> tuple[int, int]:
        rx = 0
        tx = 0
        networks = stats.get("networks") or {}
        for entry in networks.values():
            rx += _safe_int(entry.get("rx_bytes"))
            tx += _safe_int(entry.get("tx_bytes"))
        return rx, tx

    def _sum_block_io(stats: dict) -> tuple[int, int]:
        read = 0
        write = 0
        blk = stats.get("blkio_stats") or {}
        for entry in blk.get("io_service_bytes_recursive") or []:
            op = (entry.get("op") or "").lower()
            if op == "read":
                read += _safe_int(entry.get("value"))
            elif op == "write":
                write += _safe_int(entry.get("value"))
        return read, write

    def _collect():
        try:
            containers = client.containers.list(all=True)
        except Exception as e:
            logger.debug("container stats list failed: %s", e)
            return []

        result: list[dict[str, str]] = []
        for c in containers:
            try:
                stats = c.stats(stream=False)
            except Exception as e:
                logger.debug("container stats failed for %s: %s", c.name, e)
                continue

            cpu_pct = _calc_cpu_pct(stats)
            mem_stats = stats.get("memory_stats", {}) or {}
            mem_used = _safe_int(mem_stats.get("usage"))
            mem_limit = _safe_int(mem_stats.get("limit"))
            mem_pct = (mem_used / mem_limit * 100.0) if mem_limit else 0.0
            rx, tx = _sum_network_io(stats)
            blk_read, blk_write = _sum_block_io(stats)
            pids = _safe_int((stats.get("pids_stats") or {}).get("current"))

            mem_usage = (
                f"{fmt_bytes(mem_used)}/{fmt_bytes(mem_limit)}"
                if mem_limit
                else f"{fmt_bytes(mem_used)}/-"
            )
            result.append(
                {
                    "name": getattr(c, "name", "unknown"),
                    "cpu": f"{cpu_pct:.2f}%",
                    "mem_pct": f"{mem_pct:.2f}%",
                    "mem_usage": mem_usage,
                    "netio": f"{fmt_bytes(rx)}/{fmt_bytes(tx)}",
                    "blockio": f"{fmt_bytes(blk_read)}/{fmt_bytes(blk_write)}",
                    "pids": str(pids),
                }
            )
        return result

    return await asyncio.to_thread(_collect)


async def get_container_logs(container_name: str, lines: int = 50) -> str:
    """Return raw log string from a Docker container.

    Args:
        container_name: Name or ID of the container
        lines: Number of lines to retrieve. Positive for tail, negative for head.

    Returns:
        Container log output as a string, or error message if failed.

    Note:
        Negative line numbers retrieve from the start of the log (head),
        positive numbers retrieve from the end (tail).
    """

    def _decode(raw: object) -> str:
        if isinstance(raw, bytes):
            return raw.decode(errors="replace")
        return str(raw)

    def _fetch():
        try:
            container = client.containers.get(container_name)
        except Exception as e:
            return f"Error: {e}"

        try:
            if lines < 0:
                raw = container.logs(stdout=True, stderr=True)
                combined = _decode(raw).strip()
                log_lines = combined.splitlines()
                requested = abs(lines)
                return "\n".join(log_lines[:requested])

            raw = container.logs(stdout=True, stderr=True, tail=lines)
            return _decode(raw).strip()
        except Exception as e:
            logger.exception("Unexpected error getting container logs")
            return f"Unexpected error: {e}"

    return await asyncio.to_thread(_fetch)


async def get_container_logs_full(container_name: str, since: int | None = None) -> str:
    """Return full raw log string from a Docker container.

    Args:
        container_name: Name or ID of the container.
        since: Optional Unix timestamp (seconds) to filter logs from.
    """

    def _decode(raw: object) -> str:
        if isinstance(raw, bytes):
            return raw.decode(errors="replace")
        return str(raw)

    def _fetch():
        try:
            container = client.containers.get(container_name)
        except Exception as e:
            return f"Error: {e}"

        try:
            raw = container.logs(stdout=True, stderr=True, since=since)
            return _decode(raw).strip()
        except Exception as e:
            logger.exception("Unexpected error getting container logs")
            return f"Unexpected error: {e}"

    return await asyncio.to_thread(_fetch)


async def healthcheck_container(container_name: str) -> str:
    def _inspect():
        try:
            container = client.containers.get(container_name)
        except Exception:
            return f"Error inspecting {container_name}"

        try:
            container.reload()
            state = container.attrs.get("State", {}) or {}
            health = state.get("Health")
            if health:
                return f"Health: {health.get('Status', 'unknown')}"
            status = state.get("Status") or (
                "running" if state.get("Running") else "stopped"
            )
            return f"Status: {status}"
        except Exception as e:
            return f"Error parsing state: {e}"

    return await asyncio.to_thread(_inspect)


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
    info["commit_hash"] = os.environ.get("TELE_HOME_SUPERVISOR_COMMIT", "")
    info["last_commit"] = os.environ.get("TELE_HOME_SUPERVISOR_COMMIT_TIME", "")
    info["image"] = os.environ.get("TELE_HOME_SUPERVISOR_IMAGE", "")
    info["image_tag"] = os.environ.get("TELE_HOME_SUPERVISOR_IMAGE_TAG", "")
    info["image_digest"] = os.environ.get("TELE_HOME_SUPERVISOR_IMAGE_DIGEST", "")
    info["host"] = os.environ.get("HOSTNAME", "")
    info["run_number"] = os.environ.get("GITHUB_RUN_NUMBER", "")
    info["run_id"] = os.environ.get("GITHUB_RUN_ID", "")
    info["ref_name"] = os.environ.get("GITHUB_REF_NAME", "")
    info["workflow"] = os.environ.get("GITHUB_WORKFLOW", "")
    info["repository"] = os.environ.get("GITHUB_REPOSITORY", "")

    if not info["last_commit"]:
        rc, out, _ = await cli.run_cmd(
            ["git", "log", "-1", "--format=%cd", "--date=format:%Y-%m-%d %H:%M:%S"],
            timeout=3,
        )
        if rc == 0:
            info["last_commit"] = out.strip()

    if not info["commit_hash"]:
        rc, out, _ = await cli.run_cmd(
            ["git", "rev-parse", "--short", "HEAD"], timeout=3
        )
        if rc == 0:
            info["commit_hash"] = out.strip()

    import sys

    info["python"] = sys.version.split()[0]

    try:
        from .runtime import STARTUP_TIME

        info["started"] = STARTUP_TIME.strftime("%Y-%m-%d %H:%M:%S")
    except ImportError:
        pass

    info = {k: v for k, v in info.items() if v}
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
    """Resolve a hostname to IP addresses.

    Args:
        name: Hostname or domain to resolve

    Returns:
        Formatted string with lookup time and resolved IPs (IPv4 and IPv6),
        or error message if resolution fails.

    Example output:
        Lookup time: 45ms
        A:
          1.2.3.4
        AAAA:
          2001:db8::1
    """

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


def _fmt_rate_kbits(bits_per_s: float) -> str:
    """Format rate in Kb/s or Mb/s (bits), switching at 1000 Kb/s."""
    kbps = float(max(0.0, bits_per_s)) / 1000.0
    if kbps < 1000.0:
        return f"{kbps:.2f} Kb/s"
    return f"{kbps / 1000.0:.2f} Mb/s"


async def speedtest_download(mb: int = 100) -> str:
    """Download speed test using curl and Cloudflare's speed test endpoint.

    Args:
        mb: Size in megabytes to download (minimum 1, default 100)

    Returns:
        Formatted string with download size, time, and speed in Mb/s or Kb/s,
        or error message if test fails.

    Note:
        Uses a 30-second timeout and downloads from speed.cloudflare.com.
        Bandwidth is calculated in bits per second for accurate network measurements.
    """
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
            "TIME:%{time_total} SIZE:%{size_download}\n",
            url,
        ],
        timeout=35,
    )

    if rc != 0:
        return f"Speedtest failed: {err or out}"

    try:
        out_clean = (out.strip() + "\n" + err.strip()).strip()
        m = re.search(r"TIME:([0-9.]+)\s+SIZE:([0-9.]+)", out_clean)
        if m:
            seconds = float(m.group(1))
            downloaded = float(m.group(2))
        else:
            m = re.search(
                r"([0-9]+\.[0-9]+|[0-9]+)\s+([0-9]+\.[0-9]+|[0-9]+)",
                out_clean,
            )
            if not m:
                logger.warning("Speedtest output has insufficient parts: %s", out_clean)
                return "Speedtest failed: invalid output format"
            seconds = float(m.group(1))
            downloaded = float(m.group(2))
        if seconds <= 0:
            return "Invalid duration"

        # bits per second
        bits_per_s = (downloaded * 8.0) / seconds

        return (
            f"Size: {downloaded / 1_000_000.0:.1f}MB\n"
            f"Time: {seconds:.2f}s\n"
            f"Rate: {_fmt_rate_kbits(bits_per_s)}"
        )
    except (ValueError, IndexError) as e:
        logger.error(f"Speedtest parse error. Output: '{out[:200]}', Error: {e}")
        return f"Parse error: {e}"
