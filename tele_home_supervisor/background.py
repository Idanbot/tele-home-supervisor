"""Background jobs (started once per Application)."""

from __future__ import annotations

import asyncio
import html
import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram.constants import ParseMode
from telegram.ext import Application

from .state import BOT_STATE_KEY, BotState
from .torrent import fmt_bytes_compact_decimal, get_manager, reset_manager
from .models.torrent_snapshot import TorrentSnapshot
from . import scheduled as scheduled_fetchers
from . import intel
from . import alerting
from .config import settings

logger = logging.getLogger(__name__)

_TASK_TORRENT_COMPLETION = "torrent_completion"
_TASK_GAMEOFFERS = "gameoffers_scheduler"
_TASK_MORNING_INTEL = "morning_intel_scheduler"
_TASK_ALERTS = "alerts_scheduler"
_TASK_MEDIA_CLEANUP = "media_cleanup"

_POLL_INTERVAL_S = 30.0
_ALERT_POLL_INTERVAL_S = 60.0
_MEDIA_CLEANUP_INTERVAL_S = 900.0  # check every 15 minutes
_ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")

# ---------------------------------------------------------------------------
# Graceful shutdown coordination
# ---------------------------------------------------------------------------

_shutdown_requested = False


async def _interruptible_sleep(seconds: float) -> bool:
    """Sleep for up to *seconds*, waking early on shutdown.

    Checks the shutdown flag every second.  Returns ``True`` if shutdown
    was requested (callers should break out of their loop), ``False`` on
    a normal timeout.
    """
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if _shutdown_requested:
            return True
        await asyncio.sleep(min(1.0, end - time.monotonic()))
    return _shutdown_requested


def request_shutdown() -> None:
    """Signal all background loops to exit at their next sleep point."""
    global _shutdown_requested
    _shutdown_requested = True


async def cancel_tasks(state: BotState) -> None:
    """Cancel running background tasks and wait for them to finish."""
    request_shutdown()
    task_names = [
        _TASK_TORRENT_COMPLETION,
        _TASK_GAMEOFFERS,
        _TASK_MORNING_INTEL,
        _TASK_ALERTS,
        _TASK_MEDIA_CLEANUP,
    ]
    for name in task_names:
        task = state.tasks.get(name)
        if isinstance(task, asyncio.Task) and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                logger.warning("Background task %s cancelled", name)
            except Exception:
                logger.warning(
                    "Background task %s raised during cancel", name, exc_info=True
                )
            logger.info("Background task %s stopped", name)
    state.tasks.clear()


def ensure_started(app: Application) -> None:
    state: BotState = app.bot_data.setdefault(BOT_STATE_KEY, BotState())

    # Load persisted state
    state.load_state()

    # Start torrent completion loop
    task = state.tasks.get(_TASK_TORRENT_COMPLETION)
    if not isinstance(task, asyncio.Task) or task.done():
        state.tasks[_TASK_TORRENT_COMPLETION] = asyncio.create_task(
            _torrent_completion_loop(app)
        )

    # Start Game Offers scheduler (replaces Epic Games)
    task = state.tasks.get(_TASK_GAMEOFFERS)
    if not isinstance(task, asyncio.Task) or task.done():
        state.tasks[_TASK_GAMEOFFERS] = asyncio.create_task(_game_offers_scheduler(app))

    # Start Morning Intel scheduler (8 AM)
    task = state.tasks.get(_TASK_MORNING_INTEL)
    if not isinstance(task, asyncio.Task) or task.done():
        state.tasks[_TASK_MORNING_INTEL] = asyncio.create_task(
            _morning_intel_scheduler(app)
        )

    # Start alerts loop
    task = state.tasks.get(_TASK_ALERTS)
    if not isinstance(task, asyncio.Task) or task.done():
        state.tasks[_TASK_ALERTS] = asyncio.create_task(_alerts_loop(app))

    # Start media cleanup loop
    task = state.tasks.get(_TASK_MEDIA_CLEANUP)
    if not isinstance(task, asyncio.Task) or task.done():
        state.tasks[_TASK_MEDIA_CLEANUP] = asyncio.create_task(_media_cleanup_loop(app))


def _get_state(app: Application) -> BotState:
    return app.bot_data.setdefault(BOT_STATE_KEY, BotState())


def _get_torrent_hash(torrent_obj: object) -> str | None:
    for attr in ("hash", "info_hash", "hashString"):
        val = getattr(torrent_obj, attr, None)
        if val:
            return str(val)
    return None


def _snapshot_torrents() -> dict[str, TorrentSnapshot] | None:
    mgr = get_manager()
    if mgr is None or mgr.qbt_client is None:
        return None
    try:
        torrents = mgr.qbt_client.torrents_info() or []
    except Exception:
        logger.exception("Failed to query torrents_info()")
        reset_manager()
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
    while not _shutdown_requested:
        try:
            start = time.monotonic()
            snapshot = await asyncio.to_thread(_snapshot_torrents)
            if snapshot is None:
                if await _interruptible_sleep(_POLL_INTERVAL_S):
                    break
                continue

            if not initialized:
                seen_complete = {h: t.is_complete for h, t in snapshot.items()}
                initialized = True
                if await _interruptible_sleep(_POLL_INTERVAL_S):
                    break
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
                            await app.bot.send_message(
                                chat_id=chat_id, text=msg, parse_mode=ParseMode.HTML
                            )
                        except Exception:
                            logger.exception(
                                "Failed sending torrent completion to chat_id=%s",
                                chat_id,
                            )

            elapsed = time.monotonic() - start
            if await _interruptible_sleep(max(0.0, _POLL_INTERVAL_S - elapsed)):
                break
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Torrent completion loop error")
            if await _interruptible_sleep(_POLL_INTERVAL_S):
                break
    logger.info("Torrent completion loop stopped")


async def _alerts_loop(app: Application) -> None:
    logger.info("Starting alerts loop (interval=%ss)", _ALERT_POLL_INTERVAL_S)
    while not _shutdown_requested:
        try:
            start = time.monotonic()
            state = _get_state(app)
            if not state.alerts_enabled:
                if await _interruptible_sleep(_ALERT_POLL_INTERVAL_S):
                    break
                continue
            metrics = await alerting.collect_alert_metrics(state)
            if metrics:
                notifications, changed = alerting.evaluate_alert_rules(state, metrics)
                for chat_id, message in notifications:
                    try:
                        await app.bot.send_message(
                            chat_id=chat_id,
                            text=message,
                            parse_mode=ParseMode.HTML,
                        )
                    except Exception:
                        logger.exception(
                            "Failed sending alert notification to chat_id=%s", chat_id
                        )
                if changed:
                    state.save()
            elapsed = time.monotonic() - start
            if await _interruptible_sleep(max(0.0, _ALERT_POLL_INTERVAL_S - elapsed)):
                break
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Alerts loop error")
            if await _interruptible_sleep(_ALERT_POLL_INTERVAL_S):
                break
    logger.info("Alerts loop stopped")


def _seconds_until_time(target_hour: int, target_minute: int = 0) -> float:
    """Calculate seconds until next occurrence of target time in Israel timezone."""
    now = datetime.now(_ISRAEL_TZ)
    target = now.replace(
        hour=target_hour, minute=target_minute, second=0, microsecond=0
    )

    if now >= target:
        # Target time has passed today, schedule for tomorrow
        target = target + timedelta(days=1)

    delta = (target - now).total_seconds()
    return max(0.0, delta)


async def _game_offers_scheduler(app: Application) -> None:
    """Schedule combined Game Offers notification at 8 PM Israel time daily."""
    logger.info("Starting Game Offers scheduler (8 PM Israel time)")

    while not _shutdown_requested:
        try:
            # Wait until 8 PM Israel time
            wait_seconds = _seconds_until_time(20, 0)  # 8 PM = 20:00
            logger.info(
                "Game Offers: waiting %.1f seconds until next run", wait_seconds
            )
            if await _interruptible_sleep(wait_seconds):
                break

            # Fetch and send
            state = _get_state(app)
            if not settings.ALLOWED_CHAT_IDS:
                logger.warning("No allowed chat IDs configured")
                if await _interruptible_sleep(3600):
                    break
                continue

            combined_msg, image_url = await asyncio.to_thread(
                scheduled_fetchers.build_combined_game_offers, 5
            )

            for chat_id in settings.ALLOWED_CHAT_IDS:
                if state.is_gameoffers_muted(chat_id):
                    logger.debug("Game Offers muted for chat_id=%s", chat_id)
                    continue

                try:
                    if image_url:
                        try:
                            sent = await app.bot.send_photo(
                                chat_id=chat_id,
                                photo=image_url,
                                caption=combined_msg,
                                parse_mode=ParseMode.HTML,
                            )
                            if sent and hasattr(sent, "message_id"):
                                state.track_media_message(chat_id, sent.message_id)
                        except Exception as img_err:
                            logger.warning(
                                "Failed to send Game Offers image, sending text: %s",
                                img_err,
                            )
                            await app.bot.send_message(
                                chat_id=chat_id,
                                text=combined_msg,
                                parse_mode=ParseMode.HTML,
                                disable_web_page_preview=True,
                            )
                    else:
                        await app.bot.send_message(
                            chat_id=chat_id,
                            text=combined_msg,
                            parse_mode=ParseMode.HTML,
                            disable_web_page_preview=True,
                        )
                    logger.info(
                        "Sent Game Offers notification to chat_id=%s",
                        chat_id,
                    )
                except Exception:
                    logger.exception(
                        "Failed to send Game Offers notification to chat_id=%s", chat_id
                    )

            # Wait a bit to avoid rescheduling immediately
            if await _interruptible_sleep(120):
                break

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Game Offers scheduler error")
            if await _interruptible_sleep(3600):
                break
    logger.info("Game Offers scheduler stopped")


async def _morning_intel_scheduler(app: Application) -> None:
    """Schedule Morning Intel at 8 AM Israel time daily."""
    logger.info("Starting Morning Intel scheduler (8 AM Israel time)")

    while not _shutdown_requested:
        try:
            # Wait until 8 AM Israel time
            wait_seconds = _seconds_until_time(8, 0)  # 8 AM = 08:00
            logger.info(
                "Morning Intel: waiting %.1f seconds until next run", wait_seconds
            )
            if await _interruptible_sleep(wait_seconds):
                break

            # Fetch and send
            state = _get_state(app)
            if not settings.ALLOWED_CHAT_IDS:
                logger.warning("No allowed chat IDs configured")
                if await _interruptible_sleep(3600):
                    break
                continue

            for chat_id in settings.ALLOWED_CHAT_IDS:
                try:
                    message = await intel.build_morning_intel(chat_id, state)
                    await app.bot.send_message(
                        chat_id=chat_id,
                        text=message,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True,
                    )
                    logger.info(
                        "Sent Morning Intel notification to chat_id=%s", chat_id
                    )
                except Exception:
                    logger.exception(
                        "Failed to send Morning Intel notification to chat_id=%s",
                        chat_id,
                    )

            # Wait a bit to avoid rescheduling immediately
            if await _interruptible_sleep(120):
                break

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Morning Intel scheduler error")
            if await _interruptible_sleep(3600):
                break
    logger.info("Morning Intel scheduler stopped")


# ---------------------------------------------------------------------------
# Media auto-delete loop
# ---------------------------------------------------------------------------


async def delete_media_messages(
    app: Application, entries: list[tuple[int, int]]
) -> int:
    """Delete a batch of tracked media messages.

    Returns the number of successfully deleted messages.
    """
    deleted = 0
    for chat_id, message_id in entries:
        try:
            await app.bot.delete_message(chat_id=chat_id, message_id=message_id)
            deleted += 1
        except Exception:
            logger.debug(
                "Could not delete media message %s in chat %s", message_id, chat_id
            )
    return deleted


async def _media_cleanup_loop(app: Application) -> None:
    """Periodically delete tracked media older than the configured TTL."""
    max_age_s = settings.BOT_AUTO_DELETE_MEDIA_HOURS * 3600
    logger.info(
        "Starting media cleanup loop (TTL=%sh, interval=%ss)",
        settings.BOT_AUTO_DELETE_MEDIA_HOURS,
        _MEDIA_CLEANUP_INTERVAL_S,
    )
    while not _shutdown_requested:
        try:
            state = _get_state(app)
            expired = state.pop_expired_media(max_age_s)
            if expired:
                deleted = await delete_media_messages(app, expired)
                state.save()
                logger.info(
                    "Auto-deleted %d/%d expired media messages", deleted, len(expired)
                )
            if await _interruptible_sleep(_MEDIA_CLEANUP_INTERVAL_S):
                break
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Media cleanup loop error")
            if await _interruptible_sleep(_MEDIA_CLEANUP_INTERVAL_S):
                break
    logger.info("Media cleanup loop stopped")
