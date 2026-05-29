from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class MagnetEntry:
    name: str
    magnet: str
    seeders: int = 0
    leechers: int = 0
