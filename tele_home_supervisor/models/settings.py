"""Configuration dataclass."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Set


@dataclass
class Settings:
    """Configuration settings for tele_home_supervisor."""

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
    BOT_AUTH_TOTP_SECRET: str | None
    BOT_AUTH_TTL_HOURS: float
    BOT_AUTO_DELETE_MEDIA_HOURS: float
    ALERT_PING_LAN_TARGETS: List[str]
    ALERT_PING_WAN_TARGETS: List[str]

    # TMDB
    TMDB_API_KEY: str
    TMDB_BASE_URL: str
    TMDB_USER_AGENT: str

    # PirateBay / TPB
    TPB_BASE_URL: str
    TPB_API_BASE_URL: str
    TPB_API_BASE_URLS: List[str]
    TPB_USER_AGENT: str
    TPB_COOKIE: str
    TPB_REFERER: str
