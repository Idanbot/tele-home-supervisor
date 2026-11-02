"""Home network inventory scanner."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import re
import shutil
import time
import uuid

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from . import cli
from .models.network_inventory import (
    NetworkDeviceScan,
    NetworkInventoryScanSummary,
    NetworkService,
)

logger = logging.getLogger(__name__)


async def scan_network_inventory(
    targets: list[str],
    *,
    nmap_args: list[str],
    timeout_s: int,
) -> tuple[NetworkInventoryScanSummary, list[NetworkDeviceScan]]:
    """Scan configured network targets and return per-device observations."""
    scan_id = uuid.uuid4().hex[:12]
    scanned_at = time.time()
    normalized_targets = _normalize_targets(targets)
    if not normalized_targets:
        return (
            NetworkInventoryScanSummary(
                scan_id=scan_id,
                scanned_at=scanned_at,
                targets=[],
                devices_seen=0,
                error="no targets configured",
            ),
            [],
        )

    if shutil.which("nmap"):
        summary, devices = await _scan_with_nmap(
            scan_id,
            scanned_at,
            normalized_targets,
            nmap_args=nmap_args,
            timeout_s=timeout_s,
        )
    else:
        summary, devices = await _scan_with_ping(
            scan_id,
            scanned_at,
            normalized_targets,
            timeout_s=timeout_s,
        )
    return summary, devices


def normalize_mac(mac: str) -> str | None:
    """Normalize MAC address to lowercase colon-separated format."""
    clean_mac = re.sub(r"[^0-9a-fA-F]", "", mac or "")
    if len(clean_mac) != 12:
        return None
    return ":".join(clean_mac[i : i + 2] for i in range(0, 12, 2)).lower()


def read_arp_table(arp_path: str | None = None) -> dict[str, str]:
    """Return mapping of IPv4 -> normalized MAC from system or host ARP cache."""
    if arp_path is None:
        candidates = [
            os.environ.get("HOST_ARP_PATH", ""),
            "/host_proc/net/arp",
            "/host/proc/net/arp",
            "/host_arp",
            "/proc/net/arp",
        ]
        for candidate in candidates:
            if candidate and os.path.exists(candidate):
                arp_path = candidate
                break
        if not arp_path:
            arp_path = "/proc/net/arp"

    table: dict[str, str] = {}
    try:
        with open(arp_path) as f:
            for line in f.readlines()[1:]:
                parts = line.split()
                if len(parts) >= 4:
                    ip = parts[0]
                    mac = parts[3]
                    if mac != "00:00:00:00:00:00":
                        norm = normalize_mac(mac)
                        if norm:
                            table[ip] = norm
    except OSError as exc:
        logger.debug("Failed to read ARP cache from %s: %s", arp_path, exc)
    return table


async def find_device_by_mac(
    mac: str,
    targets: list[str],
    *,
    nmap_args: list[str] | None = None,
    timeout_s: int = 45,
    arp_path: str | None = None,
) -> tuple[
    NetworkDeviceScan | None, list[NetworkDeviceScan], NetworkInventoryScanSummary
]:
    """Scan targets looking for a device matching the target MAC address."""
    norm_mac = normalize_mac(mac)
    if not norm_mac:
        raise ValueError(f"Invalid MAC address: {mac}")

    summary, devices = await scan_network_inventory(
        targets,
        nmap_args=nmap_args if nmap_args is not None else ["-T4", "-F"],
        timeout_s=timeout_s,
    )

    # 1. Match directly from scan observations
    for dev in devices:
        if normalize_mac(dev.mac) == norm_mac:
            return dev, devices, summary

    # 2. Check ARP table in case host replied but scanner didn't parse MAC
    arp_table = read_arp_table(arp_path=arp_path)
    matched_ips = [ip for ip, m in arp_table.items() if m == norm_mac]
    if matched_ips:
        matched_ip = matched_ips[0]
        for dev in devices:
            if dev.ip == matched_ip:
                dev.mac = norm_mac
                return dev, devices, summary

        # Device is in ARP cache but wasn't in scanned devices list
        dev = NetworkDeviceScan(
            scan_id=summary.scan_id,
            scanned_at=summary.scanned_at,
            ip=matched_ip,
            mac=norm_mac,
            status="up",
        )
        devices.append(dev)
        return dev, devices, summary

    return None, devices, summary


def _normalize_targets(targets: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in targets:
        target = (raw or "").strip()
        if not target:
            continue
        try:
            if "/" in target:
                network = ipaddress.ip_network(target, strict=False)
                target = str(network)
            else:
                target = str(ipaddress.ip_address(target))
        except ValueError:
            logger.debug("Skipping invalid inventory target: %r", raw)
            continue
        if target not in seen:
            out.append(target)
            seen.add(target)
    return out


async def _scan_with_nmap(
    scan_id: str,
    scanned_at: float,
    targets: list[str],
    *,
    nmap_args: list[str],
    timeout_s: int,
) -> tuple[NetworkInventoryScanSummary, list[NetworkDeviceScan]]:
    args = ["nmap", "-oX", "-", *nmap_args, *targets]
    rc, out, err = await cli.run_cmd(args, timeout=timeout_s)
    if rc != 0 or not out:
        message = err or f"nmap exited with {rc}"
        return (
            NetworkInventoryScanSummary(
                scan_id=scan_id,
                scanned_at=scanned_at,
                targets=targets,
                devices_seen=0,
                scanner="nmap",
                error=message,
            ),
            [],
        )
    try:
        devices = _parse_nmap_xml(scan_id, scanned_at, out)
    except (DefusedXmlException, ElementTree.ParseError, ValueError) as exc:
        return (
            NetworkInventoryScanSummary(
                scan_id=scan_id,
                scanned_at=scanned_at,
                targets=targets,
                devices_seen=0,
                scanner="nmap",
                error=f"invalid nmap XML output: {exc}",
            ),
            [],
        )
    return (
        NetworkInventoryScanSummary(
            scan_id=scan_id,
            scanned_at=scanned_at,
            targets=targets,
            devices_seen=len(devices),
            scanner="nmap",
        ),
        devices,
    )


def _parse_nmap_xml(
    scan_id: str, scanned_at: float, text: str
) -> list[NetworkDeviceScan]:
    root = ElementTree.fromstring(text)
    devices: list[NetworkDeviceScan] = []
    for host in root.findall("host"):
        status = (
            host.find("status").get("state", "")
            if host.find("status") is not None
            else ""
        )
        ip = ""
        mac = ""
        vendor = ""
        for address in host.findall("address"):
            addr = address.get("addr", "").strip()
            addr_type = address.get("addrtype", "").strip().lower()
            if addr_type == "ipv4" and not ip:
                ip = addr
            elif addr_type == "mac" and not mac:
                mac = addr
                vendor = address.get("vendor", "").strip()
        if not ip:
            continue

        hostname = ""
        hostnames = host.find("hostnames")
        if hostnames is not None:
            for node in hostnames.findall("hostname"):
                hostname = node.get("name", "").strip()
                if hostname:
                    break

        devices.append(
            NetworkDeviceScan(
                scan_id=scan_id,
                scanned_at=scanned_at,
                ip=ip,
                status=status or "unknown",
                hostname=hostname,
                mac=mac,
                vendor=vendor,
                services=_parse_xml_ports(host),
            )
        )
    return sorted(devices, key=lambda record: record.ip)


def _parse_xml_ports(host) -> list[NetworkService]:
    services: list[NetworkService] = []
    ports = host.find("ports")
    if ports is None:
        return services
    for port_node in ports.findall("port"):
        state = port_node.find("state")
        if state is None or state.get("state") != "open":
            continue
        port_id = port_node.get("portid", "")
        if not port_id.isdigit():
            continue
        service = port_node.find("service")
        services.append(
            NetworkService(
                port=int(port_id),
                protocol=port_node.get("protocol", "tcp"),
                service=service.get("name", "") if service is not None else "",
            )
        )
    return services


async def _scan_with_ping(
    scan_id: str,
    scanned_at: float,
    targets: list[str],
    *,
    timeout_s: int,
) -> tuple[NetworkInventoryScanSummary, list[NetworkDeviceScan]]:
    ips = list(_expand_ping_targets(targets))
    if not ips:
        return (
            NetworkInventoryScanSummary(
                scan_id=scan_id,
                scanned_at=scanned_at,
                targets=targets,
                devices_seen=0,
                scanner="ping",
                error="no pingable targets",
            ),
            [],
        )
    deadline = time.monotonic() + timeout_s
    sem = asyncio.Semaphore(32)

    async def ping(ip: str) -> NetworkDeviceScan | None:
        async with sem:
            remaining = max(1, int(deadline - time.monotonic()))
            rc, _, _ = await cli.run_cmd(["ping", "-c", "1", "-W", "1", ip], remaining)
            if rc == 0:
                return NetworkDeviceScan(
                    scan_id=scan_id,
                    scanned_at=scanned_at,
                    ip=ip,
                    status="up",
                )
            return None

    results = await asyncio.gather(*(ping(ip) for ip in ips))
    devices = [item for item in results if item is not None]
    return (
        NetworkInventoryScanSummary(
            scan_id=scan_id,
            scanned_at=scanned_at,
            targets=targets,
            devices_seen=len(devices),
            scanner="ping",
        ),
        devices,
    )


def _expand_ping_targets(targets: list[str]) -> list[str]:
    ips: list[str] = []
    for target in targets:
        if "/" not in target:
            ips.append(target)
            continue
        network = ipaddress.ip_network(target, strict=False)
        hosts = list(network.hosts())
        if len(hosts) > 512:
            hosts = hosts[:512]
        ips.extend(str(host) for host in hosts)
    return ips
