"""qBittorrent integration helpers.

This module reads connection configuration from the environment once at
import time and exposes a small `TorrentManager` wrapper used by the bot
handlers. Environment variables:

- `QBT_HOST` (default: `qbittorrent`)
- `QBT_PORT` (default: `8080`)
- `QBT_USER` (default: `admin`)
- `QBT_PASS` (default: `adminadmin`)

The class performs lazy connection (the `connect` method builds the
`qbittorrentapi.Client` and logs in). Returned strings are safe to send
as plain text or HTML (this module uses `html.escape` before returning
content).
"""
from __future__ import annotations

import html
import logging
import os
from typing import Optional

try:
    import qbittorrentapi
except Exception:  # pragma: no cover - import-time fallbacks
    qbittorrentapi = None  # type: ignore

logger = logging.getLogger(__name__)

# Load environment once at module import (treat empty/blank values as unset)
def _env_or_default(key: str, default: str) -> str:
    v = os.environ.get(key)
    if v is None:
        return default
    v = v.strip()
    return v if len(v) >= 1 else default

QBT_HOST: str = _env_or_default("QBT_HOST", "qbittorrent")
_qbt_port_raw: str = _env_or_default("QBT_PORT", "8080")
try:
    _port = int(_qbt_port_raw)
except Exception:
    _port = 8080
QBT_PORT: int = _port
QBT_USER: str = _env_or_default("QBT_USER", "admin")
QBT_PASS: str = _env_or_default("QBT_PASS", "adminadmin")


class TorrentManager:
    """Minimal wrapper around `qbittorrentapi.Client`.

    The manager is intentionally small: create an instance, call
    `connect()` and then use `add_magnet` / `get_status`.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        self.host = host or QBT_HOST
        self.port = port or QBT_PORT
        self.username = username or QBT_USER
        self.password = password or QBT_PASS

        self._base_url = f"http://{self.host}:{self.port}"
        self.qbt_client: Optional["qbittorrentapi.Client"] = None

    def connect(self) -> bool:
        """Build the client and log in to the WebUI.

        Returns True on success, False otherwise.
        """
        if qbittorrentapi is None:
            logger.error("qbittorrentapi package is not installed")
            return False

        try:
            self.qbt_client = qbittorrentapi.Client(host=self._base_url, username=self.username, password=self.password)
            self.qbt_client.auth_log_in()
            # Accessing app.version can raise in some client states; guard it
            try:
                ver = getattr(self.qbt_client.app, "version", None)
                logger.info("Connected to qBittorrent: %s", ver)
            except Exception:
                logger.info("Connected to qBittorrent (version unknown)")
            return True
        except qbittorrentapi.LoginFailed:  # type: ignore
            logger.warning("Invalid qBittorrent login credentials")
            return False
        except Exception as exc:  # pragma: no cover - surface errors
            logger.exception("Connection error to qBittorrent: %s", exc)
            return False

    def add_magnet(self, magnet_link: str, save_path: str = "/downloads") -> str:
        """Add a magnet link to qBittorrent.

        The `save_path` must be valid inside the qBittorrent container.
        """
        if self.qbt_client is None:
            ok = self.connect()
            if not ok:
                return "Failed to connect to qBittorrent."

        try:
            # torrents_add accepts urls (magnet) and save_path
            self.qbt_client.torrents_add(urls=magnet_link, save_path=save_path)
            return "Torrent added successfully."
        except Exception as exc:
            logger.exception("Failed to add torrent: %s", exc)
            return f"Failed to add torrent: {html.escape(str(exc))}"

    def get_status(self) -> str:
        """Return a formatted HTML-safe status of torrents.

        Returns a short multi-line report or an error string.
        """
        if self.qbt_client is None:
            ok = self.connect()
            if not ok:
                return "Failed to connect to qBittorrent."

        try:
            torrents = self.qbt_client.torrents_info()
            if not torrents:
                return "No active torrents found."

            parts: list[str] = []
            for t in torrents:
                name = html.escape(getattr(t, "name", "<unknown>"))
                state = html.escape(str(getattr(t, "state", "unknown")))
                progress = (getattr(t, "progress", 0.0) or 0.0) * 100.0
                dlspeed = (getattr(t, "dlspeed", 0) or 0) / 1024.0
                parts.append(
                    f"<b>{name}</b><br/>"
                    f"&nbsp;&nbsp;Status: {state}<br/>"
                    f"&nbsp;&nbsp;Progress: {progress:.1f}%<br/>"
                    f"&nbsp;&nbsp;Speed: {dlspeed:.1f} KiB/s"
                )
            return "<br/><br/>".join(parts)
        except Exception as exc:
            logger.exception("Error retrieving qBittorrent status: %s", exc)
            return f"Error retrieving status: {html.escape(str(exc))}"
