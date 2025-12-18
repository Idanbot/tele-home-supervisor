"""View layer for formatting Telegram messages (HTML)."""

from __future__ import annotations

import html


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
