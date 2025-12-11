"""Business logic services decoupled from Telegram handlers.

These are thin wrappers around `utils` and `torrent` that return strings
suitable for sending to telegram. They are intentionally synchronous so
`api_functions` can call them via `asyncio.to_thread`.
"""
from __future__ import annotations

from . import utils
from . import torrent as torrent_mod
from .config import settings


def host_health(show_wan: bool = False, watch_paths: list[str] | None = None) -> str:
    return utils.host_health(show_wan, watch_paths)


def list_containers() -> str:
    return utils.list_containers_basic()


def container_stats_summary() -> str:
    return utils.container_stats_summary()


def container_stats_rich() -> str:
    return utils.container_stats_rich()


def get_container_logs(container_name: str, lines: int = 50) -> str:
    return utils.get_container_logs(container_name, lines)


def healthcheck_container(container_name: str) -> str:
    return utils.healthcheck_container(container_name)


def get_uptime_info() -> str:
    return utils.get_uptime_info()


def get_version_info() -> str:
    return utils.get_version_info()


# Torrent helpers
def torrent_add(magnet: str, save_path: str = "/downloads") -> str:
    return _call_with_mgr("add_magnet", magnet, save_path)


def torrent_status() -> str:
    return _call_with_mgr("get_status")


def torrent_stop(name_substr: str) -> str:
    return _call_with_mgr("stop_by_name", name_substr)


def torrent_start(name_substr: str) -> str:
    return _call_with_mgr("start_by_name", name_substr)


def _call_with_mgr(method_name: str, *args, **kwargs) -> str:
    """Create a TorrentManager, connect, and call a method on it.

    Returns a user-friendly error string if connection fails or the method
    is missing; otherwise returns the method's result.
    """
    mgr = torrent_mod.TorrentManager()
    if not mgr.connect():
        return "Failed to connect to qBittorrent."
    method = getattr(mgr, method_name, None)
    if not callable(method):
        return "Internal error: invalid torrent operation"
    return method(*args, **kwargs)
