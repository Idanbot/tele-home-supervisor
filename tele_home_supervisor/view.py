"""View layer for formatting Telegram messages (HTML)."""

from __future__ import annotations

import html
import math
import time


def bold(text: str) -> str:
    return f"<b>{html.escape(str(text))}</b>"


def code(text: str) -> str:
    return f"<code>{html.escape(str(text))}</code>"


def pre(text: str) -> str:
    return f"<pre>{html.escape(str(text))}</pre>"


def chunk(msg: str, size: int = 4000) -> list[str]:
    """Split message into chunks ensuring no chunk exceeds size limit."""
    if len(msg) <= size:
        return [msg]

    lines = msg.splitlines()
    chunks: list[str] = []
    current = ""
    for line in lines:
        if len(line) > size:
            if current:
                chunks.append(current)
                current = ""
            start = 0
            while start < len(line):
                chunks.append(line[start : start + size])
                start += size
            continue
        added_length = len(line) + (1 if current else 0)
        if len(current) + added_length > size and current:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks


def render_host_health(data: dict, show_wan: bool = False) -> str:
    lines = [
        f"{bold('Host:')} {code(data['host'])} <i>{html.escape(data['system'])} {html.escape(data['release'])}</i>",
        f"{bold('Time:')} {html.escape(data['time'])}",
        f"{bold('LAN IP:')} {code(data['lan_ip'])}",
    ]
    if show_wan:
        lines.append(f"{bold('WAN IP:')} {code(data['wan_ip'])}")

    disks_html = (
        " | ".join(html.escape(d) for d in data["disks"]) if data["disks"] else "n/a"
    )

    lines.extend(
        [
            f"{bold('Uptime:')} {data['uptime']} | {bold('Load:')} {data['load']}",
            f"{bold('CPU:')} {data['cpu_pct']}% | {bold('Mem:')} {data['mem_used']}/{data['mem_total']} ({data['mem_pct']}%) | {bold('Temp:')} {html.escape(data['temp'])}",
            f"{bold('Disks:')} {disks_html}",
        ]
    )
    return "\n".join(lines)


def _format_timestamp(ts: float | None) -> str:
    if not ts:
        return "never"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


def _p95(samples: list[float]) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    idx = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[idx]


def render_command_metrics(metrics: dict) -> str:
    if not metrics:
        return "<i>No command metrics recorded yet.</i>"

    lines = [bold("Command Metrics:")]
    for name in sorted(metrics.keys()):
        entry = metrics[name]
        avg = (entry.total_latency_s / entry.count) if entry.count else 0.0
        p95 = _p95(entry.latencies_s)
        last_run = _format_timestamp(entry.last_run_ts)
        line = (
            f"{code(name)} runs {entry.count} ok {entry.success} err {entry.error} "
            f"rl {entry.rate_limited} avg {avg * 1000:.1f}ms "
            f"p95 {p95 * 1000:.1f}ms max {entry.max_latency_s * 1000:.1f}ms "
            f"last {html.escape(last_run)}"
        )
        lines.append(line)
    return "\n".join(lines)


def render_container_list(containers: list[dict]) -> str:
    if not containers:
        return "<i>No containers found.</i>"

    lines = [bold("Containers:")]
    for c in containers:
        if "error" in c:
            lines.append(f"{code(c.get('name', 'unknown'))} • error")
            continue

        name = code(c["name"])
        image = code(c["image"])
        status = html.escape(c["status"])
        ports = html.escape(c["ports"])
        lines.append(f"{name} • {status} • {image} • {ports}")
    return "\n".join(lines)


def render_container_list_page(
    containers: list[dict], page: int, total_pages: int
) -> str:
    if not containers:
        return "<i>No containers found.</i>"

    page_label = f"Containers (page {page + 1}/{max(total_pages, 1)}):"
    lines = [bold(page_label)]
    for c in containers:
        if "error" in c:
            lines.append(f"{code(c.get('name', 'unknown'))} • error")
            continue

        name = code(c["name"])
        image = code(c["image"])
        status = html.escape(c["status"])
        ports = html.escape(c["ports"])
        lines.append(f"{name} • {status} • {image} • {ports}")
    return "\n".join(lines)


def render_container_stats(stats: list[dict]) -> str:
    if not stats:
        return "<i>No running containers.</i>"

    lines = [bold("Container Detailed Stats:")]
    for s in stats:
        lines.append(
            f"{code(s['name'])} CPU {s['cpu']} MEM {s['mem_pct']} ({s['mem_usage']})\n"
            f"Net I/O: {s['netio']} Block I/O: {s['blockio']} PIDs: {s['pids']}"
        )
    return "\n\n".join(lines)


def render_tmdb_list(title: str, items: list[dict[str, object]]) -> str:
    if not items:
        return "<i>No results found.</i>"
    lines = [bold(title)]
    for idx, item in enumerate(items, start=1):
        name = html.escape(str(item.get("title") or item.get("name") or "Unknown"))
        year = html.escape(str(item.get("year") or ""))
        rating = item.get("rating")
        rating_text = f"{rating:.1f}" if isinstance(rating, (int, float)) else "-"
        suffix = f" ({year})" if year else ""
        lines.append(f"{idx}. {name}{suffix} - ⭐ {rating_text}")
    return "\n".join(lines)


def render_logs(container: str, logs: str, direction: str, count: str) -> str:
    safe_name = html.escape(container)
    return (
        f"{bold(f'Logs for {safe_name}')} <i>({direction} {count} lines)</i>\n"
        f"{pre(logs)}"
    )


def render_torrent_list(torrents: list[dict]) -> str:
    if not torrents:
        return "No active torrents found."

    parts = []
    for t in torrents:
        name = bold(t["name"])
        state = html.escape(t["state"])

        progress_line = f"  Progress: {t['progress']:.1f}%"
        if t.get("size_summary"):
            progress_line += f" ({t['size_summary']})"

        parts.append(
            f"{name}\n"
            f"  Status: {state}\n"
            f"{progress_line}\n"
            f"  Speed: {t['dlspeed']:.1f} KiB/s"
        )
    return "\n\n".join(parts)
