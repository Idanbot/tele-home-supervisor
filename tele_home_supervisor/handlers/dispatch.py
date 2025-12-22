"""Dispatch layer: applies rate limiting then calls the real handlers."""

from __future__ import annotations

from .common import rate_limit
from . import meta, system, docker, network, torrents, notifications, ai, media


# Meta
cmd_start = rate_limit(meta.cmd_start, name="start")
cmd_help = rate_limit(meta.cmd_help, name="help")
cmd_whoami = rate_limit(meta.cmd_whoami, name="whoami")
cmd_auth = rate_limit(meta.cmd_auth, name="auth")
cmd_version = rate_limit(meta.cmd_version, name="version")
cmd_metrics = rate_limit(meta.cmd_metrics, name="metrics")
cmd_debug = rate_limit(meta.cmd_debug, name="debug")

# System
cmd_ip = rate_limit(system.cmd_ip, name="ip")
cmd_health = rate_limit(system.cmd_health, name="health")
cmd_uptime = rate_limit(system.cmd_uptime, name="uptime")
cmd_temp = rate_limit(system.cmd_temp, name="temp")
cmd_top = rate_limit(system.cmd_top, name="top")
cmd_ping = rate_limit(system.cmd_ping, name="ping")

# Docker
cmd_docker = rate_limit(docker.cmd_docker, name="docker")
cmd_dockerstats = rate_limit(docker.cmd_dockerstats, name="dockerstats")
cmd_dstats_rich = rate_limit(docker.cmd_dstats_rich, name="dstatsrich")
cmd_dlogs = rate_limit(docker.cmd_dlogs, name="dlogs")
cmd_dhealth = rate_limit(docker.cmd_dhealth, name="dhealth")
cmd_dinspect = rate_limit(docker.cmd_dinspect, name="dinspect")
cmd_ports = rate_limit(docker.cmd_ports, name="ports")

# Network
cmd_dns = rate_limit(network.cmd_dns, name="dns")
cmd_traceroute = rate_limit(network.cmd_traceroute, name="traceroute")
cmd_speedtest = rate_limit(network.cmd_speedtest, name="speedtest")

# Torrents
cmd_torrent_add = rate_limit(torrents.cmd_torrent_add, name="torrentadd")
cmd_torrent_status = rate_limit(torrents.cmd_torrent_status, name="torrentstatus")
cmd_torrent_stop = rate_limit(torrents.cmd_torrent_stop, name="torrentstop")
cmd_torrent_start = rate_limit(torrents.cmd_torrent_start, name="torrentstart")
cmd_torrent_delete = rate_limit(torrents.cmd_torrent_delete, name="torrentdelete")
cmd_subscribe = rate_limit(torrents.cmd_subscribe, name="subscribe")
cmd_pbtop = rate_limit(torrents.cmd_pbtop, name="pbtop")
cmd_pbsearch = rate_limit(torrents.cmd_pbsearch, name="pbsearch")

# Notifications
cmd_mute_gameoffers = rate_limit(notifications.cmd_mute_gameoffers, name="muteoffers")
cmd_mute_hackernews = rate_limit(notifications.cmd_mute_hackernews, name="mutehn")
cmd_epicgames_now = rate_limit(notifications.cmd_epicgames_now, name="epicgames")
cmd_gameoffers_now = rate_limit(notifications.cmd_gameoffers_now, name="gameoffers")
cmd_hackernews_now = rate_limit(notifications.cmd_hackernews_now, name="hackernews")
cmd_steamfree_now = rate_limit(notifications.cmd_steamfree_now, name="steamfree")
cmd_gogfree_now = rate_limit(notifications.cmd_gogfree_now, name="gogfree")
cmd_humblefree_now = rate_limit(notifications.cmd_humblefree_now, name="humblefree")

# AI
cmd_ask = rate_limit(ai.cmd_ask, name="ask")
cmd_askreset = rate_limit(ai.cmd_askreset, name="askreset")

# Media
cmd_movies = rate_limit(media.cmd_movies, name="movies")
cmd_shows = rate_limit(media.cmd_shows, name="shows")
cmd_incinema = rate_limit(media.cmd_incinema, name="incinema")
cmd_tmdb = rate_limit(media.cmd_tmdb, name="tmdb")
