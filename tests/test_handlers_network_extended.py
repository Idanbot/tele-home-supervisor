from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from conftest import DummyContext, DummyUpdate

from tele_home_supervisor.handlers import network
from tele_home_supervisor.handlers.common import get_state
from tele_home_supervisor.models.managed_host import ManagedHost
from tele_home_supervisor.models.network_inventory import (
    NetworkDeviceScan,
    NetworkInventoryScanSummary,
    NetworkService,
)


async def allow_guard(update, context):
    return True


@pytest.mark.asyncio
async def test_netinventory_renders_disabled_pending_and_summary(monkeypatch):
    monkeypatch.setattr(network, "guard_sensitive", allow_guard)
    update = DummyUpdate(chat_id=1, user_id=1)
    context = DummyContext()

    monkeypatch.setattr(network.config, "NETWORK_INVENTORY_TARGETS", [])
    await network.cmd_netinventory(update, context)
    assert "disabled" in update.message.replies[-1]

    monkeypatch.setattr(network.config, "NETWORK_INVENTORY_TARGETS", ["192.168.1.0/24"])
    await network.cmd_netinventory(update, context)
    assert "No network inventory scan" in update.message.replies[-1]

    state = get_state(context.application)
    summary = NetworkInventoryScanSummary(
        scan_id="scan",
        scanned_at=1_700_000_000,
        targets=["192.168.1.0/24"],
        devices_seen=1,
        new_devices=["192.168.1.10"],
        missing_devices=["192.168.1.20"],
        scanner="nmap",
    )
    state.network_inventory_last_summary = summary
    state.network_inventory = {
        "192.168.1.10": [
            NetworkDeviceScan(
                scan_id="scan",
                scanned_at=1_700_000_000,
                ip="192.168.1.10",
                hostname="pi",
                services=[NetworkService(port=22, protocol="tcp", service="ssh")],
            )
        ]
    }
    await network.cmd_netinventory(update, context)
    assert "Network Inventory" in update.message.replies[-1]
    assert "192.168.1.10" in update.message.replies[-1]


@pytest.mark.asyncio
async def test_traceroute_speedtest_and_shutdown_paths(monkeypatch):
    monkeypatch.setattr(network, "guard_sensitive", allow_guard)
    monkeypatch.setattr(
        network.services,
        "traceroute_host",
        AsyncMock(return_value="1:  192.168.1.1  0.5ms\n2:  8.8.8.8  5.5ms"),
    )
    monkeypatch.setattr(network.view, "render_traceroute_chart", lambda hops: None)
    monkeypatch.setattr(
        network.services,
        "speedtest_download",
        AsyncMock(return_value="Size: 1.0MB\nTime: 1.00s\nRate: 8.00 Mb/s"),
    )
    monkeypatch.setattr(network.view, "render_speedtest_chart", lambda mbps: None)
    monkeypatch.setattr(network, "_ping_once", AsyncMock(return_value=True))
    monkeypatch.setattr(
        network,
        "_resolve_shutdown_request",
        lambda target: network._ResolvedShutdownRequest(
            ok=True,
            ping_host="192.168.1.10",
            ssh_target="user@host",
            shutdown_command="shutdown now",
        ),
    )
    monkeypatch.setattr(network.cli, "run_cmd", AsyncMock(return_value=(0, "ok", "")))
    monkeypatch.setattr(network, "_schedule_power_state_watch", Mock())

    update = DummyUpdate(chat_id=1, user_id=1)
    context = DummyContext(args=["example.com", "5"])
    await network.cmd_traceroute(update, context)
    await network.cmd_speedtest(update, DummyContext(args=["10"]))
    await network.cmd_wolshutdown(update, DummyContext(args=[]))

    replies = "\n".join(update.message.replies)
    assert "Traceroute example.com" in replies
    assert "Speedtest" in replies
    assert "Shutdown command accepted" in replies


def test_wol_resolution_helpers(monkeypatch):
    host = ManagedHost(
        name="pc",
        aliases=["desktop"],
        ping_host="192.168.1.10",
        mac="AABBCCDDEEFF",
        wol_broadcast_ip="192.168.1.255",
        wol_port=9,
        ssh_target="user@pc",
        shutdown_command="sudo poweroff",
        ssh_password_env="PC_PASS",
    )
    monkeypatch.setattr(
        network.config,
        "get_managed_host",
        lambda value: host if value in {"pc", "desktop"} else None,
    )
    monkeypatch.setattr(network.config, "default_managed_host", lambda: host)
    monkeypatch.setattr(network.config, "MANAGED_HOSTS", [host])
    monkeypatch.setattr(network.config, "WOL_TARGET_IP", "192.168.1.10")
    monkeypatch.setattr(network.config, "WOL_TARGET_MAC", "aa:bb:cc:dd:ee:ff")
    monkeypatch.setattr(network.config, "WOL_BROADCAST_IP", "192.168.1.255")
    monkeypatch.setattr(network.config, "WOL_PORT", 9)
    monkeypatch.setenv("PC_PASS", "secret")

    wol = network._resolve_wol_request("desktop")
    shutdown = network._resolve_shutdown_request("desktop")
    command, env = network._build_shutdown_ssh_command(shutdown)

    assert wol.ok is True
    assert wol.mac == "aa:bb:cc:dd:ee:ff"
    assert shutdown.ok is True
    assert shutdown.ssh_password == "secret"
    assert command[0] == "sshpass"
    assert env == {"SSHPASS": "secret"}
    assert network._normalize_mac("AA-BB-CC-DD-EE-FF") == "aa:bb:cc:dd:ee:ff"
    assert network._looks_like_ipv4("256.1.1.1") is False
