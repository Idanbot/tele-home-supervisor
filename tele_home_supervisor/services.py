"""Business logic services.

These functions are now async. They await async `utils` functions or run
synchronous logic (like qBittorrent) in threads.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import Any

from . import piratebay, utils, tmdb, protondb
from . import torrent as torrent_mod

# Simple in-memory cache for Steam search results
_STEAM_SEARCH_CACHE: OrderedDict[str, tuple[float, list[dict]]] = OrderedDict()
_STEAM_SEARCH_CACHE_TTL = 300  # 5 minutes
_STEAM_SEARCH_CACHE_MAX = 50


def _get_cached_steam_search(query: str) -> list[dict] | None:
    """Get cached Steam search result if still valid."""
    query_lower = query.lower().strip()
    entry = _STEAM_SEARCH_CACHE.get(query_lower)
    if not entry:
        return None
    ts, results = entry
    if time.monotonic() - ts > _STEAM_SEARCH_CACHE_TTL:
        _STEAM_SEARCH_CACHE.pop(query_lower, None)
        return None
    return results


def _cache_steam_search(query: str, results: list[dict]) -> None:
    """Cache Steam search result."""
    query_lower = query.lower().strip()
    _STEAM_SEARCH_CACHE[query_lower] = (time.monotonic(), results)
    # Prune old entries
    while len(_STEAM_SEARCH_CACHE) > _STEAM_SEARCH_CACHE_MAX:
        _STEAM_SEARCH_CACHE.popitem(last=False)


async def host_health(
    show_wan: bool = False, watch_paths: list[str] | None = None
) -> dict[str, Any]:
    return await utils.host_health(watch_paths)


async def list_containers() -> list[dict[str, Any]]:
    return await utils.list_containers_basic()


async def container_stats_rich() -> list[dict[str, str]]:
    return await utils.container_stats_rich()


async def get_container_logs(container_name: str, lines: int = 50) -> str:
    return await utils.get_container_logs(container_name, lines)


async def get_container_logs_full(container_name: str, since: int | None = None) -> str:
    return await utils.get_container_logs_full(container_name, since=since)


async def healthcheck_container(container_name: str) -> str:
    return await utils.healthcheck_container(container_name)


async def get_container_inspect(container_name: str) -> dict:
    return await utils.get_container_inspect(container_name)


async def get_uptime_info() -> str:
    return await utils.get_uptime_info()


async def get_version_info() -> dict[str, str]:
    return await utils.get_version_info()


async def container_names() -> set[str]:
    return await utils.list_container_names()


async def get_listening_ports() -> str:
    return await utils.get_listening_ports()


async def dns_lookup(name: str) -> str:
    return await utils.dns_lookup(name)


async def traceroute_host(host: str, max_hops: int = 20) -> str:
    return await utils.traceroute_host(host, max_hops)


async def speedtest_download(mb: int = 100) -> str:
    return await utils.speedtest_download(mb)


async def piratebay_top(
    category: str | None, debug_sink=None
) -> list[dict[str, object]]:
    return await asyncio.to_thread(piratebay.top, category, debug_sink)


async def piratebay_search(query: str, debug_sink=None) -> list[dict[str, object]]:
    return await asyncio.to_thread(piratebay.search, query, debug_sink)


async def tmdb_trending_movies(page: int = 1) -> dict[str, object]:
    return await asyncio.to_thread(tmdb.trending_movies, page)


async def tmdb_trending_shows(page: int = 1) -> dict[str, object]:
    return await asyncio.to_thread(tmdb.trending_shows, page)


async def tmdb_in_cinema(page: int = 1) -> dict[str, object]:
    return await asyncio.to_thread(tmdb.in_cinema, page)


async def tmdb_search_multi(query: str, page: int = 1) -> dict[str, object]:
    return await asyncio.to_thread(tmdb.search_multi, query, page)


async def tmdb_movie_details(movie_id: int) -> dict[str, object]:
    return await asyncio.to_thread(tmdb.movie_details, movie_id)


async def tmdb_tv_details(tv_id: int) -> dict[str, object]:
    return await asyncio.to_thread(tmdb.tv_details, tv_id)


async def protondb_search(query: str) -> list[dict[str, object]]:
    """Search Steam games with caching."""
    cached = _get_cached_steam_search(query)
    if cached is not None:
        return cached
    results = await asyncio.to_thread(protondb.search_steam_games, query)
    _cache_steam_search(query, results)
    return results


async def protondb_summary(appid: int | str) -> dict[str, object] | None:
    return await asyncio.to_thread(protondb.get_protondb_summary, appid)


async def steam_app_details(appid: int | str) -> dict[str, object] | None:
    return await asyncio.to_thread(protondb.get_steam_app_details, appid)


async def steam_player_count(appid: int | str) -> int | None:
    return await asyncio.to_thread(protondb.get_steam_player_count, appid)


# Torrent helpers (Sync wrappers)


async def torrent_add(magnet: str, save_path: str = "/downloads") -> str:
    return await asyncio.to_thread(_call_with_mgr, "add_magnet", magnet, save_path)


async def torrent_status() -> str:
    return await asyncio.to_thread(_call_with_mgr, "get_status")


async def torrent_stop(name_substr: str) -> str:
    return await asyncio.to_thread(_call_with_mgr, "stop_by_name", name_substr)


async def torrent_start(name_substr: str) -> str:
    return await asyncio.to_thread(_call_with_mgr, "start_by_name", name_substr)


async def torrent_names() -> set[str]:
    def _get():
        mgr = torrent_mod.TorrentManager()
        if not mgr.connect() or mgr.qbt_client is None:
            return set()
        try:
            torrents = mgr.qbt_client.torrents_info() or []
            return {
                str(getattr(t, "name", "") or "")
                for t in torrents
                if getattr(t, "name", None)
            }
        except Exception:
            return set()

    return await asyncio.to_thread(_get)


async def torrent_preview(name_substr: str) -> str:
    return await asyncio.to_thread(_call_with_mgr, "preview_by_name", name_substr)


async def torrent_delete(name_substr: str, delete_files: bool = True) -> str:
    return await asyncio.to_thread(
        _call_with_mgr, "delete_by_name", name_substr, delete_files=delete_files
    )


async def torrent_stop_by_hash(torrent_hash: str) -> str:
    return await asyncio.to_thread(_call_with_mgr, "stop_by_hash", torrent_hash)


async def torrent_start_by_hash(torrent_hash: str) -> str:
    return await asyncio.to_thread(_call_with_mgr, "start_by_hash", torrent_hash)


async def torrent_info_by_hash(torrent_hash: str) -> str:
    return await asyncio.to_thread(_call_with_mgr, "info_by_hash", torrent_hash)


async def get_torrent_list() -> list[dict]:
    """Get list of torrents for inline keyboard."""

    def _get():
        mgr = torrent_mod.TorrentManager()
        if not mgr.connect():
            return []
        return mgr.get_torrent_list()

    return await asyncio.to_thread(_get)


async def torrent_preview_missing() -> str:
    """Preview torrents with missingFiles state."""
    return await asyncio.to_thread(_call_with_mgr, "preview_missing_files")


async def torrent_clean_missing(delete_files: bool = True) -> str:
    """Delete all torrents with missingFiles state."""
    return await asyncio.to_thread(
        _call_with_mgr, "clean_missing_files", delete_files=delete_files
    )


def _call_with_mgr(method_name: str, *args, **kwargs) -> str:
    """Create a TorrentManager, connect, and call a method on it."""
    mgr = torrent_mod.TorrentManager()
    if not mgr.connect():
        return "Failed to connect to qBittorrent."
    method = getattr(mgr, method_name, None)
    if not callable(method):
        return "Internal error: invalid torrent operation"
    return method(*args, **kwargs)
