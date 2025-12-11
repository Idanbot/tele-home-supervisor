"""Core configuration and thin Telegram handler wrappers.

This module exposes configuration constants (used by `main`) and a set of
thin wrappers that delegate to the real implementations in
`tele_home_supervisor.api_functions` to avoid circular imports.
"""
from __future__ import annotations

import os
import logging
import time
import threading
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)

# Global rate limit (seconds) for all commands. Default 1s.
RATE_LIMIT_S: float = float(os.environ.get("RATE_LIMIT_S", "1.0"))
_last_command_ts = 0.0
_rate_lock = threading.Lock()

# Token used by `main.build_application` to construct the Application
TOKEN: str | None = os.environ.get("BOT_TOKEN")

ALLOWED: set[int] = set()
for part in os.environ.get("ALLOWED_CHAT_IDS", "").replace(" ", "").split(","):
    if part.isdigit():
        ALLOWED.add(int(part))

if not ALLOWED:
    logger.warning("ALLOWED_CHAT_IDS is empty; guarded commands will be unauthorized.")

# Feature flags / config used by handlers
SHOW_WAN = os.environ.get("SHOW_WAN", "false").lower() in {"1", "true", "yes"}
WATCH_PATHS = [p.strip() for p in os.environ.get("WATCH_PATHS", "/,/srv/media").split(",") if p.strip()]


def _validate_config() -> None:
    """Validate configuration at module load and log warnings/errors."""
    if TOKEN is None:
        logger.error("BOT_TOKEN environment variable is not set")
    if not ALLOWED:
        logger.warning("ALLOWED_CHAT_IDS is empty; all guarded commands will be unauthorized")
    if not WATCH_PATHS:
        logger.warning("WATCH_PATHS is empty; disk usage monitoring disabled")


_validate_config()


def _delegate(name: str) -> Callable[["telegram.Update", "telegram.ext.ContextTypes.DEFAULT_TYPE"], Awaitable[None]]:
    """Return a thin wrapper that imports and returns the named callable.

    The return type matches the expected telegram handler signature so
    type-checkers (Pylance/pyright) understand the API without using Any.
    """

    async def wrapper(update, context):
        # Global rate limiting: allow at most one command per RATE_LIMIT_S seconds
        try:
            now = time.monotonic()
            with _rate_lock:
                global _last_command_ts
                elapsed = now - _last_command_ts
                if elapsed < RATE_LIMIT_S:
                    # Send a short rate-limit notice and skip executing the command
                    try:
                        if update and getattr(update, "effective_message", None):
                            await update.effective_message.reply_text(
                                f"⏱ Rate limit: please wait {RATE_LIMIT_S - elapsed:.1f}s",
                            )
                    except Exception:
                        # best-effort notify; ignore any errors
                        pass
                    return
                _last_command_ts = now
        except Exception:
            # If rate-limiter itself fails, do not block command execution
            pass
        mod = __import__("tele_home_supervisor.api_functions", fromlist=[name])
        func = getattr(mod, name)
        return await func(update, context)

    return wrapper


# Export handler callables (these are thin wrappers that import the real
# implementation lazily).
cmd_start = _delegate("cmd_start")
cmd_help = _delegate("cmd_help")
cmd_ip = _delegate("cmd_ip")
cmd_health = _delegate("cmd_health")
cmd_docker = _delegate("cmd_docker")
cmd_dockerstats = _delegate("cmd_dockerstats")
cmd_whoami = _delegate("cmd_whoami")
cmd_logs = _delegate("cmd_logs")
cmd_uptime = _delegate("cmd_uptime")
cmd_version = _delegate("cmd_version")
cmd_dstats_rich = _delegate("cmd_dstats_rich")
cmd_dhealth = _delegate("cmd_dhealth")
cmd_ping = _delegate("cmd_ping")
cmd_temp = _delegate("cmd_temp")
cmd_torrent_add = _delegate("cmd_torrent_add")
cmd_torrent_status = _delegate("cmd_torrent_status")

__all__ = [
    "TOKEN",
    "ALLOWED",
    "SHOW_WAN",
    "WATCH_PATHS",
    "cmd_start",
    "cmd_help",
    "cmd_ip",
    "cmd_health",
    "cmd_docker",
    "cmd_dockerstats",
    "cmd_dstats_rich",
    "cmd_dhealth",
    "cmd_ping",
    "cmd_torrent_add",
    "cmd_torrent_status",
    "cmd_temp",
    "cmd_whoami",
    "cmd_logs",
    "cmd_uptime",
    "cmd_version",
]
