"""Dispatch layer: applies rate limiting then calls the real handlers."""
from __future__ import annotations

from .common import run_rate_limited
from . import meta, system, docker, network, torrents


async def cmd_start(update, context) -> None:
    await run_rate_limited(update, context, meta.cmd_start)


async def cmd_help(update, context) -> None:
    await run_rate_limited(update, context, meta.cmd_help)


async def cmd_whoami(update, context) -> None:
    await run_rate_limited(update, context, meta.cmd_whoami)


async def cmd_version(update, context) -> None:
    await run_rate_limited(update, context, meta.cmd_version)


async def cmd_ip(update, context) -> None:
    await run_rate_limited(update, context, system.cmd_ip)


async def cmd_health(update, context) -> None:
    await run_rate_limited(update, context, system.cmd_health)


async def cmd_uptime(update, context) -> None:
    await run_rate_limited(update, context, system.cmd_uptime)


async def cmd_temp(update, context) -> None:
    await run_rate_limited(update, context, system.cmd_temp)


async def cmd_top(update, context) -> None:
    await run_rate_limited(update, context, system.cmd_top)


async def cmd_ping(update, context) -> None:
    await run_rate_limited(update, context, system.cmd_ping)


async def cmd_docker(update, context) -> None:
    await run_rate_limited(update, context, docker.cmd_docker)


async def cmd_dockerstats(update, context) -> None:
    await run_rate_limited(update, context, docker.cmd_dockerstats)


async def cmd_dstats_rich(update, context) -> None:
    await run_rate_limited(update, context, docker.cmd_dstats_rich)


async def cmd_dlogs(update, context) -> None:
    await run_rate_limited(update, context, docker.cmd_dlogs)


async def cmd_dhealth(update, context) -> None:
    await run_rate_limited(update, context, docker.cmd_dhealth)


async def cmd_ports(update, context) -> None:
    await run_rate_limited(update, context, docker.cmd_ports)


async def cmd_dns(update, context) -> None:
    await run_rate_limited(update, context, network.cmd_dns)


async def cmd_traceroute(update, context) -> None:
    await run_rate_limited(update, context, network.cmd_traceroute)


async def cmd_speedtest(update, context) -> None:
    await run_rate_limited(update, context, network.cmd_speedtest)


async def cmd_torrent_add(update, context) -> None:
    await run_rate_limited(update, context, torrents.cmd_torrent_add)


async def cmd_torrent_status(update, context) -> None:
    await run_rate_limited(update, context, torrents.cmd_torrent_status)


async def cmd_torrent_stop(update, context) -> None:
    await run_rate_limited(update, context, torrents.cmd_torrent_stop)


async def cmd_torrent_start(update, context) -> None:
    await run_rate_limited(update, context, torrents.cmd_torrent_start)


async def cmd_torrent_delete(update, context) -> None:
    await run_rate_limited(update, context, torrents.cmd_torrent_delete)


async def cmd_subscribe(update, context) -> None:
    await run_rate_limited(update, context, torrents.cmd_subscribe)

