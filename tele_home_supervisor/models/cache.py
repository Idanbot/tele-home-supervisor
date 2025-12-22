"""Cache-related dataclasses."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CacheEntry:
    """Cache entry with timestamp and cached items."""

    updated_at: float
    items: set[str]


@dataclass
class LogCacheEntry:
    updated_at: float
    lines: list[str]
