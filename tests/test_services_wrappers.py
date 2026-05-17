from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from tele_home_supervisor import services


@pytest.mark.asyncio
async def test_async_service_wrappers_delegate_to_utils(monkeypatch):
    calls: list[tuple[str, tuple, dict]] = []

    def make_fake(name, value):
        async def fake(*args, **kwargs):
            calls.append((name, args, kwargs))
            return value

        return fake

    delegates = {
        "host_health": {"ok": True},
        "get_disk_usage_stats": [{"path": "/"}],
        "ping_host": "pong",
        "list_containers_basic": [{"name": "app"}],
        "container_stats_rich": [{"name": "app", "cpu": "1%"}],
        "get_container_logs": "logs",
        "get_container_logs_full": "all logs",
        "healthcheck_container": "healthy",
        "get_container_inspect": {"Id": "abc"},
        "get_uptime_info": "1 day",
        "get_version_info": {"build": "test"},
        "list_container_names": {"app"},
        "get_listening_ports": "LISTEN",
        "get_cpu_temp": "42C",
        "get_top_processes": "top",
        "dns_lookup": "1.2.3.4",
        "traceroute_host": "trace",
        "speedtest_download": "Rate: 1 Mb/s",
    }
    for name, value in delegates.items():
        monkeypatch.setattr(
            services.utils,
            name,
            AsyncMock(side_effect=make_fake(name, value)),
        )

    assert await services.host_health(True, ["/"]) == {"ok": True}
    assert await services.get_disk_usage_stats(["/"]) == [{"path": "/"}]
    assert await services.ping_host("host", 2) == "pong"
    assert await services.list_containers() == [{"name": "app"}]
    assert await services.container_stats_rich() == [{"name": "app", "cpu": "1%"}]
    assert await services.get_container_logs("app", 10) == "logs"
    assert await services.get_container_logs_full("app", since=123) == "all logs"
    assert await services.healthcheck_container("app") == "healthy"
    assert await services.get_container_inspect("app") == {"Id": "abc"}
    assert await services.get_uptime_info() == "1 day"
    assert await services.get_version_info() == {"build": "test"}
    assert await services.container_names() == {"app"}
    assert await services.get_listening_ports() == "LISTEN"
    assert await services.get_cpu_temp() == "42C"
    assert await services.get_top_processes() == "top"
    assert await services.dns_lookup("example.com") == "1.2.3.4"
    assert await services.traceroute_host("example.com", 4) == "trace"
    assert await services.speedtest_download(5) == "Rate: 1 Mb/s"
    assert {name for name, _, _ in calls} == set(delegates)


@pytest.mark.asyncio
async def test_external_service_wrappers_and_steam_cache(monkeypatch):
    monkeypatch.setattr(
        services.piratebay,
        "top",
        AsyncMock(return_value=[{"name": "top"}]),
    )
    monkeypatch.setattr(
        services.piratebay,
        "search",
        AsyncMock(return_value=[{"name": "search"}]),
    )
    monkeypatch.setattr(
        services.tmdb,
        "trending_movies",
        AsyncMock(return_value={"movies": []}),
    )
    monkeypatch.setattr(
        services.tmdb,
        "trending_shows",
        AsyncMock(return_value={"shows": []}),
    )
    monkeypatch.setattr(
        services.tmdb,
        "in_cinema",
        AsyncMock(return_value={"cinema": []}),
    )
    monkeypatch.setattr(
        services.tmdb,
        "search_multi",
        AsyncMock(return_value={"results": []}),
    )
    monkeypatch.setattr(
        services.tmdb,
        "movie_details",
        AsyncMock(return_value={"id": 1}),
    )
    monkeypatch.setattr(
        services.tmdb,
        "tv_details",
        AsyncMock(return_value={"id": 2}),
    )
    steam_search = AsyncMock(return_value=[{"appid": 1, "name": "Game"}])
    monkeypatch.setattr(services.protondb, "search_steam_games", steam_search)
    monkeypatch.setattr(
        services.protondb,
        "get_protondb_summary",
        AsyncMock(return_value={"tier": "gold"}),
    )
    monkeypatch.setattr(
        services.protondb,
        "get_steam_app_details",
        AsyncMock(return_value={"name": "Game"}),
    )
    monkeypatch.setattr(
        services.protondb,
        "get_steam_player_count",
        AsyncMock(return_value=42),
    )

    services._STEAM_SEARCH_CACHE.clear()

    assert await services.piratebay_top("100") == [{"name": "top"}]
    assert await services.piratebay_search("ubuntu") == [{"name": "search"}]
    assert await services.tmdb_trending_movies(2) == {"movies": []}
    assert await services.tmdb_trending_shows(2) == {"shows": []}
    assert await services.tmdb_in_cinema(2) == {"cinema": []}
    assert await services.tmdb_search_multi("matrix", 3) == {"results": []}
    assert await services.tmdb_movie_details(1) == {"id": 1}
    assert await services.tmdb_tv_details(2) == {"id": 2}
    assert await services.protondb_search("Portal") == [{"appid": 1, "name": "Game"}]
    assert await services.protondb_search(" portal ") == [{"appid": 1, "name": "Game"}]
    steam_search.assert_awaited_once()
    assert await services.protondb_summary(1) == {"tier": "gold"}
    assert await services.steam_app_details(1) == {"name": "Game"}
    assert await services.steam_player_count(1) == 42


@pytest.mark.asyncio
async def test_torrent_service_wrappers(monkeypatch):
    manager = Mock()
    manager.qbt_client = Mock()
    manager.add_magnet.return_value = "added"
    manager.get_status.return_value = "status"
    manager.stop_by_name.return_value = "stopped"
    manager.start_by_name.return_value = "started"
    manager.preview_by_name.return_value = "preview"
    manager.delete_by_name.return_value = "deleted"
    manager.stop_by_hash.return_value = "hash stopped"
    manager.start_by_hash.return_value = "hash started"
    manager.info_by_hash.return_value = "info"
    manager.delete_by_hash.return_value = "hash deleted"
    manager.get_torrent_list.return_value = [{"hash": "abc"}]
    manager.preview_missing_files.return_value = "missing"
    manager.clean_missing_files.return_value = "cleaned"
    manager.qbt_client.torrents_info.return_value = [Mock(name="Ubuntu")]
    manager.qbt_client.torrents_info.return_value[0].name = "Ubuntu"

    monkeypatch.setattr(services.torrent_mod, "get_manager", lambda: manager)
    monkeypatch.setattr(services.torrent_mod, "reset_manager", Mock())

    assert await services.torrent_add("magnet") == "added"
    assert await services.torrent_status() == "status"
    assert await services.torrent_stop("u") == "stopped"
    assert await services.torrent_start("u") == "started"
    assert await services.torrent_names() == {"Ubuntu"}
    assert await services.torrent_preview("u") == "preview"
    assert await services.torrent_delete("u", delete_files=False) == "deleted"
    assert await services.torrent_stop_by_hash("abc") == "hash stopped"
    assert await services.torrent_start_by_hash("abc") == "hash started"
    assert await services.torrent_info_by_hash("abc") == "info"
    assert await services.torrent_delete_by_hash("abc") == "hash deleted"
    assert await services.get_torrent_list() == [{"hash": "abc"}]
    assert await services.torrent_preview_missing() == "missing"
    assert await services.torrent_clean_missing(delete_files=False) == "cleaned"


def test_call_with_mgr_retries_once(monkeypatch):
    first = Mock()
    first.operation.side_effect = RuntimeError("expired")
    second = Mock()
    second.operation.return_value = "ok"
    managers = iter([first, second])
    reset = Mock()

    monkeypatch.setattr(services.torrent_mod, "get_manager", lambda: next(managers))
    monkeypatch.setattr(services.torrent_mod, "reset_manager", reset)

    assert services._call_with_mgr("operation") == "ok"
    reset.assert_called_once()


def test_call_with_mgr_handles_missing_manager_and_method(monkeypatch):
    monkeypatch.setattr(services.torrent_mod, "get_manager", lambda: None)
    assert services._call_with_mgr("operation") == "Failed to connect to qBittorrent."

    monkeypatch.setattr(services.torrent_mod, "get_manager", lambda: object())
    assert (
        services._call_with_mgr("missing")
        == "Internal error: invalid torrent operation"
    )
