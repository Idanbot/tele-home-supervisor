"""Core configuration and thin Telegram handler wrappers.

This module exposes configuration constants (used by `main`) and a set of
thin wrappers that delegate to the real implementations in
`tele_home_supervisor.api_functions` to avoid circular imports.
"""
from __future__ import annotations

import os
import logging
from typing import Any

logger = logging.getLogger(__name__)

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


def _delegate(name: str) -> Any:
    """Return a thin wrapper that imports and returns the named callable.

    Used by the telegram registration to avoid importing the full
    `api_functions` module at import time.
    """

    async def wrapper(update, context):
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
    "cmd_whoami",
]
