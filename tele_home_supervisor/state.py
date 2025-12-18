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

    # Scheduled notifications mute state (chat_id -> muted)
    epic_games_muted: set[int] = field(default_factory=set)
    hackernews_muted: set[int] = field(default_factory=set)

    _state_file: Path = field(default_factory=lambda: Path("/app/data/bot_state.json"))

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

    def toggle_epic_games_mute(self, chat_id: int) -> bool:
        """Toggle Epic Games notifications. Returns True if now muted."""
        if chat_id in self.epic_games_muted:
            self.epic_games_muted.discard(chat_id)
            self._save_state()
            return False
        self.epic_games_muted.add(chat_id)
        self._save_state()
        return True

    def is_epic_games_muted(self, chat_id: int) -> bool:
        return chat_id in self.epic_games_muted

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
                "epic_games_muted": list(self.epic_games_muted),
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
            self.epic_games_muted = set(data.get("epic_games_muted", []))
            self.hackernews_muted = set(data.get("hackernews_muted", []))
            self.torrent_completion_subscribers = set(
                data.get("torrent_completion_subscribers", [])
            )
            logger.info("Loaded bot state from %s", self._state_file)
        except Exception:
            logger.exception("Failed to load bot state")


BOT_STATE_KEY = "state"
