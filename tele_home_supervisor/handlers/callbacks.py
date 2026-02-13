"""Callback query dispatcher.

Routes incoming ``CallbackQuery`` data to domain-specific handler modules:
- :mod:`.cb_docker` – Docker containers and log viewing
- :mod:`.cb_torrents` – Torrent management
- :mod:`.cb_media` – TMDB, ProtonDB, PirateBay, free games
"""

from __future__ import annotations

import html
import logging

from telegram.constants import ParseMode

from .common import allowed
from . import alerts as alerts_handler

# Sub-module handlers
from . import cb_docker, cb_torrents, cb_media

# Shared helpers (used by the router and also re-exported)
from .cb_helpers import (  # noqa: F401 – re-exported
    safe_edit_message_text as _safe_edit_message_text,
    run_audit_action as _run_audit_action,
    build_pagination_row as _build_pagination_row,
    parse_page as _parse_page,
)

# ---------------------------------------------------------------------------
# Re-exports for backward compatibility – other modules import these names
# from ``handlers.callbacks``.
# ---------------------------------------------------------------------------
from .cb_docker import (  # noqa: F401
    DOCKER_PAGE_SIZE,
    LOG_PAGE_SIZE,
    LOG_PAGE_STEP,
    build_docker_keyboard,
    build_dlogs_selection_keyboard,
    normalize_docker_page,
    _get_log_lines,
    _render_logs_page,
    _parse_log_page_payload,
)
from .cb_torrents import (  # noqa: F401
    TORRENT_PAGE_SIZE,
    build_torrent_keyboard,
    normalize_torrent_page,
    paginate_torrents,
)
from .cb_media import (  # noqa: F401
    build_tmdb_keyboard,
    build_protondb_keyboard,
    build_free_games_keyboard,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Alert payload parser (kept here – tiny and only used by the router)
# ---------------------------------------------------------------------------


def _parse_alerts_payload(data: str) -> tuple[str, str] | None:
    parts = data.split(":")
    if len(parts) != 3:
        return None
    _, action, rule_id = parts
    if not action or not rule_id:
        return None
    return action, rule_id


# ---------------------------------------------------------------------------
# Central callback dispatcher
# ---------------------------------------------------------------------------


async def handle_callback_query(update, context) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data

    if not allowed(update):
        await _safe_edit_message_text(query, "⛔ Not authorized")
        return

    try:
        # --- Alerts ----------------------------------------------------------
        if data.startswith("alerts:"):
            payload = _parse_alerts_payload(data)
            if payload:
                action, rule_id = payload
                await _run_audit_action(
                    update,
                    context,
                    f"alerts_{action}",
                    rule_id,
                    alerts_handler.handle_alerts_callback(
                        query, context, action, rule_id
                    ),
                )
            else:
                await _safe_edit_message_text(query, "❓ Invalid alert action")

        # --- Docker / Logs ---------------------------------------------------
        elif data.startswith("dlogs:page:"):
            payload = cb_docker._parse_log_page_payload(data, "dlogs:page:")
            if payload:
                container, start, since = payload
                await _run_audit_action(
                    update,
                    context,
                    "dlogs_page",
                    container,
                    cb_docker.handle_dlogs_page(
                        query, context, container, start, since=since, refresh=False
                    ),
                )
        elif data.startswith("dlogs:refresh:"):
            payload = cb_docker._parse_log_page_payload(data, "dlogs:refresh:")
            if payload:
                container, start, since = payload
                await _run_audit_action(
                    update,
                    context,
                    "dlogs_refresh",
                    container,
                    cb_docker.handle_dlogs_page(
                        query, context, container, start, since=since, refresh=True
                    ),
                )
        elif data.startswith("dlogs:file:"):
            payload = cb_docker._parse_log_page_payload(data, "dlogs:file:")
            if payload:
                container, _, since = payload
                await _run_audit_action(
                    update,
                    context,
                    "dlogs_file",
                    container,
                    cb_docker.handle_dlogs_file(query, context, container, since),
                )
        elif data.startswith("dlogs:list:"):
            page = _parse_page(data, "dlogs:list:")
            await _run_audit_action(
                update,
                context,
                "dlogs_list",
                str(page),
                cb_docker.handle_dlogs_list(query, context, page),
            )
        elif data == "dlogs:back":
            await _run_audit_action(
                update,
                context,
                "dlogs_back",
                None,
                cb_docker.handle_dlogs_list(query, context, 0),
            )
        elif data == "dlogs:noop":
            return
        elif data.startswith("dlogs:"):
            container = data[6:]
            await _run_audit_action(
                update,
                context,
                "dlogs",
                container,
                cb_docker.handle_dlogs_callback(query, context, container),
            )
        elif data.startswith("dhealth:"):
            container = data[8:]
            await _run_audit_action(
                update,
                context,
                "dhealth",
                container,
                cb_docker.handle_dhealth_callback(query, context, container),
            )
        elif data.startswith("dstats:"):
            container = data[7:]
            await _run_audit_action(
                update,
                context,
                "dstats",
                container,
                cb_docker.handle_dstats_callback(query, context, container),
            )
        elif data == "docker:refresh":
            await _run_audit_action(
                update,
                context,
                "docker_refresh",
                "0",
                cb_docker.handle_docker_refresh(query, context, 0),
            )
        elif data.startswith("docker:refresh:"):
            page = _parse_page(data, "docker:refresh:")
            await _run_audit_action(
                update,
                context,
                "docker_refresh",
                str(page),
                cb_docker.handle_docker_refresh(query, context, page),
            )
        elif data.startswith("docker:page:"):
            page = _parse_page(data, "docker:page:")
            await _run_audit_action(
                update,
                context,
                "docker_page",
                str(page),
                cb_docker.handle_docker_page(query, context, page),
            )
        elif data == "docker:noop":
            return

        # --- Torrents --------------------------------------------------------
        elif data.startswith("tstop:"):
            torrent_hash = data[6:]
            await _run_audit_action(
                update,
                context,
                "tstop",
                torrent_hash,
                cb_torrents.handle_torrent_stop(query, context, torrent_hash),
            )
        elif data.startswith("tstart:"):
            torrent_hash = data[7:]
            await _run_audit_action(
                update,
                context,
                "tstart",
                torrent_hash,
                cb_torrents.handle_torrent_start(query, context, torrent_hash),
            )
        elif data.startswith("tinfo:"):
            torrent_hash = data[6:]
            await _run_audit_action(
                update,
                context,
                "tinfo",
                torrent_hash,
                cb_torrents.handle_torrent_info(query, context, torrent_hash),
            )
        elif data.startswith("tdelete:"):
            torrent_hash = data[8:]
            await _run_audit_action(
                update,
                context,
                "tdelete",
                torrent_hash,
                cb_torrents.handle_torrent_delete(query, context, torrent_hash),
            )
        elif data == "torrent:refresh":
            await _run_audit_action(
                update,
                context,
                "torrent_refresh",
                "0",
                cb_torrents.handle_torrent_refresh(query, context, 0),
            )
        elif data.startswith("torrent:refresh:"):
            page = _parse_page(data, "torrent:refresh:")
            await _run_audit_action(
                update,
                context,
                "torrent_refresh",
                str(page),
                cb_torrents.handle_torrent_refresh(query, context, page),
            )
        elif data.startswith("torrent:page:"):
            page = _parse_page(data, "torrent:page:")
            await _run_audit_action(
                update,
                context,
                "torrent_page",
                str(page),
                cb_torrents.handle_torrent_page(query, context, page),
            )
        elif data == "torrent:noop":
            return

        # --- Media (TMDB, ProtonDB, PirateBay, Games) -----------------------
        elif data.startswith("games:"):
            game_type = data[6:]
            await _run_audit_action(
                update,
                context,
                "games",
                game_type,
                cb_media.handle_games_callback(query, context, game_type),
            )
        elif data.startswith("pbmagnet:"):
            key = data[len("pbmagnet:") :]
            await _run_audit_action(
                update,
                context,
                "pbmagnet",
                key,
                cb_media.handle_piratebay_magnet(query, context, key),
            )
        elif data.startswith("pbselect:"):
            key = data[len("pbselect:") :]
            await _run_audit_action(
                update,
                context,
                "pbselect",
                key,
                cb_media.handle_piratebay_select(query, context, key),
            )
        elif data.startswith("pbadd:"):
            key = data[len("pbadd:") :]
            await _run_audit_action(
                update,
                context,
                "pbadd",
                key,
                cb_media.handle_piratebay_add(query, context, key),
            )
        elif data.startswith("tmdbpage:"):
            await _run_audit_action(
                update,
                context,
                "tmdbpage",
                None,
                cb_media.handle_tmdb_page(query, context, data),
            )
        elif data.startswith("tmdbinfo:"):
            await _run_audit_action(
                update,
                context,
                "tmdbinfo",
                data,
                cb_media.handle_tmdb_info(query, context, data),
            )
        elif data.startswith("protondbinfo:"):
            await _run_audit_action(
                update,
                context,
                "protondbinfo",
                data,
                cb_media.handle_protondb_info(query, context, data),
            )
        else:
            await _safe_edit_message_text(query, "❓ Unknown action")
    except Exception as e:
        logger.exception("Callback query error")
        try:
            await query.message.reply_text(
                f"❌ Error: {html.escape(str(e))}", parse_mode=ParseMode.HTML
            )
        except Exception as notify_error:
            logger.error(f"Failed to send error notification: {notify_error}")
