"""Central configuration for tele_home_supervisor."""

from __future__ import annotations

import logging
import os
from typing import Set, List

from .models.settings import Settings

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


def _read_optional_int(name: str) -> int | None:
    value = (os.environ.get(name) or "").strip()
    if not value:
        return None
    return int(value) if value.isdigit() else None


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


def _split_csv(s: str) -> List[str]:
    """Parse comma-separated string into a list of values."""
    return [p.strip() for p in (s or "").split(",") if p.strip()]


def _read_settings() -> Settings:
    """Read all configuration from environment variables.

    Returns:
        Settings object with all configuration values.

    Note:
        Invalid numeric values fall back to sensible defaults.
        Boolean values accept: 1/true/yes (case-insensitive) as True.
    """
    token = os.environ.get("BOT_TOKEN") or None
    owner_id = _read_optional_int("OWNER_ID")
    allowed = _split_ints(os.environ.get("ALLOWED_CHAT_IDS", ""))
    blocked = _split_ints(os.environ.get("BLOCKED_IDS", ""))
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
    bot_auth_totp_secret = os.environ.get("BOT_AUTH_TOTP_SECRET") or None
    try:
        bot_auth_ttl_hours = float(os.environ.get("BOT_AUTH_TTL_HOURS", "168") or "168")
    except Exception:
        bot_auth_ttl_hours = 168.0
    try:
        bot_auto_delete_media_hours = float(
            os.environ.get("BOT_AUTO_DELETE_MEDIA_HOURS", "24") or "24"
        )
    except Exception:
        bot_auto_delete_media_hours = 24.0
    alert_ping_lan = _split_csv(os.environ.get("ALERT_PING_LAN_TARGETS", ""))
    alert_ping_wan = _split_csv(os.environ.get("ALERT_PING_WAN_TARGETS", ""))

    # TMDB
    tmdb_api_key = os.environ.get("TMDB_API_KEY", "")
    tmdb_base_url = os.environ.get(
        "TMDB_BASE_URL", "https://api.themoviedb.org/3"
    ).rstrip("/")
    tmdb_user_agent = os.environ.get(
        "TMDB_USER_AGENT",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )

    # PirateBay / TPB
    tpb_base_url = os.environ.get("TPB_BASE_URL", "https://thepiratebay.org").rstrip(
        "/"
    )
    tpb_api_base_url = os.environ.get("TPB_API_BASE_URL", "https://apibay.org").rstrip(
        "/"
    )
    tpb_api_base_urls = _split_csv(os.environ.get("TPB_API_BASE_URLS", ""))
    tpb_user_agent = os.environ.get(
        "TPB_USER_AGENT",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )
    tpb_cookie = os.environ.get("TPB_COOKIE", "")
    tpb_referer = os.environ.get("TPB_REFERER", "")

    return Settings(
        BOT_TOKEN=token,
        OWNER_ID=owner_id,
        ALLOWED_CHAT_IDS=allowed,
        BLOCKED_IDS=blocked,
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
        BOT_AUTH_TOTP_SECRET=bot_auth_totp_secret,
        BOT_AUTH_TTL_HOURS=bot_auth_ttl_hours,
        BOT_AUTO_DELETE_MEDIA_HOURS=bot_auto_delete_media_hours,
        ALERT_PING_LAN_TARGETS=alert_ping_lan,
        ALERT_PING_WAN_TARGETS=alert_ping_wan,
        TMDB_API_KEY=tmdb_api_key,
        TMDB_BASE_URL=tmdb_base_url,
        TMDB_USER_AGENT=tmdb_user_agent,
        TPB_BASE_URL=tpb_base_url,
        TPB_API_BASE_URL=tpb_api_base_url,
        TPB_API_BASE_URLS=tpb_api_base_urls,
        TPB_USER_AGENT=tpb_user_agent,
        TPB_COOKIE=tpb_cookie,
        TPB_REFERER=tpb_referer,
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
    if settings.BOT_AUTH_TOTP_SECRET is None:
        logger.warning("BOT_AUTH_TOTP_SECRET is not set; /auth will be unavailable.")


# Exported constants
TOKEN: str | None = settings.BOT_TOKEN
OWNER_ID: int | None = settings.OWNER_ID
ALLOWED: set[int] = settings.ALLOWED_CHAT_IDS
BLOCKED_IDS: set[int] = settings.BLOCKED_IDS
RATE_LIMIT_S: float = settings.RATE_LIMIT_S
SHOW_WAN: bool = settings.SHOW_WAN
WATCH_PATHS: list[str] = settings.WATCH_PATHS
OLLAMA_HOST: str = settings.OLLAMA_HOST
OLLAMA_MODEL: str = settings.OLLAMA_MODEL
QBT_TIMEOUT_S: float = settings.QBT_TIMEOUT_S
BOT_AUTH_TOTP_SECRET: str | None = settings.BOT_AUTH_TOTP_SECRET
BOT_AUTH_TTL_HOURS: float = settings.BOT_AUTH_TTL_HOURS
BOT_AUTO_DELETE_MEDIA_HOURS: float = settings.BOT_AUTO_DELETE_MEDIA_HOURS
ALERT_PING_LAN_TARGETS: list[str] = settings.ALERT_PING_LAN_TARGETS
ALERT_PING_WAN_TARGETS: list[str] = settings.ALERT_PING_WAN_TARGETS

validate_settings()
