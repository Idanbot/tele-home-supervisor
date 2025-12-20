"""Central configuration for tele_home_supervisor."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Set, List

logger = logging.getLogger(__name__)


def _split_ints(s: str) -> Set[int]:
    """Parse comma-separated string into a set of integers.

    Args:
        s: Comma-separated string of integers (e.g., "123,456,789")

    Returns:
        Set of parsed integers. Invalid entries are silently skipped.

    Example:
        >>> _split_ints("123,456,invalid,789")
        {123, 456, 789}
    """
    out = set()
    for part in (s or "").split(","):
        p = part.strip()
        if p.isdigit():
            out.add(int(p))
    return out


def _split_paths(s: str) -> List[str]:
    """Parse comma-separated string into a list of filesystem paths.

    Args:
        s: Comma-separated string of paths. Defaults to "/,/srv/media" if empty.

    Returns:
        List of non-empty path strings.

    Example:
        >>> _split_paths("/home,/var/log")
        ['/home', '/var/log']
    """
    return [p.strip() for p in (s or "/,/srv/media").split(",") if p.strip()]


@dataclass
class Settings:
    """Configuration settings for tele_home_supervisor.

    All settings are loaded from environment variables with sensible defaults.
    """

    BOT_TOKEN: str | None
    ALLOWED_CHAT_IDS: Set[int]
    RATE_LIMIT_S: float
    SHOW_WAN: bool
    WATCH_PATHS: List[str]
    QBT_HOST: str
    QBT_PORT: int
    QBT_USER: str
    QBT_PASS: str
    QBT_TIMEOUT_S: float
    OLLAMA_HOST: str
    OLLAMA_MODEL: str
    BOT_AUTH_SECRET: str | None


def _read_settings() -> Settings:
    """Read all configuration from environment variables.

    Returns:
        Settings object with all configuration values.

    Note:
        Invalid numeric values fall back to sensible defaults.
        Boolean values accept: 1/true/yes (case-insensitive) as True.
    """
    token = os.environ.get("BOT_TOKEN") or None
    allowed = _split_ints(os.environ.get("ALLOWED_CHAT_IDS", ""))
    try:
        rate_limit = float(os.environ.get("RATE_LIMIT_S", "1.0") or "1.0")
    except Exception:
        rate_limit = 1.0
    show_wan = os.environ.get("SHOW_WAN", "false").lower() in {"1", "true", "yes"}
    watch_paths = _split_paths(os.environ.get("WATCH_PATHS", "/,/srv/media"))

    # qBittorrent
    qbt_host = os.environ.get("QBT_HOST") or "qbittorrent"
    qbt_port_raw = (os.environ.get("QBT_PORT") or "8080").strip()
    try:
        qbt_port = int(qbt_port_raw) if qbt_port_raw else 8080
    except Exception:
        qbt_port = 8080
    qbt_user = os.environ.get("QBT_USER") or "admin"
    qbt_pass = os.environ.get("QBT_PASS") or "adminadmin"
    try:
        qbt_timeout = float(os.environ.get("QBT_TIMEOUT_S", "8") or "8")
    except Exception:
        qbt_timeout = 8.0

    # Ollama
    ollama_host = os.environ.get("OLLAMA_HOST") or "http://localhost:11434"
    ollama_model = os.environ.get("OLLAMA_MODEL") or "llama2"
    bot_auth_secret = os.environ.get("BOT_AUTH_SECRET") or None

    return Settings(
        BOT_TOKEN=token,
        ALLOWED_CHAT_IDS=allowed,
        RATE_LIMIT_S=rate_limit,
        SHOW_WAN=show_wan,
        WATCH_PATHS=watch_paths,
        QBT_HOST=qbt_host,
        QBT_PORT=qbt_port,
        QBT_USER=qbt_user,
        QBT_PASS=qbt_pass,
        QBT_TIMEOUT_S=qbt_timeout,
        OLLAMA_HOST=ollama_host,
        OLLAMA_MODEL=ollama_model,
        BOT_AUTH_SECRET=bot_auth_secret,
    )


settings = _read_settings()


def validate_settings() -> None:
    """Validate critical configuration and log warnings for issues.

    This function checks BOT_TOKEN and ALLOWED_CHAT_IDS, logging appropriate
    error/warning messages if they are not configured correctly.
    """
    if settings.BOT_TOKEN is None:
        logger.error("BOT_TOKEN environment variable is not set")
    if not settings.ALLOWED_CHAT_IDS:
        logger.warning(
            "ALLOWED_CHAT_IDS is empty; guarded commands will be unauthorized."
        )
    if settings.BOT_AUTH_SECRET is None:
        logger.warning("BOT_AUTH_SECRET is not set; /auth will be unavailable.")


# Exported constants
TOKEN: str | None = settings.BOT_TOKEN
ALLOWED: set[int] = settings.ALLOWED_CHAT_IDS
RATE_LIMIT_S: float = settings.RATE_LIMIT_S
SHOW_WAN: bool = settings.SHOW_WAN
WATCH_PATHS: list[str] = settings.WATCH_PATHS
OLLAMA_HOST: str = settings.OLLAMA_HOST
OLLAMA_MODEL: str = settings.OLLAMA_MODEL
QBT_TIMEOUT_S: float = settings.QBT_TIMEOUT_S
BOT_AUTH_SECRET: str | None = settings.BOT_AUTH_SECRET

validate_settings()
