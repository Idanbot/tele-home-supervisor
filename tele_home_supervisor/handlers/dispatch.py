"""Dispatch layer: applies rate limiting then calls the real handlers."""

from __future__ import annotations

from .common import rate_limit
from . import meta, system, docker, network, torrents, notifications, ai


# Meta
cmd_start = rate_limit(meta.cmd_start)
cmd_help = rate_limit(meta.cmd_help)
cmd_whoami = rate_limit(meta.cmd_whoami)
cmd_version = rate_limit(meta.cmd_version)

# System
cmd_ip = rate_limit(system.cmd_ip)
cmd_health = rate_limit(system.cmd_health)
cmd_uptime = rate_limit(system.cmd_uptime)
cmd_temp = rate_limit(system.cmd_temp)
cmd_top = rate_limit(system.cmd_top)
cmd_ping = rate_limit(system.cmd_ping)

# Docker
cmd_docker = rate_limit(docker.cmd_docker)
cmd_dockerstats = rate_limit(docker.cmd_dockerstats)
cmd_dstats_rich = rate_limit(docker.cmd_dstats_rich)
cmd_dlogs = rate_limit(docker.cmd_dlogs)
cmd_dhealth = rate_limit(docker.cmd_dhealth)
cmd_ports = rate_limit(docker.cmd_ports)

# Network
cmd_dns = rate_limit(network.cmd_dns)
cmd_traceroute = rate_limit(network.cmd_traceroute)
cmd_speedtest = rate_limit(network.cmd_speedtest)

# Torrents
cmd_torrent_add = rate_limit(torrents.cmd_torrent_add)
cmd_torrent_status = rate_limit(torrents.cmd_torrent_status)
cmd_torrent_stop = rate_limit(torrents.cmd_torrent_stop)
cmd_torrent_start = rate_limit(torrents.cmd_torrent_start)
cmd_torrent_delete = rate_limit(torrents.cmd_torrent_delete)
cmd_subscribe = rate_limit(torrents.cmd_subscribe)

# Notifications
cmd_mute_epicgames = rate_limit(notifications.cmd_mute_epicgames)
cmd_mute_hackernews = rate_limit(notifications.cmd_mute_hackernews)
cmd_epicgames_now = rate_limit(notifications.cmd_epicgames_now)
cmd_hackernews_now = rate_limit(notifications.cmd_hackernews_now)
cmd_steamfree_now = rate_limit(notifications.cmd_steamfree_now)
cmd_gogfree_now = rate_limit(notifications.cmd_gogfree_now)
cmd_humblefree_now = rate_limit(notifications.cmd_humblefree_now)

# AI
cmd_ask = rate_limit(ai.cmd_ask)
