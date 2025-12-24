"""Command registry (single source of truth for help + wiring)."""

from __future__ import annotations

from .models.command_spec import CommandSpec, Group


_INFO_COMMANDS = (
    CommandSpec("start", "Info", "/start", "show help", "cmd_start"),
    CommandSpec("help", "Info", "/help", "this menu", "cmd_help"),
    CommandSpec("whoami", "Info", "/whoami", "show chat and user info", "cmd_whoami"),
    CommandSpec(
        "auth",
        "Info",
        "/auth <code>",
        "authorize sensitive commands for 24 hours",
        "cmd_auth",
    ),
    CommandSpec(
        "check_auth",
        "Info",
        "/check_auth",
        "check auth status and time remaining",
        "cmd_check_auth",
    ),
    CommandSpec(
        "version",
        "Info",
        "/version",
        "bot version and build info",
        "cmd_version",
    ),
    CommandSpec(
        "metrics",
        "Info",
        "/metrics",
        "command metrics summary",
        "cmd_metrics",
    ),
    CommandSpec(
        "debug",
        "Info",
        "/debug [command]",
        "recent errors/debug info",
        "cmd_debug",
    ),
)

_SYSTEM_COMMANDS = (
    CommandSpec("ip", "System", "/ip", "private LAN IP", "cmd_ip"),
    CommandSpec(
        "health",
        "System",
        "/health",
        "CPU/RAM/disk/load/uptime (and WAN if enabled)",
        "cmd_health",
    ),
    CommandSpec("uptime", "System", "/uptime", "system uptime", "cmd_uptime"),
    CommandSpec(
        "temp",
        "System",
        "/temp",
        "CPU temperature (reads /host_thermal/temp)",
        "cmd_temp",
    ),
    CommandSpec("top", "System", "/top", "top CPU processes", "cmd_top"),
)

_DOCKER_COMMANDS = (
    CommandSpec(
        "docker",
        "Docker",
        "/docker",
        "list containers, status, ports",
        "cmd_docker",
    ),
    CommandSpec(
        "dinspect",
        "Docker",
        "/dinspect <container>",
        "inspect container (JSON, file if large)",
        "cmd_dinspect",
        needs="container",
    ),
    CommandSpec(
        "dockerstats",
        "Docker",
        "/dockerstats",
        "CPU/MEM per running container",
        "cmd_dockerstats",
    ),
    CommandSpec(
        "dstatsrich",
        "Docker",
        "/dstatsrich",
        "detailed Docker stats (net/block IO)",
        "cmd_dstats_rich",
    ),
    CommandSpec(
        "dlogs",
        "Docker",
        "/dlogs <container> [page] [--since <time>] [--file]",
        "container logs (default sends file; use page for pagination)",
        "cmd_dlogs",
        needs="container",
    ),
    CommandSpec(
        "dhealth",
        "Docker",
        "/dhealth <container>",
        "container health check",
        "cmd_dhealth",
        needs="container",
    ),
)

_NETWORK_COMMANDS = (
    CommandSpec(
        "ping",
        "Network",
        "/ping <ip> [count]",
        "ping an IP or hostname",
        "cmd_ping",
    ),
    CommandSpec(
        "ports",
        "Network",
        "/ports",
        "listening ports (inside container)",
        "cmd_ports",
    ),
    CommandSpec("dns", "Network", "/dns <name>", "DNS lookup", "cmd_dns"),
    CommandSpec(
        "traceroute",
        "Network",
        "/traceroute <host> [max_hops]",
        "trace network route",
        "cmd_traceroute",
    ),
    CommandSpec(
        "speedtest",
        "Network",
        "/speedtest [MB]",
        "quick download speed test",
        "cmd_speedtest",
    ),
)

_TORRENTS_COMMANDS = (
    CommandSpec(
        "tadd",
        "Torrents",
        "/tadd <torrent> [save_path]",
        "add torrent (magnet/URL)",
        "cmd_torrent_add",
    ),
    CommandSpec(
        "tstatus",
        "Torrents",
        "/tstatus",
        "show torrent status",
        "cmd_torrent_status",
    ),
    CommandSpec(
        "tstop",
        "Torrents",
        "/tstop <torrent>",
        "pause torrent(s) by name",
        "cmd_torrent_stop",
        needs="torrent",
    ),
    CommandSpec(
        "tstart",
        "Torrents",
        "/tstart <torrent>",
        "resume torrent(s) by name",
        "cmd_torrent_start",
        needs="torrent",
    ),
    CommandSpec(
        "tdelete",
        "Torrents",
        "/tdelete <torrent> yes",
        "delete torrent(s) and files",
        "cmd_torrent_delete",
        needs="torrent",
    ),
    CommandSpec(
        "subscribe",
        "Torrents",
        "/subscribe [on|off|status]",
        "torrent completion notifications",
        "cmd_subscribe",
    ),
    CommandSpec(
        "pbtop",
        "Torrents",
        "/pbtop [category]",
        "top Pirate Bay torrents (audio, video, apps, games, porn, other)",
        "cmd_pbtop",
    ),
    CommandSpec(
        "pbsearch",
        "Torrents",
        "/pbsearch <query>",
        "search Pirate Bay torrents",
        "cmd_pbsearch",
    ),
)

_NOTIFICATIONS_COMMANDS = (
    CommandSpec(
        "mute_gameoffers",
        "Notifications",
        "/mute_gameoffers",
        "toggle Game Offers daily notifications (8 PM)",
        "cmd_mute_gameoffers",
    ),
    CommandSpec(
        "mute_hackernews",
        "Notifications",
        "/mute_hackernews",
        "toggle Hacker News daily digest (8 AM)",
        "cmd_mute_hackernews",
    ),
    CommandSpec(
        "gameoffers",
        "Notifications",
        "/gameoffers",
        "show combined game offers (Epic/Steam/GOG/Humble)",
        "cmd_gameoffers_now",
    ),
    CommandSpec(
        "epicgames",
        "Notifications",
        "/epicgames",
        "check current Epic Games free games",
        "cmd_epicgames_now",
    ),
    CommandSpec(
        "hackernews",
        "Notifications",
        "/hackernews [n]",
        "show top N Hacker News stories (default: 5)",
        "cmd_hackernews_now",
    ),
    CommandSpec(
        "steamfree",
        "Notifications",
        "/steamfree [n]",
        "show current Steam free-to-keep games",
        "cmd_steamfree_now",
    ),
    CommandSpec(
        "gogfree",
        "Notifications",
        "/gogfree",
        "show current GOG free games",
        "cmd_gogfree_now",
    ),
    CommandSpec(
        "humblefree",
        "Notifications",
        "/humblefree",
        "show current Humble Bundle free games",
        "cmd_humblefree_now",
    ),
)

_MEDIA_COMMANDS = (
    CommandSpec(
        "movies",
        "Media",
        "/movies",
        "TMDB trending movies",
        "cmd_movies",
    ),
    CommandSpec(
        "shows",
        "Media",
        "/shows",
        "TMDB trending shows",
        "cmd_shows",
    ),
    CommandSpec(
        "incinema",
        "Media",
        "/incinema",
        "TMDB in cinemas now",
        "cmd_incinema",
    ),
    CommandSpec(
        "tmdb",
        "Media",
        "/tmdb <query>",
        "TMDB search (movies + shows)",
        "cmd_tmdb",
    ),
    CommandSpec(
        "protondb",
        "Media",
        "/protondb <game>",
        "ProtonDB Linux/Steam Deck compatibility",
        "cmd_protondb",
    ),
)

_AI_COMMANDS = (
    CommandSpec(
        "ask",
        "AI",
        "/ask <question>",
        "ask a question, flags: --temp|-t 0.4 --top-k|-k 40 --top-p|-p 0.9 --num-predict|-n 640",
        "cmd_ask",
    ),
    CommandSpec(
        "askreset",
        "AI",
        "/askreset",
        "reset custom AI generation parameters",
        "cmd_askreset",
    ),
)


COMMANDS: tuple[CommandSpec, ...] = (
    *_INFO_COMMANDS,
    *_SYSTEM_COMMANDS,
    *_DOCKER_COMMANDS,
    *_NETWORK_COMMANDS,
    *_TORRENTS_COMMANDS,
    *_NOTIFICATIONS_COMMANDS,
    *_MEDIA_COMMANDS,
    *_AI_COMMANDS,
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
