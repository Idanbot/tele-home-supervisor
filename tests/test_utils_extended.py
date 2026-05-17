from __future__ import annotations

import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from tele_home_supervisor import utils


@pytest.mark.asyncio
async def test_get_primary_ip_falls_back_to_psutil(monkeypatch):
    monkeypatch.setattr(
        utils.cli,
        "run_cmd",
        AsyncMock(return_value=(1, "", "no route")),
    )
    monkeypatch.setattr(
        utils.psutil,
        "net_if_addrs",
        lambda: {
            "lo": [SimpleNamespace(family=socket.AF_INET, address="127.0.0.1")],
            "eth0": [SimpleNamespace(family=socket.AF_INET, address="192.168.1.5")],
        },
    )

    assert await utils.get_primary_ip() == "192.168.1.5"


@pytest.mark.asyncio
async def test_host_health_collects_expected_fields(monkeypatch):
    monkeypatch.setattr(utils, "get_primary_ip", AsyncMock(return_value="192.168.1.5"))
    monkeypatch.setattr(utils, "get_wan_ip", AsyncMock(return_value="8.8.8.8"))
    monkeypatch.setattr(utils, "get_temp", AsyncMock(return_value="45C"))
    monkeypatch.setattr(utils, "human_uptime", lambda: "1 day")
    monkeypatch.setattr(utils.os, "getloadavg", lambda: (1.0, 2.0, 3.0))
    monkeypatch.setattr(utils.psutil, "cpu_percent", lambda interval=0.2: 12.3)
    monkeypatch.setattr(
        utils.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(used=1024, total=2048, percent=50.0),
    )
    monkeypatch.setattr(
        utils.psutil,
        "disk_usage",
        lambda path: SimpleNamespace(used=100, total=200, percent=50.0),
    )

    data = await utils.host_health(["/"])

    assert data["lan_ip"] == "192.168.1.5"
    assert data["wan_ip"] == "8.8.8.8"
    assert data["cpu_pct"] == 12
    assert data["disks"] == ["/: 100.0 B/200.0 B (50%)"]


@pytest.mark.asyncio
async def test_container_helpers_with_fake_client():
    container = Mock()
    container.name = "app"
    container.image.tags = ["app:latest"]
    container.image.short_id = "sha256:abc"
    container.status = "running"
    container.attrs = {
        "NetworkSettings": {"Ports": {"80/tcp": [{"HostPort": "8080"}]}},
        "State": {"Health": {"Status": "healthy"}},
    }
    container.logs.return_value = b"line1\nline2\nline3"
    client = Mock()
    client.containers.list.return_value = [container]
    client.containers.get.return_value = container

    with patch("tele_home_supervisor.utils.client", client):
        assert await utils.list_container_names() == {"app"}
        basic = await utils.list_containers_basic()
        assert basic[0]["ports"] == "8080->80/tcp"
        assert await utils.get_container_logs("app", lines=2) == "line1\nline2\nline3"
        assert (
            await utils.get_container_logs_full("app", since=123)
            == "line1\nline2\nline3"
        )
        assert await utils.healthcheck_container("app") == "Health: healthy"
        assert await utils.get_container_inspect("app") == container.attrs


@pytest.mark.asyncio
async def test_command_helpers_and_version(monkeypatch):
    monkeypatch.setattr(utils.shutil, "which", lambda name: f"/usr/bin/{name}")
    run = AsyncMock(
        side_effect=[
            (0, "ping output", ""),
            (0, "USER PID\nroot 1\napp 2\n", ""),
            (0, "LISTEN 0 1", ""),
            (0, "2026-01-01 00:00:00", ""),
            (0, "abc123", ""),
            (0, "", "trace err"),
        ]
    )
    monkeypatch.setattr(utils.cli, "run_cmd", run)

    assert await utils.ping_host("host", 2) == "ping output"
    assert "root 1" in await utils.get_top_processes()
    assert await utils.get_listening_ports() == "LISTEN 0 1"
    version = await utils.get_version_info()
    assert version["last_commit"] == "2026-01-01 00:00:00"
    assert version["commit_hash"] == "abc123"
    assert await utils.traceroute_host("host", 4) == "trace err"


@pytest.mark.asyncio
async def test_dns_lookup_disk_usage_and_speedtest_edges(monkeypatch):
    monkeypatch.setattr(
        utils.socket,
        "getaddrinfo",
        lambda *_: [
            (socket.AF_INET, None, None, None, ("1.2.3.4", 0)),
            (socket.AF_INET6, None, None, None, ("2001:db8::1", 0)),
        ],
    )
    assert "1.2.3.4" in await utils.dns_lookup("example.com")

    monkeypatch.setattr(
        utils.psutil,
        "disk_usage",
        lambda path: SimpleNamespace(total=100, used=40, free=60, percent=40.0),
    )
    assert await utils.get_disk_usage_stats(["/"]) == [
        {"path": "/", "total": 100, "used": 40, "free": 60, "percent": 40.0}
    ]

    monkeypatch.setattr(utils.shutil, "which", lambda name: "/usr/bin/curl")
    monkeypatch.setattr(
        utils.cli,
        "run_cmd",
        AsyncMock(
            side_effect=[
                (1, "", "fail"),
                (0, "bad output", ""),
                (0, "TIME:0 SIZE:1", ""),
            ]
        ),
    )
    assert (await utils.speedtest_download(1)).startswith("Speedtest failed")
    assert (
        await utils.speedtest_download(1) == "Speedtest failed: invalid output format"
    )
    assert await utils.speedtest_download(1) == "Invalid duration"


def test_split_telegram_message_long_lines_and_code_blocks():
    text = "```python\n" + ("x" * 120) + "\n```\nend"
    chunks = utils.split_telegram_message(text, limit=50)

    assert len(chunks) > 1
    assert all(len(chunk) <= 60 for chunk in chunks)
    assert chunks[0].startswith("```python")
    assert chunks[-1].endswith("end")


def test_rate_formatting_and_port_formatting():
    assert utils._fmt_rate_kbits(500_000) == "500.00 Kb/s"
    assert utils._fmt_rate_kbits(2_000_000) == "2.00 Mb/s"
    assert utils._format_ports(None) == "-"
    assert utils._format_ports({"80/tcp": None}) == "80/tcp"
