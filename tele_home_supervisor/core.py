"""Core configuration constants used by the bot."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .config import settings

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Global rate limit (seconds) for all commands.
RATE_LIMIT_S: float = settings.RATE_LIMIT_S

# Token used by `main.build_application` to construct the Application
TOKEN: str | None = settings.BOT_TOKEN

# Allowed chat ids (may be empty)
ALLOWED: set[int] = set(settings.ALLOWED_CHAT_IDS)

if not ALLOWED:
    logger.warning("ALLOWED_CHAT_IDS is empty; guarded commands will be unauthorized.")

# Feature flags / config used by handlers
SHOW_WAN = settings.SHOW_WAN
WATCH_PATHS = list(settings.WATCH_PATHS)


def _validate_config() -> None:
    if TOKEN is None:
        logger.error("BOT_TOKEN environment variable is not set (from config.settings)")
    if not ALLOWED:
        logger.warning("ALLOWED_CHAT_IDS is empty; all guarded commands will be unauthorized")
    if not WATCH_PATHS:
        logger.warning("WATCH_PATHS is empty; disk usage monitoring disabled")


_validate_config()


__all__ = ["TOKEN", "ALLOWED", "SHOW_WAN", "WATCH_PATHS", "RATE_LIMIT_S"]
