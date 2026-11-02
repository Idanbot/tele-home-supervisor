import time
from pathlib import Path

import pytest
from defusedxml.common import DefusedXmlException

from tele_home_supervisor import network_inventory
from tele_home_supervisor.models.bot_state import BotState
from tele_home_supervisor.models.network_inventory import (
    NetworkDeviceScan,
    NetworkInventoryScanSummary,
    NetworkService,
)

NMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<nmaprun>
  <host>
    <status state="up"/>
    <address addr="192.168.1.10" addrtype="ipv4"/>
    <address addr="AA:BB:CC:DD:EE:FF" addrtype="mac" vendor="Raspberry Pi"/>
    <hostnames>
      <hostname name="desktop.local" type="PTR"/>
    </hostnames>
    <ports>
      <port protocol="tcp" portid="22">
        <state state="open"/>
        <service name="ssh"/>
      </port>
      <port protocol="tcp" portid="80">
        <state state="closed"/>
        <service name="http"/>
      </port>
    </ports>
  </host>
</nmaprun>
"""


def test_parse_nmap_xml_records_device_services() -> None:
    devices = network_inventory._parse_nmap_xml("scan1", 123.0, NMAP_XML)

    assert len(devices) == 1
    device = devices[0]
    assert device.ip == "192.168.1.10"
    assert device.hostname == "desktop.local"
    assert device.status == "up"
    assert device.mac == "AA:BB:CC:DD:EE:FF"
    assert device.vendor == "Raspberry Pi"
    assert device.services == [NetworkService(port=22, protocol="tcp", service="ssh")]


def test_parse_nmap_xml_rejects_entity_expansion() -> None:
    unsafe_xml = """<?xml version="1.0"?>
<!DOCTYPE nmaprun [
  <!ENTITY local "blocked">
]>
<nmaprun><host><address addr="&local;" addrtype="ipv4"/></host></nmaprun>
"""

    with pytest.raises(DefusedXmlException):
        network_inventory._parse_nmap_xml("scan1", 123.0, unsafe_xml)


@pytest.mark.asyncio
async def test_scan_uses_nmap_when_available(monkeypatch) -> None:
    monkeypatch.setattr(network_inventory.shutil, "which", lambda name: "/usr/bin/nmap")

    async def fake_run_cmd(cmd, timeout=10, env=None):
        assert cmd[:3] == ["nmap", "-oX", "-"]
        assert "-F" in cmd
        assert "192.168.1.0/24" in cmd
        return 0, NMAP_XML, ""

    monkeypatch.setattr(network_inventory.cli, "run_cmd", fake_run_cmd)

    summary, devices = await network_inventory.scan_network_inventory(
        ["192.168.1.0/24"],
        nmap_args=["-F"],
        timeout_s=30,
    )

    assert summary.scanner == "nmap"
    assert summary.devices_seen == 1
    assert devices[0].ip == "192.168.1.10"


@pytest.mark.asyncio
async def test_scan_reports_invalid_nmap_xml(monkeypatch) -> None:
    monkeypatch.setattr(network_inventory.shutil, "which", lambda name: "/usr/bin/nmap")

    async def fake_run_cmd(cmd, timeout=10, env=None):
        return 0, "<nmaprun>", ""

    monkeypatch.setattr(network_inventory.cli, "run_cmd", fake_run_cmd)

    summary, devices = await network_inventory.scan_network_inventory(
        ["192.168.1.0/24"],
        nmap_args=["-F"],
        timeout_s=30,
    )

    assert devices == []
    assert summary.devices_seen == 0
    assert summary.error.startswith("invalid nmap XML output:")


@pytest.mark.asyncio
async def test_scan_handles_empty_targets_and_ping_fallback(monkeypatch) -> None:
    summary, devices = await network_inventory.scan_network_inventory(
        ["", "not-an-ip"],
        nmap_args=[],
        timeout_s=30,
    )
    assert devices == []
    assert summary.error == "no targets configured"

    monkeypatch.setattr(network_inventory.shutil, "which", lambda name: None)

    async def fake_run_cmd(cmd, timeout=10, env=None):
        if cmd[-1] == "192.168.1.1":
            return 0, "pong", ""
        return 1, "", "timeout"

    monkeypatch.setattr(network_inventory.cli, "run_cmd", fake_run_cmd)

    summary, devices = await network_inventory.scan_network_inventory(
        ["192.168.1.1", "192.168.1.2"],
        nmap_args=[],
        timeout_s=30,
    )

    assert summary.scanner == "ping"
    assert summary.devices_seen == 1
    assert devices[0].ip == "192.168.1.1"


def test_expand_ping_targets_caps_large_networks() -> None:
    ips = network_inventory._expand_ping_targets(["192.168.1.1", "10.0.0.0/16"])

    assert ips[0] == "192.168.1.1"
    assert len(ips) == 513


def test_bot_state_inventory_lifecycle_persists_and_prunes(tmp_path: Path) -> None:
    database_file = tmp_path / "state.sqlite3"
    state = BotState()
    state._database_file = database_file
    old = time.time() - 10 * 86400
    now = time.time()

    first_summary = NetworkInventoryScanSummary(
        scan_id="old",
        scanned_at=old,
        targets=["192.168.1.0/24"],
        devices_seen=1,
        scanner="nmap",
    )
    state.record_network_inventory_scan(
        first_summary,
        [NetworkDeviceScan(scan_id="old", scanned_at=old, ip="192.168.1.10")],
        retention_days=30,
        max_scans_per_device=2,
    )

    second_summary = NetworkInventoryScanSummary(
        scan_id="new",
        scanned_at=now,
        targets=["192.168.1.0/24"],
        devices_seen=1,
        scanner="nmap",
    )
    new_devices, missing_devices = state.record_network_inventory_scan(
        second_summary,
        [NetworkDeviceScan(scan_id="new", scanned_at=now, ip="192.168.1.20")],
        retention_days=1,
        max_scans_per_device=2,
    )

    assert new_devices == ["192.168.1.20"]
    assert missing_devices == []
    assert "192.168.1.10" not in state.network_inventory
    assert "192.168.1.20" in state.network_inventory

    loaded = BotState()
    loaded._database_file = database_file
    loaded.load_state()

    assert loaded.network_inventory_last_summary is not None
    assert loaded.network_inventory_last_summary.scan_id == "new"
    assert loaded.latest_network_inventory()[0].ip == "192.168.1.20"


def test_normalize_mac():
    assert network_inventory.normalize_mac("AA:BB:CC:DD:EE:FF") == "aa:bb:cc:dd:ee:ff"
    assert network_inventory.normalize_mac("aa-bb-cc-dd-ee-ff") == "aa:bb:cc:dd:ee:ff"
    assert network_inventory.normalize_mac("aabb.ccdd.eeff") == "aa:bb:cc:dd:ee:ff"
    assert network_inventory.normalize_mac("aabbccddeeff") == "aa:bb:cc:dd:ee:ff"
    assert network_inventory.normalize_mac("invalid") is None
    assert network_inventory.normalize_mac("") is None
    assert network_inventory.normalize_mac("AA:BB:CC") is None


def test_read_arp_table(tmp_path: Path):
    arp_file = tmp_path / "arp"
    arp_file.write_text(
        "IP address       HW type     Flags       HW address            Mask     Device\n"
        "192.168.1.10     0x1         0x2         aa:bb:cc:dd:ee:ff     *        eth0\n"
        "192.168.1.11     0x1         0x0         00:00:00:00:00:00     *        eth0\n"
        "192.168.1.12     0x1         0x2         11-22-33-44-55-66     *        eth0\n"
    )
    table = network_inventory.read_arp_table(str(arp_file))
    assert table == {
        "192.168.1.10": "aa:bb:cc:dd:ee:ff",
        "192.168.1.12": "11:22:33:44:55:66",
    }
    # Nonexistent file returns empty dict
    assert network_inventory.read_arp_table(str(tmp_path / "nonexistent")) == {}


@pytest.mark.asyncio
async def test_find_device_by_mac_direct(monkeypatch, tmp_path: Path):
    dummy_summary = NetworkInventoryScanSummary(
        scan_id="s1", scanned_at=100.0, targets=["192.168.1.0/24"], devices_seen=1
    )
    dummy_device = NetworkDeviceScan(
        scan_id="s1",
        scanned_at=100.0,
        ip="192.168.1.42",
        mac="AA:BB:CC:DD:EE:FF",
        hostname="my-pi",
    )

    async def fake_scan(targets, nmap_args=None, timeout_s=45):
        return dummy_summary, [dummy_device]

    monkeypatch.setattr(network_inventory, "scan_network_inventory", fake_scan)

    dev, devices, summary = await network_inventory.find_device_by_mac(
        "aa:bb:cc:dd:ee:ff", ["192.168.1.0/24"]
    )
    assert dev is not None
    assert dev.ip == "192.168.1.42"
    assert summary.scan_id == "s1"

    # Test not found
    dev_nf, _, _ = await network_inventory.find_device_by_mac(
        "11:22:33:44:55:66",
        ["192.168.1.0/24"],
        arp_path=str(tmp_path / "nonexistent_arp"),
    )
    assert dev_nf is None

    # Test invalid mac raises
    with pytest.raises(ValueError):
        await network_inventory.find_device_by_mac("invalid_mac", ["192.168.1.0/24"])


@pytest.mark.asyncio
async def test_find_device_by_mac_via_arp(monkeypatch, tmp_path: Path):
    dummy_summary = NetworkInventoryScanSummary(
        scan_id="s2", scanned_at=200.0, targets=["192.168.1.0/24"], devices_seen=1
    )
    # Scan found an IP but without MAC
    dummy_device = NetworkDeviceScan(
        scan_id="s2", scanned_at=200.0, ip="192.168.1.50", mac=""
    )

    arp_file = tmp_path / "arp"
    arp_file.write_text(
        "IP address       HW type     Flags       HW address            Mask     Device\n"
        "192.168.1.50     0x1         0x2         aa:bb:cc:dd:ee:ff     *        eth0\n"
    )

    async def fake_scan(targets, nmap_args=None, timeout_s=45):
        return dummy_summary, [dummy_device]

    monkeypatch.setattr(network_inventory, "scan_network_inventory", fake_scan)

    dev, devices, summary = await network_inventory.find_device_by_mac(
        "aa:bb:cc:dd:ee:ff", ["192.168.1.0/24"], arp_path=str(arp_file)
    )
    assert dev is not None
    assert dev.ip == "192.168.1.50"
    assert dev.mac == "aa:bb:cc:dd:ee:ff"
