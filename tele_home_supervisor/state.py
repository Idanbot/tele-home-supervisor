"""Bot runtime state (caches, subscriptions, background tasks)."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import services

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Cache entry with timestamp and cached items.

    Attributes:
        updated_at: Unix timestamp (monotonic) when cache was last updated
        items: Set of cached string values
    """

    updated_at: float
    items: set[str]


def _normalize(items: set[str]) -> set[str]:
    """Normalize a set of strings by trimming whitespace and removing empty values.

    Args:
        items: Set of strings to normalize

    Returns:
        Set of non-empty trimmed strings
    """
    return {i.strip() for i in items if i and i.strip()}


@dataclass
class BotState:
    """Runtime state for the bot including caches, subscriptions, and background tasks.

    Attributes:
        cache_ttl_s: Time-to-live for cached data in seconds
        caches: Dictionary of cache entries keyed by cache type
        torrent_completion_subscribers: Set of chat IDs subscribed to torrent notifications
        tasks: Dictionary of background asyncio tasks
        gameoffers_muted: Set of chat IDs with game offers notifications muted
        hackernews_muted: Set of chat IDs with hacker news notifications muted
        _state_file: Path to persistent state file on disk
    """

    cache_ttl_s: float = 60.0
    caches: dict[str, CacheEntry] = field(default_factory=dict)

    torrent_completion_subscribers: set[int] = field(default_factory=set)
    tasks: dict[str, object] = field(default_factory=dict)

    # Scheduled notifications mute state (chat_id -> muted)
    gameoffers_muted: set[int] = field(default_factory=set)
    hackernews_muted: set[int] = field(default_factory=set)

    _state_file: Path = field(default_factory=lambda: Path("/app/data/bot_state.json"))

    async def refresh_containers(self) -> set[str]:
        """Refresh the cache of Docker container names.

        Returns:
            Set of current container names
        """
        names = _normalize(await services.container_names())
        self.caches["containers"] = CacheEntry(updated_at=time.monotonic(), items=names)
        return set(names)

    async def refresh_torrents(self) -> set[str]:
        """Refresh the cache of torrent names.

        Returns:
            Set of current torrent names
        """
        names = _normalize(await services.torrent_names())
        self.caches["torrents"] = CacheEntry(updated_at=time.monotonic(), items=names)
        return set(names)

    async def maybe_refresh(self, key: str) -> set[str]:
        entry = self.caches.get(key)
        if entry and (time.monotonic() - entry.updated_at) < self.cache_ttl_s:
            return set(entry.items)
        if key == "containers":
            return await self.refresh_containers()
        if key == "torrents":
            return await self.refresh_torrents()
        return set()

    def get_cached(self, key: str) -> set[str]:
        entry = self.caches.get(key)
        return set(entry.items) if entry else set()

    def suggest(self, key: str, query: str | None = None, limit: int = 5) -> list[str]:
        """Get suggestions from cached items based on a query string.

        Args:
            key: Cache key ("containers" or "torrents")
            query: Optional search query. If provided, filters by prefix/contains.
            limit: Maximum number of suggestions to return

        Returns:
            List of suggested items, ranked by relevance (prefix matches first).

        Note:
            When no query is provided, returns sorted list of all items.
        """
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

    def set_torrent_completion_subscription(
        self, chat_id: int, enable: bool | None
    ) -> bool:
        if enable is None:
            enable = chat_id not in self.torrent_completion_subscribers
        if enable:
            self.torrent_completion_subscribers.add(chat_id)
            return True
        self.torrent_completion_subscribers.discard(chat_id)
        return False

    def torrent_completion_enabled(self, chat_id: int) -> bool:
        return chat_id in self.torrent_completion_subscribers

    def toggle_gameoffers_mute(self, chat_id: int) -> bool:
        """Toggle combined Game Offers notifications. Returns True if now muted."""
        if chat_id in self.gameoffers_muted:
            self.gameoffers_muted.discard(chat_id)
            self._save_state()
            return False
        self.gameoffers_muted.add(chat_id)
        self._save_state()
        return True

    def is_gameoffers_muted(self, chat_id: int) -> bool:
        return chat_id in self.gameoffers_muted

    def toggle_hackernews_mute(self, chat_id: int) -> bool:
        """Toggle Hacker News notifications. Returns True if now muted."""
        if chat_id in self.hackernews_muted:
            self.hackernews_muted.discard(chat_id)
            self._save_state()
            return False
        self.hackernews_muted.add(chat_id)
        self._save_state()
        return True

    def is_hackernews_muted(self, chat_id: int) -> bool:
        return chat_id in self.hackernews_muted

    def _save_state(self) -> None:
        """Persist mute preferences to disk."""
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "gameoffers_muted": list(self.gameoffers_muted),
                "hackernews_muted": list(self.hackernews_muted),
                "torrent_completion_subscribers": list(
                    self.torrent_completion_subscribers
                ),
            }
            self._state_file.write_text(json.dumps(data, indent=2))
        except Exception:
            logger.exception("Failed to save bot state")

    def load_state(self) -> None:
        """Load persisted state from disk."""
        try:
            if not self._state_file.exists():
                return
            data = json.loads(self._state_file.read_text())
            # Migrate legacy epic_games_muted to gameoffers_muted if present
            legacy_epic = set(data.get("epic_games_muted", []))
            self.gameoffers_muted = set(data.get("gameoffers_muted", [])) or legacy_epic
            self.hackernews_muted = set(data.get("hackernews_muted", []))
            self.torrent_completion_subscribers = set(
                data.get("torrent_completion_subscribers", [])
            )
            logger.info("Loaded bot state from %s", self._state_file)
        except Exception:
            logger.exception("Failed to load bot state")


BOT_STATE_KEY = "state"
