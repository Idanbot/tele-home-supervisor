"""Background jobs (started once per Application)."""
from __future__ import annotations

import asyncio
import html
import logging
import time
from dataclasses import dataclass

from telegram.constants import ParseMode
from telegram.ext import Application

from .state import BOT_STATE_KEY, BotState
from .torrent import TorrentManager, fmt_bytes_compact_decimal

logger = logging.getLogger(__name__)

_TASK_TORRENT_COMPLETION = "torrent_completion"
_POLL_INTERVAL_S = 30.0


@dataclass(frozen=True)
class TorrentSnapshot:
    torrent_hash: str
    name: str
    is_complete: bool
    total_size: int
    downloaded: int


def ensure_started(app: Application) -> None:
    state: BotState = app.bot_data.setdefault(BOT_STATE_KEY, BotState())
    task = state.tasks.get(_TASK_TORRENT_COMPLETION)
    if isinstance(task, asyncio.Task) and not task.done():
        return
    state.tasks[_TASK_TORRENT_COMPLETION] = asyncio.create_task(_torrent_completion_loop(app))


def _get_state(app: Application) -> BotState:
    return app.bot_data.setdefault(BOT_STATE_KEY, BotState())


def _get_torrent_hash(torrent_obj: object) -> str | None:
    for attr in ("hash", "info_hash", "hashString"):
        val = getattr(torrent_obj, attr, None)
        if val:
            return str(val)
    return None


def _snapshot_torrents() -> dict[str, TorrentSnapshot] | None:
    mgr = TorrentManager()
    if not mgr.connect() or mgr.qbt_client is None:
        return None
    try:
        torrents = mgr.qbt_client.torrents_info() or []
    except Exception:
        logger.exception("Failed to query torrents_info()")
        return None

    out: dict[str, TorrentSnapshot] = {}
    for t in torrents:
        torrent_hash = _get_torrent_hash(t)
        if not torrent_hash:
            continue

        name = str(getattr(t, "name", "") or "")
        progress_frac = getattr(t, "progress", 0.0) or 0.0
        try:
            progress_frac = float(progress_frac)
        except Exception:
            progress_frac = 0.0

        amount_left_raw = getattr(t, "amount_left", None)
        try:
            amount_left = int(amount_left_raw) if amount_left_raw is not None else None
        except Exception:
            amount_left = None

        is_complete = bool(amount_left == 0 or progress_frac >= 0.9999)

        total_size_raw = getattr(t, "total_size", None)
        if total_size_raw is None:
            total_size_raw = getattr(t, "size", None)
        try:
            total_size = int(total_size_raw or 0)
        except Exception:
            total_size = 0

        downloaded_raw = None
        for attr in ("completed", "downloaded", "downloaded_session"):
            val = getattr(t, attr, None)
            if val is None:
                continue
            downloaded_raw = val
            break
        try:
            downloaded = int(downloaded_raw or 0)
        except Exception:
            downloaded = 0
        if downloaded <= 0 and total_size > 0:
            downloaded = int(progress_frac * total_size)
        if total_size > 0:
            downloaded = max(0, min(downloaded, total_size))

        out[torrent_hash] = TorrentSnapshot(
            torrent_hash=torrent_hash,
            name=name,
            is_complete=is_complete,
            total_size=total_size,
            downloaded=downloaded,
        )
    return out


def _format_completion_message(t: TorrentSnapshot) -> str:
    name = html.escape(t.name or "<unknown>")
    size_part = ""
    if t.total_size > 0:
        size_part = f" (<code>{fmt_bytes_compact_decimal(t.downloaded)}/{fmt_bytes_compact_decimal(t.total_size)}</code>)"
    return f"✅ Torrent completed: <b>{name}</b>{size_part}"


async def _torrent_completion_loop(app: Application) -> None:
    initialized = False
    seen_complete: dict[str, bool] = {}

    logger.info("Starting torrent completion loop (interval=%ss)", _POLL_INTERVAL_S)
    while True:
        try:
            start = time.monotonic()
            snapshot = await asyncio.to_thread(_snapshot_torrents)
            if snapshot is None:
                await asyncio.sleep(_POLL_INTERVAL_S)
                continue

            if not initialized:
                seen_complete = {h: t.is_complete for h, t in snapshot.items()}
                initialized = True
                await asyncio.sleep(_POLL_INTERVAL_S)
                continue

            current_complete = {h: t.is_complete for h, t in snapshot.items()}
            new_completions: list[TorrentSnapshot] = []
            for h, t in snapshot.items():
                if t.is_complete and not seen_complete.get(h, False):
                    new_completions.append(t)

            seen_complete = current_complete

            state = _get_state(app)
            if new_completions and state.torrent_completion_subscribers:
                subs = list(state.torrent_completion_subscribers)
                for t in new_completions:
                    msg = _format_completion_message(t)
                    for chat_id in subs:
                        try:
                            await app.bot.send_message(chat_id=chat_id, text=msg, parse_mode=ParseMode.HTML)
                        except Exception:
                            logger.exception("Failed sending torrent completion to chat_id=%s", chat_id)

            elapsed = time.monotonic() - start
            await asyncio.sleep(max(0.0, _POLL_INTERVAL_S - elapsed))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Torrent completion loop error")
            await asyncio.sleep(_POLL_INTERVAL_S)

