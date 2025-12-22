"""TMDB cache dataclass."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TmdbCacheEntry:
    updated_at: float
    kind: str
    query: str | None
    page: int
    total_pages: int
    items: list[dict[str, object]]
