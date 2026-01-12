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
    ALERT_PING_LAN_TARGETS: List[str]
    ALERT_PING_WAN_TARGETS: List[str]
