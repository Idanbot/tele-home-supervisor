"""Bot runtime state (caches, subscriptions, background tasks)."""

from __future__ import annotations

import json
import logging
import secrets
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

from .. import services
from .cache import CacheEntry, LogCacheEntry
from .debug import DebugEntry, DebugRecorder
from .metrics import CommandMetrics
from .tmdb_cache import TmdbCacheEntry

logger = logging.getLogger(__name__)

MAX_LATENCY_SAMPLES = 200
_MAGNET_CACHE_TTL_S = 30 * 60
_MAGNET_CACHE_MAX = 200
_LOG_CACHE_TTL_S = 5 * 60
_DEBUG_TTL_S = 60 * 60
_DEBUG_MAX_PER_CMD = 50
_TMDB_CACHE_TTL_S = 15 * 60
_TMDB_CACHE_MAX = 200


def _normalize(items: set[str]) -> set[str]:
    """Normalize a set of strings by trimming whitespace and removing empty values."""
    return {i.strip() for i in items if i and i.strip()}


@dataclass
class BotState:
    """Runtime state for the bot including caches, subscriptions, and background tasks."""

    cache_ttl_s: float = 60.0
    caches: dict[str, CacheEntry] = field(default_factory=dict)

    torrent_completion_subscribers: set[int] = field(default_factory=set)
    tasks: dict[str, object] = field(default_factory=dict)

    # Scheduled notifications mute state (chat_id -> muted)
    gameoffers_muted: set[int] = field(default_factory=set)
    hackernews_muted: set[int] = field(default_factory=set)

    # Auth grants (user_id -> monotonic expiry timestamp)
    auth_grants: dict[int, float] = field(default_factory=dict)

    command_metrics: dict[str, CommandMetrics] = field(default_factory=dict)

    magnet_cache: OrderedDict[str, tuple[float, str, str]] = field(
        default_factory=OrderedDict
    )
    log_cache: dict[str, LogCacheEntry] = field(default_factory=dict)
    debug_cache: dict[str, list[DebugEntry]] = field(default_factory=dict)
    tmdb_cache: OrderedDict[str, TmdbCacheEntry] = field(default_factory=OrderedDict)

    _state_file: Path = field(default_factory=lambda: Path("/app/data/bot_state.json"))
    _debug_recorder: DebugRecorder | None = field(default=None, init=False, repr=False)

    async def refresh_containers(self) -> set[str]:
        """Refresh the cache of Docker container names."""
        names = _normalize(await services.container_names())
        self.caches["containers"] = CacheEntry(updated_at=time.monotonic(), items=names)
        return set(names)

    async def refresh_torrents(self) -> set[str]:
        """Refresh the cache of torrent names."""
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
        """Get suggestions from cached items based on a query string."""
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

    def get_log_cache(self, container: str) -> list[str] | None:
        entry = self.log_cache.get(container)
        if not entry:
            return None
        if (time.monotonic() - entry.updated_at) > _LOG_CACHE_TTL_S:
            self.log_cache.pop(container, None)
            return None
        return entry.lines

    def set_log_cache(self, container: str, lines: list[str]) -> None:
        self.log_cache[container] = LogCacheEntry(
            updated_at=time.monotonic(), lines=lines
        )

    def _prune_debug(self, command: str) -> None:
        entries = self.debug_cache.get(command, [])
        if not entries:
            return
        cutoff = time.time() - _DEBUG_TTL_S
        kept = [entry for entry in entries if entry.timestamp >= cutoff]
        if kept:
            self.debug_cache[command] = kept[-_DEBUG_MAX_PER_CMD:]
        else:
            self.debug_cache.pop(command, None)

    def add_debug(self, command: str, message: str, details: str | None = None) -> None:
        if not command:
            return
        self._prune_debug(command)
        entry = DebugEntry(timestamp=time.time(), message=message, details=details)
        self.debug_cache.setdefault(command, []).append(entry)
        self.debug_cache[command] = self.debug_cache[command][-_DEBUG_MAX_PER_CMD:]

    def get_debug(self, command: str | None = None) -> dict[str, list[DebugEntry]]:
        if command:
            self._prune_debug(command)
            entries = list(self.debug_cache.get(command, []))
            return {command: entries} if entries else {}
        for key in list(self.debug_cache.keys()):
            self._prune_debug(key)
        return {
            key: list(entries) for key, entries in self.debug_cache.items() if entries
        }

    def debug_recorder(self) -> DebugRecorder:
        if self._debug_recorder is None:
            self._debug_recorder = DebugRecorder(self)
        return self._debug_recorder

    def store_tmdb_results(
        self,
        key: str,
        kind: str,
        query: str | None,
        page: int,
        total_pages: int,
        items: list[dict[str, object]],
    ) -> None:
        entry = TmdbCacheEntry(
            updated_at=time.monotonic(),
            kind=kind,
            query=query,
            page=page,
            total_pages=total_pages,
            items=items,
        )
        self.tmdb_cache[key] = entry
        self._prune_tmdb_cache()

    def get_tmdb_results(self, key: str) -> TmdbCacheEntry | None:
        entry = self.tmdb_cache.get(key)
        if not entry:
            return None
        if (time.monotonic() - entry.updated_at) > _TMDB_CACHE_TTL_S:
            self.tmdb_cache.pop(key, None)
            return None
        return entry

    def new_tmdb_key(self) -> str:
        return secrets.token_urlsafe(8)

    def _prune_tmdb_cache(self) -> None:
        if not self.tmdb_cache:
            return
        now = time.monotonic()
        stale_keys = [
            key
            for key, entry in self.tmdb_cache.items()
            if (now - entry.updated_at) > _TMDB_CACHE_TTL_S
        ]
        for key in stale_keys:
            self.tmdb_cache.pop(key, None)
        while len(self.tmdb_cache) > _TMDB_CACHE_MAX:
            self.tmdb_cache.popitem(last=False)

    def metrics_for(self, name: str) -> CommandMetrics:
        return self.command_metrics.setdefault(name, CommandMetrics())

    def record_command(
        self, name: str, latency_s: float, ok: bool, error_msg: str | None
    ) -> None:
        metrics = self.metrics_for(name)
        metrics.count += 1
        metrics.last_run_ts = time.time()
        if ok:
            metrics.success += 1
        else:
            metrics.error += 1
            metrics.last_error = error_msg
        metrics.total_latency_s += latency_s
        metrics.max_latency_s = max(metrics.max_latency_s, latency_s)
        metrics.latencies_s.append(latency_s)
        if len(metrics.latencies_s) > MAX_LATENCY_SAMPLES:
            metrics.latencies_s.pop(0)

    def record_rate_limited(self, name: str) -> None:
        metrics = self.metrics_for(name)
        metrics.rate_limited += 1

    def store_magnet(self, name: str, magnet: str) -> str:
        key = secrets.token_urlsafe(8)
        self.magnet_cache[key] = (time.monotonic(), name, magnet)
        self._prune_magnets()
        return key

    def get_magnet(self, key: str) -> tuple[str, str] | None:
        self._prune_magnets()
        entry = self.magnet_cache.get(key)
        if not entry:
            return None
        ts, name, magnet = entry
        if (time.monotonic() - ts) > _MAGNET_CACHE_TTL_S:
            self.magnet_cache.pop(key, None)
            return None
        return name, magnet

    def _prune_magnets(self) -> None:
        if not self.magnet_cache:
            return
        now = time.monotonic()
        stale_keys = [
            key
            for key, (ts, _, _) in self.magnet_cache.items()
            if (now - ts) > _MAGNET_CACHE_TTL_S
        ]
        for key in stale_keys:
            self.magnet_cache.pop(key, None)
        while len(self.magnet_cache) > _MAGNET_CACHE_MAX:
            self.magnet_cache.popitem(last=False)

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
