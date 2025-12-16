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
from typing import Optional

try:
    import qbittorrentapi
except Exception:  # pragma: no cover - import-time fallbacks
    qbittorrentapi = None  # type: ignore

from .config import settings

logger = logging.getLogger(__name__)


def fmt_bytes_compact_decimal(num_bytes: int) -> str:
    """Format bytes as a compact decimal string (e.g. 244.4MB)."""
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    value = float(max(0, num_bytes))
    unit_idx = 0
    while value >= 1000.0 and unit_idx < len(units) - 1:
        value /= 1000.0
        unit_idx += 1
    if unit_idx == 0:
        return f"{int(value)}{units[unit_idx]}"
    return f"{value:.1f}{units[unit_idx]}"


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
        self.host = host or settings.QBT_HOST
        self.port = port or settings.QBT_PORT
        self.username = username or settings.QBT_USER
        self.password = password or settings.QBT_PASS

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
            self.qbt_client = qbittorrentapi.Client(
                host=self._base_url, username=self.username, password=self.password
            )
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

    def _find_torrents(self, name_substr: str) -> list[dict]:
        """Return list of torrents matching `name_substr` (case-insensitive).

        Each item is a dict with keys: `name`, `hash`, `state`.
        """
        if self.qbt_client is None:
            if not self.connect():
                return []
        try:
            torrents = self.qbt_client.torrents_info() or []
            matches: list[dict] = []
            target = name_substr.lower()
            for t in torrents:
                tname = getattr(t, "name", "") or ""
                if target in tname.lower():
                    thash = (
                        getattr(t, "hash", None)
                        or getattr(t, "info_hash", None)
                        or getattr(t, "hashString", None)
                    )
                    matches.append(
                        {
                            "name": tname,
                            "hash": thash,
                            "state": getattr(t, "state", "unknown"),
                        }
                    )
            return matches
        except Exception:
            logger.exception("Error finding torrents by name")
            return []

    def _call_pause_resume(self, hashes: list[str], action: str) -> bool:
        """Attempt to pause or resume torrents given their hashes.

        `action` must be either 'pause' or 'resume'. Returns True on success.
        This tries a few different qbittorrentapi method signatures for
        compatibility across versions.
        """
        if not hashes:
            return False
        if self.qbt_client is None:
            if not self.connect():
                return False
        # qBittorrent Web API expects a '|' separated string for multiple hashes
        hashes_joined = "|".join(hashes)
        try:
            if action == "pause":
                # Prefer the canonical parameter name 'hashes'
                try:
                    self.qbt_client.torrents_pause(hashes=hashes_joined)  # type: ignore
                except Exception:
                    # Fallbacks for older client signatures
                    try:
                        self.qbt_client.torrents_pause(torrent_hashes=hashes_joined)  # type: ignore
                    except Exception:
                        self.qbt_client.torrents_pause(hashes)  # type: ignore
            else:
                try:
                    self.qbt_client.torrents_resume(hashes=hashes_joined)  # type: ignore
                except Exception:
                    try:
                        self.qbt_client.torrents_resume(torrent_hashes=hashes_joined)  # type: ignore
                    except Exception:
                        self.qbt_client.torrents_resume(hashes)  # type: ignore
            return True
        except Exception:
            logger.exception("Error calling pause/resume on torrents")
            return False

    def _call_delete(self, hashes: list[str], delete_files: bool) -> bool:
        """Attempt to delete torrents given their hashes."""
        if not hashes:
            return False
        if self.qbt_client is None:
            if not self.connect():
                return False
        # qBittorrent Web API expects a '|' separated string for multiple hashes
        hashes_joined = "|".join(hashes)
        try:
            deleted = False
            # Primary: correct param names
            try:
                self.qbt_client.torrents_delete(hashes=hashes_joined, delete_files=delete_files)  # type: ignore
                deleted = True
            except Exception:
                # Fallbacks for older/signature-variant clients
                try:
                    self.qbt_client.torrents_delete(torrent_hashes=hashes_joined, delete_files=delete_files)  # type: ignore
                    deleted = True
                except Exception:
                    try:
                        self.qbt_client.torrents_delete(hashes=hashes_joined, deleteFiles=delete_files)  # type: ignore
                        deleted = True
                    except Exception:
                        self.qbt_client.torrents_delete(hashes=hashes, delete_files=delete_files)  # type: ignore
                        deleted = True

            # Verify deletion actually happened: query current torrents
            try:
                remaining = self.qbt_client.torrents_info() or []  # type: ignore
                remaining_hashes = {
                    getattr(t, "hash", None)
                    or getattr(t, "info_hash", None)
                    or getattr(t, "hashString", None)
                    for t in remaining
                }
                # If any of the requested hashes are still present, consider as not deleted
                if any(h in remaining_hashes for h in hashes):
                    logger.warning(
                        "Some torrents not deleted as expected: %s",
                        [h for h in hashes if h in remaining_hashes],
                    )
                    return False
            except Exception as e:
                logger.debug(
                    "Delete verification failed; assuming delete succeeded: %s", e
                )

            return deleted
        except Exception:
            logger.exception("Error deleting torrents")
            return False

    def stop_by_name(self, name_substr: str) -> str:
        """Stop (pause) torrents whose name includes `name_substr`.

        Returns a human-readable result string.
        """
        matches = self._find_torrents(name_substr)
        if not matches:
            return "No matching torrents found."
        hashes = [m["hash"] for m in matches if m.get("hash")]
        if not hashes:
            return "Found matching torrents but could not determine their hashes."
        ok = self._call_pause_resume(hashes, "pause")
        if ok:
            names = ", ".join(m["name"] for m in matches)
            return f"Paused: {html.escape(names)}"
        return "Failed to pause torrents."

    def start_by_name(self, name_substr: str) -> str:
        """Start (resume) torrents whose name includes `name_substr`.

        Returns a human-readable result string.
        """
        matches = self._find_torrents(name_substr)
        if not matches:
            return "No matching torrents found."
        hashes = [m["hash"] for m in matches if m.get("hash")]
        if not hashes:
            return "Found matching torrents but could not determine their hashes."
        ok = self._call_pause_resume(hashes, "resume")
        if ok:
            names = ", ".join(m["name"] for m in matches)
            return f"Resumed: {html.escape(names)}"
        return "Failed to resume torrents."

    def preview_by_name(self, name_substr: str) -> str:
        """Preview torrents matching `name_substr`."""
        matches = self._find_torrents(name_substr)
        if not matches:
            return "No matching torrents found."
        lines = ["<b>Matching torrents:</b>"]
        for m in matches[:25]:
            name = html.escape(m.get("name", "unknown"))
            state = html.escape(m.get("state", "unknown"))
            lines.append(f"<code>{name}</code> • {state}")
        if len(matches) > 25:
            lines.append(f"<i>...and {len(matches) - 25} more</i>")
        return "\n".join(lines)

    def delete_by_name(self, name_substr: str, delete_files: bool = True) -> str:
        """Delete torrents whose name includes `name_substr`.

        If `delete_files` is True, also delete the content files.
        """
        matches = self._find_torrents(name_substr)
        if not matches:
            return "No matching torrents found."
        hashes = [m["hash"] for m in matches if m.get("hash")]
        if not hashes:
            return "Found matching torrents but could not determine their hashes."
        ok = self._call_delete(hashes, delete_files=delete_files)
        if ok:
            names = ", ".join(m["name"] for m in matches)
            action = (
                "Deleted (files removed)" if delete_files else "Deleted (kept files)"
            )
            return f"{action}: {html.escape(names)}"
        return "Failed to delete torrents."

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
                progress_frac = getattr(t, "progress", 0.0) or 0.0
                progress = progress_frac * 100.0
                dlspeed = (getattr(t, "dlspeed", 0) or 0) / 1024.0

                total_size_raw = getattr(t, "total_size", None)
                if total_size_raw is None:
                    total_size_raw = getattr(t, "size", None)
                try:
                    total_size = int(total_size_raw or 0)
                except Exception:
                    total_size = 0

                downloaded: int | None = None
                for attr in ("completed", "downloaded", "downloaded_session"):
                    raw = getattr(t, attr, None)
                    if raw is None:
                        continue
                    val = None
                    try:
                        val = int(raw)
                    except (TypeError, ValueError) as e:
                        logger.debug(
                            "Cannot parse %s for torrent %s: %s", attr, name, e
                        )
                    if val is not None:
                        downloaded = val
                        break
                if downloaded is None and total_size > 0:
                    downloaded = int(progress_frac * total_size)
                if downloaded is None:
                    downloaded = 0
                if total_size > 0:
                    downloaded = max(0, min(downloaded, total_size))
                    size_summary = f"{fmt_bytes_compact_decimal(downloaded)}/{fmt_bytes_compact_decimal(total_size)}"
                    progress_line = f"  Progress: {progress:.1f}% ({size_summary})\n"
                else:
                    progress_line = f"  Progress: {progress:.1f}%\n"

                parts.append(
                    f"<b>{name}</b>\n"
                    f"  Status: {state}\n"
                    f"{progress_line}"
                    f"  Speed: {dlspeed:.1f} KiB/s"
                )
            return "\n\n".join(parts)
        except Exception as exc:
            logger.exception("Error retrieving qBittorrent status: %s", exc)
            return f"Error retrieving status: {html.escape(str(exc))}"
