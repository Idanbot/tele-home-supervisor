"""Command registry (single source of truth for help + wiring)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Group = Literal[
    "System",
    "Docker",
    "Network",
    "Torrents",
    "Notifications",
    "Media",
    "AI",
    "Info",
]
Needs = Literal["none", "container", "torrent"]


@dataclass(frozen=True)
class CommandSpec:
    name: str
    aliases: tuple[str, ...]
    group: Group
    usage: str
    description: str
    handler: str
    needs: Needs = "none"


COMMANDS: tuple[CommandSpec, ...] = (
    # Info
    CommandSpec("start", (), "Info", "/start", "show help", handler="cmd_start"),
    CommandSpec("help", (), "Info", "/help", "this menu", handler="cmd_help"),
    CommandSpec(
        "whoami", (), "Info", "/whoami", "show chat and user info", handler="cmd_whoami"
    ),
    CommandSpec(
        "auth",
        (),
        "Info",
        "/auth <code>",
        "authorize sensitive commands for 24 hours",
        handler="cmd_auth",
    ),
    CommandSpec(
        "version",
        (),
        "Info",
        "/version",
        "bot version and build info",
        handler="cmd_version",
    ),
    CommandSpec(
        "metrics",
        (),
        "Info",
        "/metrics",
        "command metrics summary",
        handler="cmd_metrics",
    ),
    CommandSpec(
        "debug",
        (),
        "Info",
        "/debug [command]",
        "recent errors/debug info",
        handler="cmd_debug",
    ),
    # System
    CommandSpec("ip", (), "System", "/ip", "private LAN IP", handler="cmd_ip"),
    CommandSpec(
        "health",
        (),
        "System",
        "/health",
        "CPU/RAM/disk/load/uptime (and WAN if enabled)",
        handler="cmd_health",
    ),
    CommandSpec(
        "uptime", (), "System", "/uptime", "system uptime", handler="cmd_uptime"
    ),
    CommandSpec(
        "temp",
        (),
        "System",
        "/temp",
        "CPU temperature (reads /host_thermal/temp)",
        handler="cmd_temp",
    ),
    CommandSpec("top", (), "System", "/top", "top CPU processes", handler="cmd_top"),
    # Docker
    CommandSpec(
        "docker",
        (),
        "Docker",
        "/docker",
        "list containers, status, ports",
        handler="cmd_docker",
    ),
    CommandSpec(
        "dockerstats",
        (),
        "Docker",
        "/dockerstats",
        "CPU/MEM per running container",
        handler="cmd_dockerstats",
    ),
    CommandSpec(
        "dstatsrich",
        (),
        "Docker",
        "/dstatsrich",
        "detailed Docker stats (net/block IO)",
        handler="cmd_dstats_rich",
    ),
    CommandSpec(
        "dlogs",
        (),
        "Docker",
        "/dlogs <container> [page] [--since <time>] [--file]",
        "container logs with pagination/filtering",
        handler="cmd_dlogs",
        needs="container",
    ),
    CommandSpec(
        "dhealth",
        (),
        "Docker",
        "/dhealth <container>",
        "container health check",
        handler="cmd_dhealth",
        needs="container",
    ),
    # Network
    CommandSpec(
        "ping",
        (),
        "Network",
        "/ping <ip> [count]",
        "ping an IP or hostname",
        handler="cmd_ping",
    ),
    CommandSpec(
        "ports",
        (),
        "Network",
        "/ports",
        "listening ports (inside container)",
        handler="cmd_ports",
    ),
    CommandSpec("dns", (), "Network", "/dns <name>", "DNS lookup", handler="cmd_dns"),
    CommandSpec(
        "traceroute",
        (),
        "Network",
        "/traceroute <host> [max_hops]",
        "trace network route",
        handler="cmd_traceroute",
    ),
    CommandSpec(
        "speedtest",
        (),
        "Network",
        "/speedtest [MB]",
        "quick download speed test",
        handler="cmd_speedtest",
    ),
    # Torrents
    CommandSpec(
        "tadd",
        (),
        "Torrents",
        "/tadd <torrent> [save_path]",
        "add torrent (magnet/URL)",
        handler="cmd_torrent_add",
    ),
    CommandSpec(
        "tstatus",
        (),
        "Torrents",
        "/tstatus",
        "show torrent status",
        handler="cmd_torrent_status",
    ),
    CommandSpec(
        "tstop",
        (),
        "Torrents",
        "/tstop <torrent>",
        "pause torrent(s) by name",
        handler="cmd_torrent_stop",
        needs="torrent",
    ),
    CommandSpec(
        "tstart",
        (),
        "Torrents",
        "/tstart <torrent>",
        "resume torrent(s) by name",
        handler="cmd_torrent_start",
        needs="torrent",
    ),
    CommandSpec(
        "tdelete",
        (),
        "Torrents",
        "/tdelete <torrent> yes",
        "delete torrent(s) and files",
        handler="cmd_torrent_delete",
        needs="torrent",
    ),
    CommandSpec(
        "subscribe",
        (),
        "Torrents",
        "/subscribe [on|off|status]",
        "torrent completion notifications",
        handler="cmd_subscribe",
    ),
    CommandSpec(
        "pbtop",
        (),
        "Torrents",
        "/pbtop [category]",
        "top Pirate Bay torrents (audio, video, apps, games, porn, other)",
        handler="cmd_pbtop",
    ),
    CommandSpec(
        "pbsearch",
        (),
        "Torrents",
        "/pbsearch <query>",
        "search Pirate Bay torrents",
        handler="cmd_pbsearch",
    ),
    # Notifications
    CommandSpec(
        "mute_gameoffers",
        (),
        "Notifications",
        "/mute_gameoffers",
        "toggle Game Offers daily notifications (8 PM)",
        handler="cmd_mute_gameoffers",
    ),
    CommandSpec(
        "mute_hackernews",
        (),
        "Notifications",
        "/mute_hackernews",
        "toggle Hacker News daily digest (8 AM)",
        handler="cmd_mute_hackernews",
    ),
    CommandSpec(
        "gameoffers",
        (),
        "Notifications",
        "/gameoffers",
        "show combined game offers (Epic/Steam/GOG/Humble)",
        handler="cmd_gameoffers_now",
    ),
    CommandSpec(
        "epicgames",
        (),
        "Notifications",
        "/epicgames",
        "check current Epic Games free games",
        handler="cmd_epicgames_now",
    ),
    CommandSpec(
        "hackernews",
        (),
        "Notifications",
        "/hackernews [n]",
        "show top N Hacker News stories (default: 5)",
        handler="cmd_hackernews_now",
    ),
    CommandSpec(
        "steamfree",
        (),
        "Notifications",
        "/steamfree [n]",
        "show current Steam free-to-keep games",
        handler="cmd_steamfree_now",
    ),
    CommandSpec(
        "gogfree",
        (),
        "Notifications",
        "/gogfree",
        "show current GOG free games",
        handler="cmd_gogfree_now",
    ),
    CommandSpec(
        "humblefree",
        (),
        "Notifications",
        "/humblefree",
        "show current Humble Bundle free games",
        handler="cmd_humblefree_now",
    ),
    # Media
    CommandSpec(
        "imdb",
        (),
        "Media",
        "/imdb <query>",
        "IMDB lookup (storyline, rating, cast)",
        handler="cmd_imdb",
    ),
    CommandSpec(
        "imdbmovies",
        (),
        "Media",
        "/imdbmovies",
        "IMDB trending movies",
        handler="cmd_imdbmovies",
    ),
    CommandSpec(
        "imdbshows",
        (),
        "Media",
        "/imdbshows",
        "IMDB trending shows",
        handler="cmd_imdbshows",
    ),
    CommandSpec(
        "rtmovies",
        (),
        "Media",
        "/rtmovies",
        "Rotten Tomatoes trending movies",
        handler="cmd_rtmovies",
    ),
    CommandSpec(
        "rtshows",
        (),
        "Media",
        "/rtshows",
        "Rotten Tomatoes trending shows",
        handler="cmd_rtshows",
    ),
    CommandSpec(
        "rtsearch",
        (),
        "Media",
        "/rtsearch <query>",
        "Rotten Tomatoes search with critic quote",
        handler="cmd_rtsearch",
    ),
    # AI
    CommandSpec(
        "ask",
        (),
        "AI",
        "/ask <question>",
        "ask a question, flags: --temp|-t 0.4 --top-k|-k 40 --top-p|-p 0.9 --num-predict|-n 640",
        handler="cmd_ask",
    ),
    CommandSpec(
        "askreset",
        (),
        "AI",
        "/askreset",
        "reset custom AI generation parameters",
        handler="cmd_askreset",
    ),
)


GROUP_ORDER: tuple[Group, ...] = (
    "System",
    "Docker",
    "Network",
    "Torrents",
    "Notifications",
    "Media",
    "AI",
    "Info",
)
