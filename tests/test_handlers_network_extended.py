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


@pytest.mark.asyncio
async def test_cmd_scanmac_validation_and_usage(monkeypatch):
    monkeypatch.setattr(network, "guard_sensitive", allow_guard)
    update = DummyUpdate(chat_id=1, user_id=1)

    # 1. No args -> usage
    context = DummyContext(args=[])
    await network.cmd_scanmac(update, context)
    assert "Usage:" in update.message.replies[-1]

    # 2. Invalid MAC -> error
    context = DummyContext(args=["not-a-mac"])
    await network.cmd_scanmac(update, context)
    assert "Invalid MAC address" in update.message.replies[-1]

    # 3. Managed host without MAC
    no_mac_host = ManagedHost(name="nohost", ping_host="192.168.1.55", mac="")
    monkeypatch.setattr(
        network.config,
        "get_managed_host",
        lambda name: no_mac_host if name == "nohost" else None,
    )
    context = DummyContext(args=["nohost"])
    await network.cmd_scanmac(update, context)
    assert "has no MAC address configured" in update.message.replies[-1]

    # 4. Valid MAC but no targets configured and unknown LAN
    monkeypatch.setattr(network.config, "NETWORK_INVENTORY_TARGETS", [])
    monkeypatch.setattr(
        network.services.utils, "get_primary_ip", AsyncMock(return_value="unknown")
    )
    context = DummyContext(args=["AA:BB:CC:DD:EE:FF"])
    await network.cmd_scanmac(update, context)
    assert "No network targets configured" in update.message.replies[-1]


@pytest.mark.asyncio
async def test_cmd_scanmac_found_and_not_found(monkeypatch):
    monkeypatch.setattr(network, "guard_sensitive", allow_guard)
    update = DummyUpdate(chat_id=1, user_id=1)
    context = DummyContext(args=["AA:BB:CC:DD:EE:FF", "192.168.1.0/24"])

    summary = NetworkInventoryScanSummary(
        scan_id="s1",
        scanned_at=1_700_000_000,
        targets=["192.168.1.0/24"],
        devices_seen=1,
        scanner="nmap",
    )
    found_dev = NetworkDeviceScan(
        scan_id="s1",
        scanned_at=1_700_000_000,
        ip="192.168.1.42",
        mac="aa:bb:cc:dd:ee:ff",
        status="up",
        hostname="pi.local",
        vendor="Raspberry Pi",
        services=[NetworkService(port=22, protocol="tcp", service="ssh")],
    )

    # 1. Device found
    monkeypatch.setattr(
        network.network_inventory,
        "find_device_by_mac",
        AsyncMock(return_value=(found_dev, [found_dev], summary)),
    )
    await network.cmd_scanmac(update, context)
    reply = update.message.replies[-1]
    assert "Device Found!" in reply
    assert "192.168.1.42" in reply
    assert "AA:BB:CC:DD:EE:FF" in reply
    assert "Raspberry Pi" in reply
    assert "22/tcp (ssh)" in reply

    # 1b. Device found via managed host name with auto-derived LAN subnet
    managed_pc = ManagedHost(
        name="pc", ping_host="192.168.1.42", mac="AA:BB:CC:DD:EE:FF"
    )
    monkeypatch.setattr(
        network.config,
        "get_managed_host",
        lambda name: managed_pc if name == "pc" else None,
    )
    monkeypatch.setattr(network.config, "NETWORK_INVENTORY_TARGETS", [])
    monkeypatch.setattr(
        network.services.utils,
        "get_primary_ip",
        AsyncMock(return_value="192.168.1.100"),
    )
    update_pc = DummyUpdate(chat_id=1, user_id=1)
    context_pc = DummyContext(args=["pc"])
    await network.cmd_scanmac(update_pc, context_pc)
    reply_pc = update_pc.message.replies[-1]
    assert "Device Found!" in reply_pc
    assert "Host:" in reply_pc
    assert "pc" in reply_pc
    assert "192.168.1.0/24" in reply_pc

    # 2. Device not found (with historical last seen)
    state = get_state(context.application)
    state.network_inventory = {"192.168.1.42": [found_dev]}
    monkeypatch.setattr(
        network.network_inventory,
        "find_device_by_mac",
        AsyncMock(return_value=(None, [found_dev], summary)),
    )
    update2 = DummyUpdate(chat_id=1, user_id=1)
    context2 = DummyContext(args=["11:22:33:44:55:66", "192.168.1.0/24"])
    await network.cmd_scanmac(update2, context2)
    reply2 = update2.message.replies[-1]
    assert "MAC Address Not Found" in reply2

    # Device not found but target MAC matches historical record
    update3 = DummyUpdate(chat_id=1, user_id=1)
    context.args = ["AA:BB:CC:DD:EE:FF", "192.168.1.0/24"]
    await network.cmd_scanmac(update3, context)
    reply3 = update3.message.replies[-1]
    assert "MAC Address Not Found" in reply3
    assert "Previously seen at" in reply3
    assert "192.168.1.42" in reply3

    # 3. Exception in scan -> record_error called
    monkeypatch.setattr(
        network.network_inventory,
        "find_device_by_mac",
        AsyncMock(side_effect=RuntimeError("nmap crashed")),
    )
    recorded = []

    async def fake_record_error(recorder, cmd, desc, exc, edit_fn):
        recorded.append((cmd, desc, str(exc)))
        await edit_fn(f"Error: {exc}")

    monkeypatch.setattr(network, "record_error", fake_record_error)
    update4 = DummyUpdate(chat_id=1, user_id=1)
    context4 = DummyContext(args=["AA:BB:CC:DD:EE:FF", "192.168.1.0/24"])
    await network.cmd_scanmac(update4, context4)
    assert len(recorded) == 1
    assert recorded[0][0] == "scanmac"


def test_resolve_default_scan_targets(monkeypatch):
    monkeypatch.setattr(network.config, "NETWORK_INVENTORY_TARGETS", [])
    monkeypatch.setattr(network.config, "MANAGED_HOSTS", [])
    monkeypatch.setattr(network.config, "ALERT_PING_LAN_TARGETS", [])
    monkeypatch.setattr(network.config, "WOL_BROADCAST_IP", "")

    # 1. From WOL_BROADCAST_IP
    monkeypatch.setattr(network.config, "WOL_BROADCAST_IP", "192.168.10.255")
    assert network._resolve_default_scan_targets() == ["192.168.10.0/24"]

    # 2. From MANAGED_HOSTS when WOL_BROADCAST_IP is unset
    monkeypatch.setattr(network.config, "WOL_BROADCAST_IP", "")
    managed_pc = ManagedHost(name="pc", ping_host="192.168.20.5")
    monkeypatch.setattr(network.config, "MANAGED_HOSTS", [managed_pc])
    assert network._resolve_default_scan_targets() == ["192.168.20.0/24"]

    # 3. From ALERT_PING_LAN_TARGETS
    monkeypatch.setattr(network.config, "MANAGED_HOSTS", [])
    monkeypatch.setattr(network.config, "ALERT_PING_LAN_TARGETS", ["192.168.30.1"])
    assert network._resolve_default_scan_targets() == ["192.168.30.0/24"]

    # 4. Fallback to LAN IP
    monkeypatch.setattr(network.config, "ALERT_PING_LAN_TARGETS", [])
    assert network._resolve_default_scan_targets("192.168.40.10") == ["192.168.40.0/24"]


def test_resolve_mac_from_arp(monkeypatch):
    monkeypatch.setattr(
        network.network_inventory,
        "read_arp_table",
        lambda: {"192.168.1.10": "aa:bb:cc:dd:ee:ff"},
    )
    assert network._resolve_mac_from_arp("192.168.1.10") == "aa:bb:cc:dd:ee:ff"
    assert network._resolve_mac_from_arp("192.168.1.99") is None
