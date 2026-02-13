"""Callback handlers for Docker containers and log viewing."""

from __future__ import annotations

import html
import io
import logging
import math

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from .. import services, view
from ..state import BotState
from .common import get_state
from .cb_helpers import safe_edit_message_text, build_pagination_row

logger = logging.getLogger(__name__)

DOCKER_PAGE_SIZE = 8
LOG_PAGE_SIZE = 50
LOG_PAGE_STEP = 45
LOG_LINE_MAX = 300


# ---------------------------------------------------------------------------
# Pagination helpers
# ---------------------------------------------------------------------------


def normalize_docker_page(total_items: int, page: int) -> tuple[int, int]:
    total_pages = max(1, math.ceil(total_items / DOCKER_PAGE_SIZE))
    page = max(0, min(page, total_pages - 1))
    return page, total_pages


# ---------------------------------------------------------------------------
# Log utilities
# ---------------------------------------------------------------------------


def _trim_log_line(line: str) -> str:
    if len(line) <= LOG_LINE_MAX:
        return line
    return f"{line[: LOG_LINE_MAX - 3]}..."


def _parse_log_page_payload(
    data: str, prefix: str
) -> tuple[str, int, int | None] | None:
    payload = data[len(prefix) :]
    parts = payload.split(":")
    if len(parts) < 2:
        return None
    if len(parts) == 2:
        container, start_raw = parts
        since_raw = None
    else:
        container = ":".join(parts[:-2])
        start_raw = parts[-2]
        since_raw = parts[-1]
    if not container:
        return None
    try:
        start = max(int(start_raw), 0)
    except ValueError:
        start = 0
    since = None
    if since_raw:
        try:
            since = int(since_raw)
        except ValueError:
            since = None
    return container, start, since


async def _get_log_lines(
    state: BotState, container: str, refresh: bool, since: int | None = None
) -> list[str]:
    if since is None and not refresh:
        cached = state.get_log_cache(container)
        if cached is not None:
            return cached
    raw = await services.get_container_logs_full(container, since=since)
    lines = raw.splitlines() if raw else []
    if since is None:
        state.set_log_cache(container, lines)
    return lines


def _render_logs_page(
    container: str, lines: list[str], start: int, since: int | None = None
) -> tuple[str, InlineKeyboardMarkup | None, int]:
    total = len(lines)
    if total == 0:
        return "<i>No logs found.</i>", None, 0
    max_start = max(0, total - LOG_PAGE_SIZE)
    start = max(0, min(start, max_start))
    end = min(start + LOG_PAGE_SIZE, total)
    header = (
        f"{view.bold(f'Logs for {html.escape(container)}')} "
        f"<i>(lines {start + 1}-{end} of {total})</i>\n"
    )
    display_lines = [_trim_log_line(line) for line in lines[start:end]]
    max_len = 3600
    if display_lines:
        allowed_len = max(
            20,
            (max_len - len(header) - 11) // max(1, len(display_lines)),
        )
        if allowed_len < LOG_LINE_MAX:
            display_lines = [
                _trim_log_line(line[:allowed_len]) for line in display_lines
            ]
    msg = f"{header}{view.pre(chr(10).join(display_lines))}"

    buttons: list[list[InlineKeyboardButton]] = []
    nav_row: list[InlineKeyboardButton] = []
    if start > 0:
        prev_start = max(0, start - LOG_PAGE_STEP)
        nav_row.append(
            InlineKeyboardButton(
                "⬆️ Older",
                callback_data=_format_log_callback(
                    container, prev_start, since, "page"
                ),
            )
        )
    nav_row.append(
        InlineKeyboardButton(
            "⬇️ Tail",
            callback_data=_format_log_callback(container, max_start, since, "page"),
        )
    )
    if start < max_start:
        next_start = min(max_start, start + LOG_PAGE_STEP)
        nav_row.append(
            InlineKeyboardButton(
                "⬇️ Newer",
                callback_data=_format_log_callback(
                    container, next_start, since, "page"
                ),
            )
        )
    if nav_row:
        buttons.append(nav_row)

    action_row = [
        InlineKeyboardButton(
            "🔄 Refresh",
            callback_data=_format_log_callback(container, start, since, "refresh"),
        ),
        InlineKeyboardButton(
            "💾 File",
            callback_data=_format_log_callback(container, start, since, "file"),
        ),
        InlineKeyboardButton(
            "🔙 List",
            callback_data="dlogs:back",
        ),
    ]
    buttons.append(action_row)

    return msg, InlineKeyboardMarkup(buttons), start


def _format_log_callback(
    container: str, start: int, since: int | None, action: str
) -> str:
    if since is None:
        return f"dlogs:{action}:{container}:{start}"
    return f"dlogs:{action}:{container}:{start}:{since}"


# ---------------------------------------------------------------------------
# Keyboard builders
# ---------------------------------------------------------------------------


def build_dlogs_selection_keyboard(
    containers: list[str], page: int = 0
) -> InlineKeyboardMarkup:
    """Build inline keyboard for selecting a container to view logs."""
    buttons: list[list[InlineKeyboardButton]] = []
    page, total_pages = normalize_docker_page(len(containers), page)
    start = page * DOCKER_PAGE_SIZE
    end = start + DOCKER_PAGE_SIZE

    row: list[InlineKeyboardButton] = []
    for name in containers[start:end]:
        row.append(
            InlineKeyboardButton(f"📜 {name[:20]}", callback_data=f"dlogs:{name[:30]}")
        )
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    nav_row = build_pagination_row(page, total_pages, "dlogs:list")
    if nav_row:
        buttons.append(nav_row)

    return InlineKeyboardMarkup(buttons)


def build_docker_keyboard(containers: list[str], page: int = 0) -> InlineKeyboardMarkup:
    """Build inline keyboard with container action buttons."""
    buttons: list[list[InlineKeyboardButton]] = []
    page, total_pages = normalize_docker_page(len(containers), page)
    start = page * DOCKER_PAGE_SIZE
    end = start + DOCKER_PAGE_SIZE
    for name in containers[start:end]:
        buttons.append(
            [
                InlineKeyboardButton(
                    f"📜 {name[:12]}", callback_data=f"dlogs:{name[:30]}"
                ),
                InlineKeyboardButton("❤️", callback_data=f"dhealth:{name[:30]}"),
                InlineKeyboardButton("📊", callback_data=f"dstats:{name[:30]}"),
            ]
        )

    nav_row = build_pagination_row(page, total_pages, "docker:page")
    if nav_row:
        buttons.append(nav_row)

    buttons.append(
        [InlineKeyboardButton("🔄 Refresh", callback_data=f"docker:refresh:{page}")]
    )
    return InlineKeyboardMarkup(buttons)


# ---------------------------------------------------------------------------
# Callback handlers
# ---------------------------------------------------------------------------


async def handle_dlogs_callback(query, context, container: str) -> None:
    state: BotState = get_state(context.application)
    await state.maybe_refresh("containers")
    if state.get_cached("containers") and container not in state.get_cached(
        "containers"
    ):
        await query.message.reply_text(f"❌ Unknown container: {container}")
        return
    lines = await _get_log_lines(state, container, refresh=True)
    start = max(len(lines) - LOG_PAGE_SIZE, 0)
    msg, keyboard, _ = _render_logs_page(container, lines, start)
    await query.message.reply_text(
        msg, parse_mode=ParseMode.HTML, reply_markup=keyboard
    )


async def handle_dlogs_page(
    query, context, container: str, start: int, since: int | None, refresh: bool
) -> None:
    state: BotState = get_state(context.application)
    lines = await _get_log_lines(state, container, refresh=refresh, since=since)
    msg, keyboard, _ = _render_logs_page(container, lines, start, since=since)
    await safe_edit_message_text(
        query, msg[:4000], parse_mode=ParseMode.HTML, reply_markup=keyboard
    )


async def handle_dhealth_callback(query, context, container: str) -> None:
    state: BotState = get_state(context.application)
    await state.maybe_refresh("containers")
    if state.get_cached("containers") and container not in state.get_cached(
        "containers"
    ):
        await query.message.reply_text(f"❌ Unknown container: {container}")
        return
    msg = await services.healthcheck_container(container)
    await query.message.reply_text(f"<pre>{msg}</pre>", parse_mode=ParseMode.HTML)


async def handle_dstats_callback(query, context, container: str) -> None:
    state: BotState = get_state(context.application)
    await state.maybe_refresh("containers")
    if state.get_cached("containers") and container not in state.get_cached(
        "containers"
    ):
        await query.message.reply_text(f"❌ Unknown container: {container}")
        return
    stats = await services.container_stats_rich()
    target_stats = [s for s in stats if s["name"] == container]
    if not target_stats:
        msg = f"Stats for {container} not found."
    else:
        msg = view.render_container_stats(target_stats)
    await query.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def handle_docker_refresh(query, context, page: int) -> None:
    await _update_docker_message(query, context, page=page, refresh=True)


async def handle_docker_page(query, context, page: int) -> None:
    await _update_docker_message(query, context, page=page, refresh=False)


async def _update_docker_message(query, context, page: int, refresh: bool) -> None:
    state: BotState = get_state(context.application)
    if refresh:
        await state.refresh_containers()
    else:
        await state.maybe_refresh("containers")

    containers = await services.list_containers()
    containers_sorted = sorted(containers, key=lambda item: str(item.get("name", "")))
    page, total_pages = normalize_docker_page(len(containers_sorted), page)
    start = page * DOCKER_PAGE_SIZE
    end = start + DOCKER_PAGE_SIZE
    page_containers = containers_sorted[start:end]
    msg = view.render_container_list_page(page_containers, page, total_pages)

    container_names = [c.get("name", "") for c in containers_sorted if c.get("name")]
    keyboard = build_docker_keyboard(container_names, page=page)

    await safe_edit_message_text(
        query, msg[:4000], parse_mode=ParseMode.HTML, reply_markup=keyboard
    )


async def handle_dlogs_list(query, context, page: int) -> None:
    state: BotState = get_state(context.application)
    await state.maybe_refresh("containers")

    container_names = sorted(state.get_cached("containers"))
    if not container_names:
        await safe_edit_message_text(
            query, "No containers found.", parse_mode=ParseMode.HTML
        )
        return

    msg = "<b>Select a container to view logs:</b>"
    keyboard = build_dlogs_selection_keyboard(container_names, page=page)
    await safe_edit_message_text(
        query, msg, parse_mode=ParseMode.HTML, reply_markup=keyboard
    )


async def handle_dlogs_file(query, context, container: str, since: int | None) -> None:
    await query.answer("Fetching log file...")
    try:
        raw_logs = await services.get_container_logs_full(container, since=since)
    except Exception as e:
        await query.message.reply_text(f"❌ Failed to fetch logs: {e}")
        return

    if not raw_logs:
        await query.message.reply_text("❌ Log is empty.")
        return

    payload = raw_logs.encode(errors="replace")
    filename = f"{container}-logs.txt"
    if since:
        filename = f"{container}-logs-since-{since}.txt"

    file_obj = io.BytesIO(payload)
    file_obj.name = filename

    try:
        await query.message.reply_document(document=file_obj)
    except Exception as e:
        logger.error(f"Failed to send log file: {e}")
        await query.message.reply_text(f"❌ Failed to send file: {e}")
