"""View layer for formatting Telegram messages (HTML)."""

from __future__ import annotations

import html
import io
import math
import re
import time

from PIL import Image, ImageDraw, ImageFont


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


def render_metrics_chart(metrics: dict) -> io.BytesIO | None:
    """Render command metrics as a bar chart image.

    Args:
        metrics: Dictionary of command name -> CommandMetrics

    Returns:
        BytesIO containing PNG image, or None if no data.
    """
    if not metrics:
        return None

    # Prepare data - sort by run count descending
    data = []
    for name, entry in metrics.items():
        avg_ms = (entry.total_latency_s / entry.count * 1000) if entry.count else 0.0
        data.append(
            {
                "name": name,
                "runs": entry.count,
                "success": entry.success,
                "error": entry.error,
                "avg_ms": avg_ms,
            }
        )

    # Sort by runs descending, limit to top 15
    data = sorted(data, key=lambda x: x["runs"], reverse=True)[:15]

    if not data:
        return None

    # Chart dimensions
    padding = 20
    bar_height = 28
    label_width = 140
    value_label_width = 80
    max_bar_width = 300
    chart_height = padding * 2 + len(data) * (bar_height + 8)
    chart_width = padding * 2 + label_width + max_bar_width + value_label_width + 40

    # Colors
    bg_color = (30, 30, 46)  # Dark background
    text_color = (205, 214, 244)  # Light text
    success_color = (166, 227, 161)  # Green
    error_color = (243, 139, 168)  # Red

    # Create image
    img = Image.new("RGB", (chart_width, chart_height), bg_color)
    draw = ImageDraw.Draw(img)

    # Try to use a nice font, fallback to default
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
        font_bold = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12
        )
        title_font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14
        )
    except (OSError, IOError):
        font = ImageFont.load_default()
        font_bold = font
        title_font = font

    # Title
    draw.text(
        (padding, padding - 5), "Command Metrics", fill=text_color, font=title_font
    )

    # Find max runs for scaling
    max_runs = max(d["runs"] for d in data) if data else 1

    # Draw bars
    y = padding + 25
    for item in data:
        name = item["name"]
        runs = item["runs"]
        success = item["success"]
        error = item["error"]
        avg_ms = item["avg_ms"]

        # Truncate long names
        if len(name) > 16:
            name = name[:14] + ".."

        # Label
        draw.text((padding, y + 6), name, fill=text_color, font=font_bold)

        # Bar position
        bar_x = padding + label_width
        bar_width = int((runs / max_runs) * max_bar_width) if max_runs > 0 else 0
        bar_width = max(bar_width, 4)  # Minimum visible width

        # Calculate success/error portions
        if runs > 0:
            success_width = int((success / runs) * bar_width)
            error_width = int((error / runs) * bar_width)
        else:
            success_width = bar_width
            error_width = 0

        # Draw success portion
        if success_width > 0:
            draw.rectangle(
                [bar_x, y + 4, bar_x + success_width, y + bar_height - 4],
                fill=success_color,
            )

        # Draw error portion (stacked)
        if error_width > 0:
            draw.rectangle(
                [
                    bar_x + success_width,
                    y + 4,
                    bar_x + success_width + error_width,
                    y + bar_height - 4,
                ],
                fill=error_color,
            )

        # Value label
        value_text = f"{runs} ({avg_ms:.0f}ms)"
        value_x = bar_x + bar_width + 8
        draw.text((value_x, y + 6), value_text, fill=text_color, font=font)

        y += bar_height + 8

    # Legend
    legend_y = chart_height - padding - 5
    draw.rectangle(
        [padding, legend_y - 8, padding + 12, legend_y + 4], fill=success_color
    )
    draw.text((padding + 18, legend_y - 6), "success", fill=text_color, font=font)
    draw.rectangle(
        [padding + 80, legend_y - 8, padding + 92, legend_y + 4], fill=error_color
    )
    draw.text((padding + 98, legend_y - 6), "error", fill=text_color, font=font)

    # Save to BytesIO
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    bio.name = "metrics.png"
    return bio


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

    return "\n\n".join(_render_torrent_lines(torrents))


def render_torrent_list_page(torrents: list[dict], page: int, total_pages: int) -> str:
    if not torrents:
        return "No active torrents found."

    page_label = f"Torrents (page {page + 1}/{max(total_pages, 1)}):"
    lines = [bold(page_label)]
    lines.extend(_render_torrent_lines(torrents))
    return "\n\n".join(lines)


def _render_torrent_lines(torrents: list[dict]) -> list[str]:
    parts: list[str] = []
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
    return parts


def render_protondb_list(title: str, games: list[dict]) -> str:
    if not games:
        return "<i>No games found.</i>"
    lines = [bold(title)]
    for idx, game in enumerate(games, start=1):
        name = html.escape(str(game.get("name") or "Unknown"))
        lines.append(f"{idx}. {name}")
    return "\n".join(lines)


# =============================================================================
# PIL-based chart rendering functions
# =============================================================================


def _get_fonts() -> tuple:
    """Load fonts with fallback to default."""
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
        font_bold = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12
        )
        title_font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14
        )
        small_font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10
        )
    except (OSError, IOError):
        font = ImageFont.load_default()
        font_bold = font
        title_font = font
        small_font = font
    return font, font_bold, title_font, small_font


# Standard color palette
_COLORS = {
    "bg": (30, 30, 46),
    "text": (205, 214, 244),
    "green": (166, 227, 161),
    "red": (243, 139, 168),
    "yellow": (249, 226, 175),
    "blue": (137, 180, 250),
    "purple": (203, 166, 247),
    "teal": (148, 226, 213),
    "orange": (250, 179, 135),
    "grid": (69, 71, 90),
    "dark": (49, 50, 68),
}


def _draw_gauge(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    size: int,
    value: float,
    label: str,
    font,
    small_font,
    color: tuple[int, int, int] = _COLORS["green"],
) -> None:
    """Draw a circular gauge at position (x, y)."""
    # Background circle
    draw.ellipse([x, y, x + size, y + size], outline=_COLORS["grid"], width=8)

    # Value arc (270 degrees max, starting from bottom-left)
    if value > 0:
        # Calculate arc extent (max 270 degrees)
        extent = min(value / 100, 1.0) * 270
        # Choose color based on value
        if value >= 90:
            arc_color = _COLORS["red"]
        elif value >= 70:
            arc_color = _COLORS["yellow"]
        else:
            arc_color = color
        draw.arc(
            [x, y, x + size, y + size],
            start=135,
            end=135 + extent,
            fill=arc_color,
            width=8,
        )

    # Center text (value)
    value_text = f"{value:.0f}%"
    bbox = draw.textbbox((0, 0), value_text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    draw.text(
        (x + size // 2 - text_w // 2, y + size // 2 - text_h // 2 - 5),
        value_text,
        fill=_COLORS["text"],
        font=font,
    )

    # Label below gauge
    bbox = draw.textbbox((0, 0), label, font=small_font)
    label_w = bbox[2] - bbox[0]
    draw.text(
        (x + size // 2 - label_w // 2, y + size + 5),
        label,
        fill=_COLORS["text"],
        font=small_font,
    )


def render_health_chart(data: dict) -> io.BytesIO | None:
    """Render host health dashboard as an image with gauges.

    Args:
        data: Health data dict with keys like cpu_pct, mem_pct, disk info, etc.

    Returns:
        BytesIO containing PNG image.
    """
    font, font_bold, title_font, small_font = _get_fonts()

    # Parse values
    cpu_pct = float(str(data.get("cpu_pct", "0")).replace("%", ""))
    mem_pct = float(str(data.get("mem_pct", "0")).replace("%", ""))

    # Parse disk percentages
    disk_pcts = []
    for d in data.get("disks", []):
        match = re.search(r"(\d+(?:\.\d+)?)%", str(d))
        if match:
            disk_pcts.append((str(d).split(":")[0].strip(), float(match.group(1))))

    # Chart dimensions
    padding = 20
    gauge_size = 80
    gauge_spacing = 30
    num_gauges = 2 + len(disk_pcts)
    chart_width = padding * 2 + num_gauges * (gauge_size + gauge_spacing)
    chart_height = padding * 2 + gauge_size + 60  # Extra space for labels and title

    # Create image
    img = Image.new("RGB", (chart_width, chart_height), _COLORS["bg"])
    draw = ImageDraw.Draw(img)

    # Title
    title = f"Health: {html.unescape(data.get('host', 'Unknown'))}"
    draw.text((padding, padding - 5), title, fill=_COLORS["text"], font=title_font)

    # Draw gauges
    y = padding + 25
    x = padding

    # CPU gauge
    _draw_gauge(
        draw, x, y, gauge_size, cpu_pct, "CPU", font_bold, small_font, _COLORS["blue"]
    )
    x += gauge_size + gauge_spacing

    # Memory gauge
    _draw_gauge(
        draw,
        x,
        y,
        gauge_size,
        mem_pct,
        "Memory",
        font_bold,
        small_font,
        _COLORS["purple"],
    )
    x += gauge_size + gauge_spacing

    # Disk gauges
    for disk_name, disk_val in disk_pcts[:4]:  # Limit to 4 disks
        short_name = disk_name[:8] if len(disk_name) > 8 else disk_name
        _draw_gauge(
            draw,
            x,
            y,
            gauge_size,
            disk_val,
            short_name,
            font_bold,
            small_font,
            _COLORS["teal"],
        )
        x += gauge_size + gauge_spacing

    # Info text at bottom
    info_y = chart_height - 18
    info_text = f"Uptime: {data.get('uptime', 'N/A')} | Load: {data.get('load', 'N/A')} | Temp: {data.get('temp', 'N/A')}"
    draw.text((padding, info_y), info_text, fill=_COLORS["grid"], font=small_font)

    # Save to BytesIO
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    bio.name = "health.png"
    return bio


def render_docker_stats_chart(stats: list[dict]) -> io.BytesIO | None:
    """Render Docker container stats as horizontal bar chart.

    Args:
        stats: List of container stats dicts with name, cpu, mem_pct, etc.

    Returns:
        BytesIO containing PNG image, or None if no data.
    """
    if not stats:
        return None

    font, font_bold, title_font, small_font = _get_fonts()

    # Limit to 12 containers
    stats = stats[:12]

    # Parse percentages
    def parse_pct(val: str) -> float:
        try:
            return float(val.replace("%", ""))
        except (ValueError, AttributeError):
            return 0.0

    # Chart dimensions
    padding = 20
    bar_height = 24
    label_width = 120
    bar_max_width = 200
    legend_height = 30
    chart_height = padding * 2 + len(stats) * (bar_height + 6) + 30 + legend_height
    chart_width = padding * 2 + label_width + bar_max_width + 100

    # Create image
    img = Image.new("RGB", (chart_width, chart_height), _COLORS["bg"])
    draw = ImageDraw.Draw(img)

    # Title
    draw.text(
        (padding, padding - 5),
        "Docker Container Stats",
        fill=_COLORS["text"],
        font=title_font,
    )

    # Draw bars
    y = padding + 25
    for s in stats:
        name = s.get("name", "?")[:14]
        cpu_pct = parse_pct(s.get("cpu", "0%"))
        mem_pct = parse_pct(s.get("mem_pct", "0%"))

        # Label
        draw.text((padding, y + 4), name, fill=_COLORS["text"], font=font_bold)

        bar_x = padding + label_width

        # CPU bar (blue)
        cpu_width = int((min(cpu_pct, 100) / 100) * bar_max_width / 2)
        if cpu_width > 0:
            draw.rectangle(
                [bar_x, y + 2, bar_x + max(cpu_width, 2), y + bar_height // 2 - 1],
                fill=_COLORS["blue"],
            )

        # Memory bar (purple)
        mem_width = int((min(mem_pct, 100) / 100) * bar_max_width / 2)
        if mem_width > 0:
            draw.rectangle(
                [
                    bar_x,
                    y + bar_height // 2 + 1,
                    bar_x + max(mem_width, 2),
                    y + bar_height - 2,
                ],
                fill=_COLORS["purple"],
            )

        # Values
        value_text = f"CPU {cpu_pct:.1f}% | Mem {mem_pct:.1f}%"
        draw.text(
            (bar_x + bar_max_width // 2 + 10, y + 4),
            value_text,
            fill=_COLORS["text"],
            font=small_font,
        )

        y += bar_height + 6

    # Legend
    legend_y = chart_height - legend_height
    draw.rectangle(
        [padding, legend_y, padding + 12, legend_y + 12], fill=_COLORS["blue"]
    )
    draw.text(
        (padding + 18, legend_y - 2), "CPU", fill=_COLORS["text"], font=small_font
    )
    draw.rectangle(
        [padding + 60, legend_y, padding + 72, legend_y + 12], fill=_COLORS["purple"]
    )
    draw.text(
        (padding + 78, legend_y - 2), "Memory", fill=_COLORS["text"], font=small_font
    )

    # Save
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    bio.name = "docker_stats.png"
    return bio


def render_torrent_chart(torrents: list[dict]) -> io.BytesIO | None:
    """Render torrent progress bars as an image.

    Args:
        torrents: List of torrent dicts with name, progress, state, dlspeed.

    Returns:
        BytesIO containing PNG image, or None if no data.
    """
    if not torrents:
        return None

    font, font_bold, title_font, small_font = _get_fonts()

    # Limit to 10 torrents
    torrents = torrents[:10]

    # Chart dimensions
    padding = 20
    row_height = 40
    chart_width = 500
    chart_height = padding * 2 + len(torrents) * row_height + 30

    # Create image
    img = Image.new("RGB", (chart_width, chart_height), _COLORS["bg"])
    draw = ImageDraw.Draw(img)

    # Title
    draw.text(
        (padding, padding - 5), "Torrent Status", fill=_COLORS["text"], font=title_font
    )

    # Draw torrents
    y = padding + 25
    bar_width = chart_width - padding * 2 - 80

    for t in torrents:
        name = t.get("name", "Unknown")[:40]
        progress = t.get("progress", 0)
        if isinstance(progress, str):
            progress = float(progress.replace("%", ""))
        progress = min(progress * 100 if progress <= 1 else progress, 100)

        state = t.get("state", "unknown")
        dlspeed = t.get("dlspeed", 0)
        if isinstance(dlspeed, (int, float)):
            speed_text = f"{dlspeed / 1024:.1f} KiB/s" if dlspeed > 0 else ""
        else:
            speed_text = str(dlspeed)

        # State color
        if "download" in state.lower():
            state_color = _COLORS["blue"]
        elif "seed" in state.lower():
            state_color = _COLORS["green"]
        elif "paus" in state.lower() or "stop" in state.lower():
            state_color = _COLORS["yellow"]
        else:
            state_color = _COLORS["grid"]

        # Name
        draw.text((padding, y), name, fill=_COLORS["text"], font=font_bold)

        # Progress bar background
        bar_y = y + 18
        draw.rectangle(
            [padding, bar_y, padding + bar_width, bar_y + 12],
            fill=_COLORS["dark"],
        )

        # Progress bar fill
        fill_width = int((progress / 100) * bar_width)
        if fill_width > 0:
            draw.rectangle(
                [padding, bar_y, padding + fill_width, bar_y + 12],
                fill=state_color,
            )

        # Progress text
        progress_text = f"{progress:.1f}%"
        draw.text(
            (padding + bar_width + 10, bar_y - 2),
            progress_text,
            fill=_COLORS["text"],
            font=small_font,
        )

        # Speed (if downloading)
        if speed_text:
            bbox = draw.textbbox((0, 0), speed_text, font=small_font)
            speed_w = bbox[2] - bbox[0]
            draw.text(
                (chart_width - padding - speed_w, y),
                speed_text,
                fill=_COLORS["teal"],
                font=small_font,
            )

        y += row_height

    # Save
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    bio.name = "torrents.png"
    return bio


def render_speedtest_chart(
    download_mbps: float, upload_mbps: float = 0, ping_ms: float = 0
) -> io.BytesIO | None:
    """Render speedtest results as gauge chart.

    Args:
        download_mbps: Download speed in Mbps
        upload_mbps: Upload speed in Mbps (optional)
        ping_ms: Ping in milliseconds (optional)

    Returns:
        BytesIO containing PNG image.
    """
    font, font_bold, title_font, small_font = _get_fonts()

    # Chart dimensions
    padding = 20
    gauge_size = 100
    chart_width = padding * 2 + gauge_size * 2 + 60
    chart_height = padding * 2 + gauge_size + 80

    # Create image
    img = Image.new("RGB", (chart_width, chart_height), _COLORS["bg"])
    draw = ImageDraw.Draw(img)

    # Title
    draw.text(
        (padding, padding - 5),
        "Speedtest Results",
        fill=_COLORS["text"],
        font=title_font,
    )

    y = padding + 30

    # Download gauge (assume 1000 Mbps max)
    dl_pct = min(download_mbps / 1000 * 100, 100)
    x = padding

    # Background arc
    draw.arc(
        [x, y, x + gauge_size, y + gauge_size],
        start=135,
        end=405,
        fill=_COLORS["dark"],
        width=10,
    )

    # Value arc
    if dl_pct > 0:
        extent = (dl_pct / 100) * 270
        color = (
            _COLORS["green"]
            if download_mbps >= 100
            else _COLORS["yellow"]
            if download_mbps >= 50
            else _COLORS["red"]
        )
        draw.arc(
            [x, y, x + gauge_size, y + gauge_size],
            start=135,
            end=135 + extent,
            fill=color,
            width=10,
        )

    # Download value
    dl_text = f"{download_mbps:.1f}"
    bbox = draw.textbbox((0, 0), dl_text, font=font_bold)
    text_w = bbox[2] - bbox[0]
    draw.text(
        (x + gauge_size // 2 - text_w // 2, y + gauge_size // 2 - 10),
        dl_text,
        fill=_COLORS["text"],
        font=font_bold,
    )
    draw.text(
        (x + gauge_size // 2 - 15, y + gauge_size // 2 + 8),
        "Mbps",
        fill=_COLORS["grid"],
        font=small_font,
    )
    draw.text(
        (x + gauge_size // 2 - 20, y + gauge_size + 10),
        "Download",
        fill=_COLORS["text"],
        font=small_font,
    )

    # Upload gauge (if provided)
    if upload_mbps > 0:
        x = padding + gauge_size + 40
        ul_pct = min(upload_mbps / 500 * 100, 100)  # Assume 500 Mbps max for upload

        draw.arc(
            [x, y, x + gauge_size, y + gauge_size],
            start=135,
            end=405,
            fill=_COLORS["dark"],
            width=10,
        )
        if ul_pct > 0:
            extent = (ul_pct / 100) * 270
            color = _COLORS["teal"]
            draw.arc(
                [x, y, x + gauge_size, y + gauge_size],
                start=135,
                end=135 + extent,
                fill=color,
                width=10,
            )

        ul_text = f"{upload_mbps:.1f}"
        bbox = draw.textbbox((0, 0), ul_text, font=font_bold)
        text_w = bbox[2] - bbox[0]
        draw.text(
            (x + gauge_size // 2 - text_w // 2, y + gauge_size // 2 - 10),
            ul_text,
            fill=_COLORS["text"],
            font=font_bold,
        )
        draw.text(
            (x + gauge_size // 2 - 15, y + gauge_size // 2 + 8),
            "Mbps",
            fill=_COLORS["grid"],
            font=small_font,
        )
        draw.text(
            (x + gauge_size // 2 - 15, y + gauge_size + 10),
            "Upload",
            fill=_COLORS["text"],
            font=small_font,
        )

    # Ping info
    if ping_ms > 0:
        ping_text = f"Ping: {ping_ms:.0f} ms"
        draw.text(
            (padding, chart_height - 25), ping_text, fill=_COLORS["text"], font=font
        )

    # Save
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    bio.name = "speedtest.png"
    return bio


def render_traceroute_chart(hops: list[dict]) -> io.BytesIO | None:
    """Render traceroute as network diagram.

    Args:
        hops: List of hop dicts with hop number, ip, hostname, rtt values.

    Returns:
        BytesIO containing PNG image, or None if no data.
    """
    if not hops:
        return None

    font, font_bold, title_font, small_font = _get_fonts()

    # Limit hops
    hops = hops[:20]

    # Chart dimensions
    padding = 20
    hop_height = 28
    chart_width = 480
    chart_height = padding * 2 + len(hops) * hop_height + 30

    # Create image
    img = Image.new("RGB", (chart_width, chart_height), _COLORS["bg"])
    draw = ImageDraw.Draw(img)

    # Title
    draw.text(
        (padding, padding - 5), "Traceroute", fill=_COLORS["text"], font=title_font
    )

    # Draw hops
    y = padding + 30
    node_x = padding + 20
    node_radius = 6

    for i, hop in enumerate(hops):
        hop_num = hop.get("hop", i + 1)
        ip = hop.get("ip", "*")
        hostname = hop.get("hostname", "")
        rtt = hop.get("rtt", 0)

        # Draw connecting line
        if i > 0:
            draw.line(
                [node_x, y - hop_height + node_radius, node_x, y - node_radius],
                fill=_COLORS["grid"],
                width=2,
            )

        # Draw node
        node_color = _COLORS["green"] if ip != "*" else _COLORS["red"]
        draw.ellipse(
            [
                node_x - node_radius,
                y - node_radius,
                node_x + node_radius,
                y + node_radius,
            ],
            fill=node_color,
        )

        # Hop number
        draw.text((padding, y - 6), str(hop_num), fill=_COLORS["text"], font=small_font)

        # IP/hostname
        label = hostname if hostname and hostname != ip else ip
        if len(label) > 35:
            label = label[:32] + "..."
        draw.text((node_x + 15, y - 6), label, fill=_COLORS["text"], font=font)

        # RTT
        if rtt and rtt != "*":
            rtt_text = f"{rtt:.1f}ms" if isinstance(rtt, (int, float)) else str(rtt)
            bbox = draw.textbbox((0, 0), rtt_text, font=small_font)
            rtt_w = bbox[2] - bbox[0]
            # Color based on latency
            if isinstance(rtt, (int, float)):
                if rtt < 50:
                    rtt_color = _COLORS["green"]
                elif rtt < 150:
                    rtt_color = _COLORS["yellow"]
                else:
                    rtt_color = _COLORS["red"]
            else:
                rtt_color = _COLORS["text"]
            draw.text(
                (chart_width - padding - rtt_w, y - 6),
                rtt_text,
                fill=rtt_color,
                font=small_font,
            )

        y += hop_height

    # Save
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    bio.name = "traceroute.png"
    return bio


def render_alerts_chart(alerts: list[dict], rules: list = None) -> io.BytesIO | None:
    """Render alert history as timeline chart.

    Args:
        alerts: List of alert event dicts with timestamp, metric, value, status.
        rules: Optional list of alert rules.

    Returns:
        BytesIO containing PNG image, or None if no data.
    """
    if not alerts and not rules:
        return None

    font, font_bold, title_font, small_font = _get_fonts()

    # Limit events
    alerts = (alerts or [])[:15]
    rules = (rules or [])[:10]

    # Chart dimensions
    padding = 20
    row_height = 24
    rules_height = len(rules) * row_height if rules else 0
    alerts_height = len(alerts) * row_height if alerts else 0
    chart_width = 450
    chart_height = padding * 2 + rules_height + alerts_height + 60

    if chart_height < 100:
        chart_height = 100

    # Create image
    img = Image.new("RGB", (chart_width, chart_height), _COLORS["bg"])
    draw = ImageDraw.Draw(img)

    # Title
    draw.text(
        (padding, padding - 5), "Alert Dashboard", fill=_COLORS["text"], font=title_font
    )

    y = padding + 30

    # Rules section
    if rules:
        draw.text((padding, y), "Active Rules:", fill=_COLORS["blue"], font=font_bold)
        y += 20
        for rule in rules:
            metric = (
                getattr(rule, "metric", str(rule.get("metric", "?")))
                if hasattr(rule, "metric")
                else rule.get("metric", "?")
            )
            operator = (
                getattr(rule, "operator", rule.get("operator", ""))
                if hasattr(rule, "operator")
                else rule.get("operator", "")
            )
            threshold = (
                getattr(rule, "threshold", rule.get("threshold", ""))
                if hasattr(rule, "threshold")
                else rule.get("threshold", "")
            )
            rule_text = f"• {metric} {operator} {threshold}"
            draw.text((padding + 10, y), rule_text, fill=_COLORS["text"], font=font)
            y += row_height
        y += 10

    # Alerts section
    if alerts:
        draw.text(
            (padding, y), "Recent Alerts:", fill=_COLORS["orange"], font=font_bold
        )
        y += 20
        for alert in alerts:
            ts = alert.get("timestamp", 0)
            if ts:
                time_str = time.strftime("%H:%M:%S", time.localtime(ts))
            else:
                time_str = "--:--:--"
            metric = alert.get("metric", "?")
            value = alert.get("value", "?")
            status = alert.get("status", "triggered")

            # Status indicator
            if "ok" in status.lower() or "resolved" in status.lower():
                color = _COLORS["green"]
            else:
                color = _COLORS["red"]

            draw.ellipse([padding + 5, y + 3, padding + 13, y + 11], fill=color)
            alert_text = f"{time_str} {metric}: {value}"
            draw.text(
                (padding + 20, y), alert_text, fill=_COLORS["text"], font=small_font
            )
            y += row_height
    elif not rules:
        draw.text((padding, y), "No alerts configured", fill=_COLORS["grid"], font=font)

    # Save
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    bio.name = "alerts.png"
    return bio


def render_audit_chart(entries: list) -> io.BytesIO | None:
    """Render audit log as timeline chart.

    Args:
        entries: List of AuditEntry objects or dicts.

    Returns:
        BytesIO containing PNG image, or None if no data.
    """
    if not entries:
        return None

    font, font_bold, title_font, small_font = _get_fonts()

    # Limit entries
    entries = entries[:20]

    # Chart dimensions
    padding = 20
    row_height = 26
    chart_width = 500
    chart_height = padding * 2 + len(entries) * row_height + 30

    # Create image
    img = Image.new("RGB", (chart_width, chart_height), _COLORS["bg"])
    draw = ImageDraw.Draw(img)

    # Title
    draw.text(
        (padding, padding - 5), "Audit Log", fill=_COLORS["text"], font=title_font
    )

    # Draw timeline
    y = padding + 30
    timeline_x = padding + 60

    for i, entry in enumerate(entries):
        # Get entry data (support both objects and dicts)
        if hasattr(entry, "created_at"):
            ts = entry.created_at
            user = entry.user_name or "?"
            action = entry.action or "?"
            target = entry.target or "-"
            status = entry.status or "?"
            duration = entry.duration_ms
        else:
            ts = entry.get("created_at", 0)
            user = entry.get("user_name", "?")
            action = entry.get("action", "?")
            target = entry.get("target", "-")
            status = entry.get("status", "?")
            duration = entry.get("duration_ms", 0)

        # Time
        time_str = time.strftime("%H:%M", time.localtime(ts)) if ts else "--:--"
        draw.text((padding, y), time_str, fill=_COLORS["grid"], font=small_font)

        # Timeline dot and line
        if i > 0:
            draw.line(
                [timeline_x, y - row_height + 8, timeline_x, y - 4],
                fill=_COLORS["grid"],
                width=1,
            )

        # Status color
        if status == "ok":
            dot_color = _COLORS["green"]
        elif status in ("error", "fail"):
            dot_color = _COLORS["red"]
        else:
            dot_color = _COLORS["yellow"]

        draw.ellipse([timeline_x - 4, y, timeline_x + 4, y + 8], fill=dot_color)

        # Entry text
        entry_text = f"{user}: {action}"
        if target and target != "-":
            entry_text += f" → {target[:15]}"
        if len(entry_text) > 40:
            entry_text = entry_text[:37] + "..."
        draw.text((timeline_x + 15, y - 2), entry_text, fill=_COLORS["text"], font=font)

        # Duration
        if duration:
            dur_text = f"{duration}ms"
            bbox = draw.textbbox((0, 0), dur_text, font=small_font)
            dur_w = bbox[2] - bbox[0]
            draw.text(
                (chart_width - padding - dur_w, y),
                dur_text,
                fill=_COLORS["grid"],
                font=small_font,
            )

        y += row_height

    # Save
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    bio.name = "audit.png"
    return bio
