"""Bot runtime state (caches, subscriptions, background tasks)."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import services


@dataclass
class CacheEntry:
    updated_at: float
    items: set[str]


def _normalize(items: set[str]) -> set[str]:
    return {i.strip() for i in items if i and i.strip()}


@dataclass
class BotState:
    cache_ttl_s: float = 60.0
    caches: dict[str, CacheEntry] = field(default_factory=dict)

    torrent_completion_subscribers: set[int] = field(default_factory=set)
    tasks: dict[str, object] = field(default_factory=dict)

    def refresh_containers(self) -> set[str]:
        names = _normalize(services.container_names())
        self.caches["containers"] = CacheEntry(updated_at=time.monotonic(), items=names)
        return set(names)

    def refresh_torrents(self) -> set[str]:
        names = _normalize(services.torrent_names())
        self.caches["torrents"] = CacheEntry(updated_at=time.monotonic(), items=names)
        return set(names)

    def maybe_refresh(self, key: str) -> set[str]:
        entry = self.caches.get(key)
        if entry and (time.monotonic() - entry.updated_at) < self.cache_ttl_s:
            return set(entry.items)
        if key == "containers":
            return self.refresh_containers()
        if key == "torrents":
            return self.refresh_torrents()
        return set()

    def get_cached(self, key: str) -> set[str]:
        entry = self.caches.get(key)
        return set(entry.items) if entry else set()

    def suggest(self, key: str, query: str | None = None, limit: int = 5) -> list[str]:
        items = list(self.get_cached(key))
        if not items:
            return []
        q = (query or "").strip().lower()
        if q:
            starts = [x for x in items if x.lower().startswith(q)]
            contains = [x for x in items if q in x.lower() and x not in starts]
            ranked = starts + contains
        else:
            ranked = sorted(items)
        return ranked[: max(0, limit)]

    def set_torrent_completion_subscription(self, chat_id: int, enable: bool | None) -> bool:
        if enable is None:
            enable = chat_id not in self.torrent_completion_subscribers
        if enable:
            self.torrent_completion_subscribers.add(chat_id)
            return True
        self.torrent_completion_subscribers.discard(chat_id)
        return False

    def torrent_completion_enabled(self, chat_id: int) -> bool:
        return chat_id in self.torrent_completion_subscribers


BOT_STATE_KEY = "state"

