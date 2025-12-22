"""Command specification dataclass and types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Group = Literal[
    "System",
    "Docker",
    "Network",
    "Torrents",
    "Notifications",
    "Media",
    "AI",
    "Info",
]
Needs = Literal["none", "container", "torrent"]


@dataclass(frozen=True)
class CommandSpec:
    name: str
    group: Group
    usage: str
    description: str
    handler: str
    aliases: tuple[str, ...] = ()
    needs: Needs = "none"
