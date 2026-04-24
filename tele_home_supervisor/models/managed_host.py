"""Managed remote host/device configuration."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ManagedHost:
    """Named remote host/device that the bot can manage."""

    name: str
    ping_host: str = ""
    mac: str = ""
    wol_broadcast_ip: str = ""
    wol_port: int = 9
    ssh_target: str = ""
    ssh_port: int = 22
    shutdown_command: str = ""
    ssh_password: str = ""
    ssh_password_env: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)

    def matches(self, token: str) -> bool:
        """Return True if *token* selects this host by name or alias."""
        needle = (token or "").strip().lower()
        if not needle:
            return False
        if self.name.lower() == needle:
            return True
        return any(alias.lower() == needle for alias in self.aliases)
