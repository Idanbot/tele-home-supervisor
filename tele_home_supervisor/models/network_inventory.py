"""Network inventory scan records."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class NetworkService:
    """Open service observed on a host during a network scan."""

    port: int
    protocol: str = "tcp"
    service: str = ""


@dataclass
class NetworkDeviceScan:
    """One observed scan result for a single network device."""

    scan_id: str
    scanned_at: float
    ip: str
    status: str = "up"
    hostname: str = ""
    mac: str = ""
    vendor: str = ""
    services: list[NetworkService] = field(default_factory=list)


@dataclass
class NetworkInventoryScanSummary:
    """Summary of one inventory scan execution."""

    scan_id: str
    scanned_at: float
    targets: list[str]
    devices_seen: int
    new_devices: list[str] = field(default_factory=list)
    missing_devices: list[str] = field(default_factory=list)
    scanner: str = ""
    error: str = ""
