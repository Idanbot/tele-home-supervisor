"""Torrent snapshot dataclass used by background tasks."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TorrentSnapshot:
    torrent_hash: str
    name: str
    is_complete: bool
    total_size: int
    downloaded: int
