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
import shutil
import json
from .cli import run_cmd, get_docker_cmd

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
        rc, out, err = run_cmd(
            ["bash", "-lc", "ip route get 1.1.1.1 | awk '{print $7; exit}'"], timeout=2
        )
        out = out.strip()
        if rc == 0 and out:
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
        rc, out, err = run_cmd(
            [
                "bash",
                "-lc",
                "curl -fsS https://ipinfo.io/ip || curl -fsS https://ifconfig.me",
            ],
            timeout=4,
        )
        out = out.strip()
        if rc == 0 and out:
            return out
        return "n/a"
    except Exception:
        logger.debug("WAN IP check failed", exc_info=True)
        return "n/a"


def get_temp() -> str:
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


def get_cpu_temp() -> str:
    """Read CPU temperature from a mounted host path (/host_thermal/temp).

    The value is expected in millidegrees (e.g. 42000), so we divide by 1000.
    """
    # Try mounted host thermal path first
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
            # Some systems provide float or integer in millidegrees
            if not raw:
                continue
            # Try to parse as int (millidegrees)
            try:
                val = int(raw)
                temp = val / 1000.0
                return f"CPU Temp: {temp:.1f}°C"
            except ValueError:
                # Try float
                try:
                    temp = float(raw)
                    # if value looks like millidegrees (>100), divide
                    if temp > 100:
                        temp = temp / 1000.0
                    return f"CPU Temp: {temp:.1f}°C"
                except ValueError:
                    continue
        except Exception:
            logger.debug("Error reading temperature from %s", p, exc_info=True)
            continue
    return "Error: Could not read temperature."


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
            disks.append(
                f"{path}: {fmt_bytes(du.used)}/{fmt_bytes(du.total)} ({du.percent:.0f}%)"
            )
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
            ports = html.escape(
                format_ports(c.attrs.get("NetworkSettings", {}).get("Ports"))
            )
            lines.append(
                f"<code>{name}</code> • {status} • <code>{image}</code> • {ports}"
            )
        except Exception:
            logger.exception(
                "Error while formatting container %s", getattr(c, "name", "<unknown>")
            )
            lines.append(
                f"<code>{html.escape(getattr(c, 'name', 'unknown'))}</code> • error"
            )
    return "\n".join(lines)


def list_container_names() -> set[str]:
    """Return container names seen via Docker API."""
    try:
        cs = client.containers.list(all=True)
    except Exception:
        logger.exception("Docker API error while listing containers (names)")
        return set()
    names: set[str] = set()
    for c in cs:
        try:
            if c.name:
                names.add(str(c.name))
        except Exception:
            continue
    return names


def container_stats_summary() -> str:
    """Get container stats using docker stats CLI (much faster than API)."""
    # Use centralized docker detection and delegate to the rich formatter
    docker_cmd = get_docker_cmd()
    if not docker_cmd:
        return "<i>Docker CLI not available in container</i>"
    return container_stats_rich()


def container_stats_rich() -> str:
    """Return extended container stats using `docker stats --no-stream`.

    Includes net IO and block IO if available.
    """
    docker_cmd = get_docker_cmd()
    if not docker_cmd:
        return "<i>Docker CLI not available in container</i>"

    fmt = "{{.Name}}\t{{.CPUPerc}}\t{{.MemPerc}}\t{{.MemUsage}}\t{{.NetIO}}\t{{.BlockIO}}\t{{.PIDs}}"
    rc, out, err = run_cmd(
        [docker_cmd, "stats", "--no-stream", "--format", fmt], timeout=5
    )
    if rc != 0:
        logger.debug("docker stats returned non-zero: %s %s", rc, err)
        return "<i>Docker stats error</i>"
    out = out.strip()
    if not out:
        return "<i>No running containers.</i>"
    lines = ["<b>Container Detailed Stats:</b>"]
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 7:
            name, cpu, mem_pct, mem_usage, netio, blockio, pids = parts[:7]
            lines.append(
                f"<code>{html.escape(name)}</code> "
                f"CPU {html.escape(cpu)} MEM {html.escape(mem_pct)} ({html.escape(mem_usage)})\n"
                f"Net I/O: {html.escape(netio)} Block I/O: {html.escape(blockio)} PIDs: {html.escape(pids)}"
            )
    return "\n\n".join(lines)


def get_container_logs(container_name: str, lines: int = 50) -> str:
    """Get logs from a container.

    Args:
        container_name: Name or ID of the container
        lines: Number of lines to fetch. Positive = tail (last N lines),
               Negative = head (first N lines). Default: 50 (last 50 lines)

    Returns:
        Formatted HTML string with logs or error message
    """
    docker_cmd = get_docker_cmd()
    if not docker_cmd:
        return "<i>Docker command not found. Ensure docker is installed and accessible.</i>"

    try:
        err = ""  # Initialize for error handling

        if lines < 0:
            # Get first N lines: fetch all logs and process in Python
            # Note: Docker writes logs to both stdout and stderr, we need to combine them
            rc, out, err = run_cmd([docker_cmd, "logs", container_name], timeout=15)
            if rc != 0:
                raise subprocess.CalledProcessError(rc, "docker logs", output=err)

            # Combine stdout and stderr (docker logs can write to both)
            combined = (out + err).strip()

            # Take first N lines
            log_lines = combined.splitlines()
            requested_lines = abs(lines)
            total_lines = len(log_lines)
            out = "\n".join(log_lines[:requested_lines])

            # Show info about total available lines
            if total_lines > requested_lines:
                out = (
                    out
                    + f"\n...\n<i>(showing first {requested_lines} of {total_lines} total lines)</i>"
                )
            else:
                out = out + f"\n<i>(total: {total_lines} lines available)</i>"
        else:
            # Get last N lines using --tail
            rc, out, err = run_cmd(
                [docker_cmd, "logs", "--tail", str(lines), container_name], timeout=15
            )
            if rc != 0:
                raise subprocess.CalledProcessError(rc, "docker logs", output=err)

            # Combine stdout and stderr
            out = (out + err).strip()

            # Get total line count for context
            rc_count, out_count, err_count = run_cmd(
                [docker_cmd, "logs", container_name], timeout=15
            )
            combined_count = (out_count + err_count).strip()
            total_lines = len(combined_count.splitlines()) if rc_count == 0 else 0

        out = out.strip()
        if not out:
            return f"<i>Container {html.escape(container_name)} has no logs</i>"

        # Limit output to avoid Telegram message size issues
        max_chars = 3500
        if len(out) > max_chars:
            if lines < 0:
                # For head, truncate from end
                out = out[:max_chars] + "\n...\n<i>(truncated)</i>"
            else:
                # For tail, truncate from beginning
                out = "...\n" + out[-max_chars:]

        safe_name = html.escape(container_name)
        direction = "first" if lines < 0 else "last"
        count = abs(lines)

        # Add total available context for tail mode
        if lines > 0 and total_lines > 0:
            count_info = f"{count} requested, {total_lines} available"
        else:
            count_info = str(count)

        return (
            f"<b>Logs for {safe_name}</b> <i>({direction} {count_info} lines)</i>\n"
            f"<pre>{html.escape(out)}</pre>"
        )

    except subprocess.TimeoutExpired:
        return f"<i>Timeout getting logs for {html.escape(container_name)}</i>"
    except subprocess.CalledProcessError as e:
        error_msg = (err or str(e.output) or str(e)).strip()
        if "No such container" in error_msg or "not found" in error_msg.lower():
            return f"<i>Container {html.escape(container_name)} not found</i>"
        return f"<i>Error getting logs for {html.escape(container_name)}:</i>\n<code>{html.escape(error_msg)}</code>"
    except FileNotFoundError:
        return "<i>Docker command not found. Ensure docker is installed and accessible.</i>"
    except Exception as e:
        logger.exception("Error getting container logs for %s", container_name)
        return f"<i>Unexpected error:</i> <code>{html.escape(str(e))}</code>"


def healthcheck_container(container_name: str) -> str:
    """Check container health/status via `docker inspect`.

    Returns Health.Status if present, otherwise container State/status.
    """
    docker_cmd = get_docker_cmd()
    if not docker_cmd:
        return "<i>Docker CLI not available in container</i>"
    try:
        rc, out, err = run_cmd(
            [docker_cmd, "inspect", "--format", "{{json .State}}", container_name],
            timeout=4,
        )
        if rc != 0:
            err_text = err or out
            if "No such object" in err_text or "No such container" in err_text:
                return f"<i>Container {html.escape(container_name)} not found</i>"
            logger.exception(
                "Error inspecting container %s: %s %s", container_name, rc, err_text
            )
            return f"<i>Error:</i> <code>{html.escape(str(err_text))}</code>"
        state = json.loads(out)
        health = state.get("Health")
        if health:
            status = health.get("Status", "unknown")
            return f"<b>Container:</b> <code>{html.escape(container_name)}</code>\n<b>Health:</b> {html.escape(status)}"
        # Fallback to general state fields
        status = state.get("Status") or (
            "running" if state.get("Running") else "stopped"
        )
        exit_code = state.get("ExitCode")
        s = f"<b>Container:</b> <code>{html.escape(container_name)}</code>\n<b>Status:</b> {html.escape(str(status))}"
        if exit_code is not None:
            s += f"\n<b>ExitCode:</b> {exit_code}"
        return s
    except subprocess.CalledProcessError as e:
        err = e.output or str(e)
        if "No such object" in err or "No such container" in err:
            return f"<i>Container {html.escape(container_name)} not found</i>"
        logger.exception("Error inspecting container %s", container_name)
        return f"<i>Error:</i> <code>{html.escape(str(err))}</code>"
    except Exception as e:
        logger.exception("Error running healthcheck for %s", container_name)
        return f"<i>Error:</i> <code>{html.escape(str(e))}</code>"


def ping_host(host: str, count: int = 3) -> str:
    """Ping an IP or hostname and return a short summary."""
    ping_bin = shutil.which("ping") or "/bin/ping"
    if not ping_bin or not os.path.exists(ping_bin):
        return "<i>ping command not available in container</i>"
    try:
        rc, out, err = run_cmd(
            [ping_bin, "-c", str(count), "-W", "2", host], timeout=10
        )
        out = out.strip()
        if not out:
            return "<i>No output from ping</i>"
        lines = out.splitlines()
        sample = "\n".join(lines[-6:])
        return f"<b>Ping {html.escape(host)}:</b>\n<pre>{html.escape(sample)}</pre>"
    except Exception as e:
        logger.exception("Error pinging %s", host)
        return f"<i>Error:</i> <code>{html.escape(str(e))}</code>"


def get_listening_ports() -> str:
    """List listening TCP/UDP ports (inside the container)."""
    ss_bin = shutil.which("ss")
    if not ss_bin:
        return "<i>ss command not available in container</i>"
    try:
        rc, out, err = run_cmd([ss_bin, "-tulpn"], timeout=6)
        out = out.strip()
        if rc != 0:
            err_text = (err or out).strip() or "unknown error"
            return f"<i>Failed to list ports:</i> <code>{html.escape(err_text)}</code>"
        if not out:
            return "<i>No output from ss</i>"
        lines = out.splitlines()
        sample = "\n".join(lines[:60])
        return f"<b>Listening Ports:</b>\n<pre>{html.escape(sample)}</pre>"
    except Exception as e:
        logger.exception("Error listing ports")
        return f"<i>Error:</i> <code>{html.escape(str(e))}</code>"


def dns_lookup(name: str) -> str:
    """Resolve a hostname using the container's resolver."""
    start = time.monotonic()
    try:
        infos = socket.getaddrinfo(name, None)
    except socket.gaierror as e:
        return f"<b>DNS {html.escape(name)}:</b> <i>{html.escape(str(e))}</i>"
    except Exception as e:
        logger.exception("DNS lookup error for %s", name)
        return f"<i>Error:</i> <code>{html.escape(str(e))}</code>"
    elapsed_ms = (time.monotonic() - start) * 1000.0

    ipv4: set[str] = set()
    ipv6: set[str] = set()
    for family, _socktype, _proto, _canonname, sockaddr in infos:
        ip = sockaddr[0] if sockaddr else None
        if not ip:
            continue
        if family == socket.AF_INET:
            ipv4.add(ip)
        elif family == socket.AF_INET6:
            ipv6.add(ip)

    lines: list[str] = [f"Lookup time: {elapsed_ms:.0f}ms"]
    if ipv4:
        lines.append("A:")
        lines.extend(f"  {ip}" for ip in sorted(ipv4))
    if ipv6:
        lines.append("AAAA:")
        lines.extend(f"  {ip}" for ip in sorted(ipv6))
    if not ipv4 and not ipv6:
        lines.append("(no addresses returned)")

    return f"<b>DNS {html.escape(name)}:</b>\n<pre>{html.escape(chr(10).join(lines))}</pre>"


def traceroute_host(host: str, max_hops: int = 20) -> str:
    """Trace route to a host (prefers tracepath; falls back to traceroute)."""
    tracepath_bin = shutil.which("tracepath")
    traceroute_bin = shutil.which("traceroute")
    cmd: list[str] | None = None
    if tracepath_bin:
        cmd = [tracepath_bin, "-n", "-m", str(max_hops), host]
    elif traceroute_bin:
        cmd = [traceroute_bin, "-n", "-m", str(max_hops), "-q", "1", "-w", "2", host]
    if cmd is None:
        return "<i>tracepath/traceroute not available in container</i>"

    try:
        rc, out, err = run_cmd(cmd, timeout=25)
        out = (out or err or "").strip()
        if not out:
            return "<i>No output from traceroute</i>"
        lines = out.splitlines()[:80]
        sample = "\n".join(lines)
        title = html.escape(host)
        if rc != 0:
            title = f"{title} (exit {rc})"
        return f"<b>Traceroute {title}:</b>\n<pre>{html.escape(sample)}</pre>"
    except Exception as e:
        logger.exception("Error running traceroute for %s", host)
        return f"<i>Error:</i> <code>{html.escape(str(e))}</code>"


def _fmt_rate_bps(bytes_per_s: float) -> str:
    units = ["B/s", "KB/s", "MB/s", "GB/s"]
    value = float(max(0.0, bytes_per_s))
    unit_idx = 0
    while value >= 1000.0 and unit_idx < len(units) - 1:
        value /= 1000.0
        unit_idx += 1
    if unit_idx == 0:
        return f"{value:.0f} {units[unit_idx]}"
    return f"{value:.2f} {units[unit_idx]}"


def speedtest_download(mb: int = 10) -> str:
    """Rough download speed test using curl against Cloudflare."""
    curl_bin = shutil.which("curl")
    if not curl_bin:
        return "<i>curl command not available in container</i>"
    bytes_to_download = max(1, int(mb)) * 1_000_000
    url = f"https://speed.cloudflare.com/__down?bytes={bytes_to_download}"
    try:
        rc, out, err = run_cmd(
            [
                curl_bin,
                "-fsSL",
                "--max-time",
                "25",
                "-o",
                "/dev/null",
                "-w",
                "%{time_total} %{size_download}\n",
                url,
            ],
            timeout=30,
        )
        out = (out or "").strip()
        if rc != 0 or not out:
            err_text = (err or out).strip() or f"exit {rc}"
            return f"<i>Speedtest failed:</i> <code>{html.escape(err_text)}</code>"
        parts = out.split()
        if len(parts) < 2:
            return f"<i>Speedtest parse error:</i> <code>{html.escape(out)}</code>"
        seconds = float(parts[0])
        downloaded_bytes = float(parts[1])
        if seconds <= 0:
            return "<i>Speedtest failed: invalid duration</i>"
        bps = downloaded_bytes / seconds
        mbps = (downloaded_bytes * 8.0) / seconds / 1_000_000.0
        msg = (
            "<b>Speedtest (download):</b>\n"
            f"Size: <code>{downloaded_bytes/1_000_000.0:.1f}MB</code>\n"
            f"Time: <code>{seconds:.2f}s</code>\n"
            f"Rate: <code>{_fmt_rate_bps(bps)}</code> (<code>{mbps:.1f} Mbps</code>)"
        )
        return msg
    except Exception as e:
        logger.exception("Speedtest error")
        return f"<i>Error:</i> <code>{html.escape(str(e))}</code>"


def get_top_processes() -> str:
    """Get top processes using ps command."""
    try:
        rc, out, err = run_cmd(["/bin/ps", "aux", "--sort=-%cpu"], timeout=5)
        if rc != 0:
            return "<i>Failed to get process list</i>"
        lines = out.splitlines()[:11]
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

    build_version = os.environ.get("TELE_HOME_SUPERVISOR_BUILD_VERSION")
    if build_version:
        lines.append(f"<b>Build:</b> <code>{html.escape(build_version)}</code>")

    # Try to get latest git commit date (suppress stderr to avoid logs when .git missing)
    try:
        rc, out, err = run_cmd(
            ["git", "log", "-1", "--format=%cd", "--date=format:%Y-%m-%d %H:%M:%S"],
            timeout=3,
        )
        out = out.strip()
        if rc == 0 and out:
            lines.append(f"<b>Last Commit:</b> {html.escape(out)}")
    except Exception:
        pass
    # Try to get git commit hash (suppress stderr)
    try:
        rc, out, err = run_cmd(["git", "rev-parse", "--short", "HEAD"], timeout=3)
        out = out.strip()
        if rc == 0 and out:
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
        from .runtime import STARTUP_TIME

        startup = STARTUP_TIME.strftime("%Y-%m-%d %H:%M:%S")
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
