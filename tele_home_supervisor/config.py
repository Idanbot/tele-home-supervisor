"""Central configuration for tele_home_supervisor.

Simple, dependency-free settings loader. Exposes a `settings` object
with typed attributes and basic validation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Set, List


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
    )


settings = _read_settings()


def validate_settings() -> None:
    if settings.BOT_TOKEN is None:
        # caller will decide whether this is fatal; we still expose the value
        return
    # Additional validations can be added here
    return
