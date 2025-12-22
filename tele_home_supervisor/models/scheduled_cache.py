"""Scheduled fetch cache entry."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ScheduledCacheEntry:
    value: object | None
    fetched_at: float
    error_count: int = 0
    next_retry_at: float = 0.0
    last_error: object | None = None
