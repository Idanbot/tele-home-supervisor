"""Configuration dataclass."""

from __future__ import annotations

from dataclasses import dataclass

from .managed_host import ManagedHost


@dataclass
class Settings:
    """Configuration settings for tele_home_supervisor."""

    BOT_TOKEN: str | None
    OWNER_ID: int | None
    ALLOWED_CHAT_IDS: set[int]
    BLOCKED_IDS: set[int]
    RATE_LIMIT_S: float
    SHOW_WAN: bool
    WATCH_PATHS: list[str]
    QBT_HOST: str
    QBT_PORT: int
    QBT_USER: str
    QBT_PASS: str
    QBT_TIMEOUT_S: float
    QBT_BAN_DURATION_S: float
    OLLAMA_HOST: str
    OLLAMA_MODEL: str
    BOT_AUTH_TOTP_SECRET: str | None
    BOT_AUTH_TTL_HOURS: float
    BOT_AUTO_DELETE_MEDIA_HOURS: float
    ALERT_PING_LAN_TARGETS: list[str]
    ALERT_PING_WAN_TARGETS: list[str]
    WOL_TARGET_IP: str
    WOL_TARGET_MAC: str
    WOL_BROADCAST_IP: str
    WOL_PORT: int
    WOL_HELPER_IMAGE: str
    WOL_SSH_TARGET: str
    WOL_SSH_PORT: int
    WOL_SSH_PASSWORD: str
    WOL_SHUTDOWN_REMOTE_CMD: str
    WOL_VERIFY_TIMEOUT_S: float
    WOL_VERIFY_INTERVAL_S: float
    DEFAULT_MANAGED_HOST: str
    MANAGED_HOSTS: list[ManagedHost]
    NETWORK_INVENTORY_TARGETS: list[str]
    NETWORK_INVENTORY_INTERVAL_S: float
    NETWORK_INVENTORY_RETENTION_DAYS: float
    NETWORK_INVENTORY_MAX_SCANS_PER_DEVICE: int
    NETWORK_INVENTORY_SCAN_TIMEOUT_S: int
    NETWORK_INVENTORY_NMAP_ARGS: list[str]

    # TMDB
    TMDB_API_KEY: str
    TMDB_BASE_URL: str
    TMDB_USER_AGENT: str

    # PirateBay / TPB
    TPB_BASE_URL: str
    TPB_API_BASE_URL: str
    TPB_API_BASE_URLS: list[str]
    TPB_USER_AGENT: str
    TPB_COOKIE: str
    TPB_REFERER: str
