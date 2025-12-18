"""Central configuration for tele_home_supervisor."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Set, List

logger = logging.getLogger(__name__)


def _split_ints(s: str) -> Set[int]:
    out = set()
    for part in (s or "").split(","):
        p = part.strip()
        if p.isdigit():
            out.add(int(p))
    return out


def _split_paths(s: str) -> List[str]:
    return [p.strip() for p in (s or "/,/srv/media").split(",") if p.strip()]


@dataclass
class Settings:
    BOT_TOKEN: str | None
    ALLOWED_CHAT_IDS: Set[int]
    RATE_LIMIT_S: float
    SHOW_WAN: bool
    WATCH_PATHS: List[str]
    QBT_HOST: str
    QBT_PORT: int
    QBT_USER: str
    QBT_PASS: str
    OLLAMA_HOST: str
    OLLAMA_MODEL: str


def _read_settings() -> Settings:
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

    # Ollama
    ollama_host = os.environ.get("OLLAMA_HOST") or "http://localhost:11434"
    ollama_model = os.environ.get("OLLAMA_MODEL") or "llama2"

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
        OLLAMA_HOST=ollama_host,
        OLLAMA_MODEL=ollama_model,
    )


settings = _read_settings()


def validate_settings() -> None:
    if settings.BOT_TOKEN is None:
        logger.error("BOT_TOKEN environment variable is not set")
    if not settings.ALLOWED_CHAT_IDS:
        logger.warning(
            "ALLOWED_CHAT_IDS is empty; guarded commands will be unauthorized."
        )


# Exported constants
TOKEN: str | None = settings.BOT_TOKEN
ALLOWED: set[int] = settings.ALLOWED_CHAT_IDS
RATE_LIMIT_S: float = settings.RATE_LIMIT_S
SHOW_WAN: bool = settings.SHOW_WAN
WATCH_PATHS: list[str] = settings.WATCH_PATHS
OLLAMA_HOST: str = settings.OLLAMA_HOST
OLLAMA_MODEL: str = settings.OLLAMA_MODEL

validate_settings()
