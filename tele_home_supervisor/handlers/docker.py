from __future__ import annotations

import io
import json
import logging
import re
import time
from datetime import datetime, timezone

from telegram.constants import ParseMode

from .. import services, view
from .common import (
    guard_sensitive,
    get_state_and_recorder,
    record_error,
    reply_usage_with_suggestions,
    set_audit_target,
)
from .callbacks import (
    DOCKER_PAGE_SIZE,
    LOG_PAGE_SIZE,
    LOG_PAGE_STEP,
    _get_log_lines,
    _render_logs_page,
    build_docker_keyboard,
    normalize_docker_page,
)

logger = logging.getLogger(__name__)
_SINCE_RE = re.compile(r"^(\d+)([smhd])$")


def _parse_since(value: str) -> int | None:
    arg = value.strip()
    if not arg:
        return None
    if arg.isdigit():
        return int(time.time() - int(arg))
    match = _SINCE_RE.match(arg.lower())
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        multiplier = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
        return int(time.time() - amount * multiplier)
    try:
        parsed = datetime.fromisoformat(arg)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())
    except ValueError:
        return None


def _parse_dlogs_args(
    args: list[str],
) -> tuple[str | None, int | None, int | None, bool, bool]:
    if not args:
        return None, None, None, False, False
    container = args[0]
    page = None
    since = None
    as_file = False
    invalid_since = False
    idx = 1
    while idx < len(args):
        arg = args[idx]
        if arg == "--file":
            as_file = True
            idx += 1
            continue
        if arg.startswith("--since="):
            since_val = arg.split("=", 1)[1]
            since = _parse_since(since_val)
            if since is None:
                invalid_since = True
            idx += 1
            continue
        if arg == "--since" and idx + 1 < len(args):
            since = _parse_since(args[idx + 1])
            if since is None:
                invalid_since = True
            idx += 2
            continue
        if arg == "--since":
            invalid_since = True
            idx += 1
            continue
        if arg.isdigit():
            page = max(int(arg) - 1, 0)
            idx += 1
            continue
        return container, None, None, as_file, invalid_since
    return container, page, since, as_file, invalid_since


async def cmd_docker(update, context) -> None:
    if not await guard_sensitive(update, context):
        return
    state, recorder = get_state_and_recorder(context)
    page = 0
    if context.args and context.args[0].isdigit():
        page = max(int(context.args[0]) - 1, 0)
    try:
        await state.refresh_containers()
    except Exception as e:
        logger.debug("refresh_containers failed: %s", e)
        recorder.record("docker", "refresh_containers failed", str(e))

    try:
        containers = await services.list_containers()
    except Exception as e:
        await record_error(
            recorder, "docker", "list_containers failed", e, update.message.reply_text
        )
        return
    containers_sorted = sorted(containers, key=lambda item: str(item.get("name", "")))
    page, total_pages = normalize_docker_page(len(containers_sorted), page)
    start = page * DOCKER_PAGE_SIZE
    end = start + DOCKER_PAGE_SIZE
    page_containers = containers_sorted[start:end]
    msg = view.render_container_list_page(page_containers, page, total_pages)

    # Get container names for inline keyboard
    container_names = sorted(state.get_cached("containers"))

    # Build inline keyboard if we have containers
    keyboard = (
        build_docker_keyboard(container_names, page=page) if container_names else None
    )

    parts = view.chunk(msg)
    for i, part in enumerate(parts):
        if i == len(parts) - 1 and keyboard:
            await update.message.reply_text(
                part, parse_mode=ParseMode.HTML, reply_markup=keyboard
            )
        else:
            await update.message.reply_text(part, parse_mode=ParseMode.HTML)


async def cmd_dockerstats(update, context) -> None:
    # Legacy command, mapped to rich stats for now or we can implement summary?
    # services.container_stats_rich returns list of dicts.
    await cmd_dstats_rich(update, context)


async def cmd_dstats_rich(update, context) -> None:
    if not await guard_sensitive(update, context):
        return
    _, recorder = get_state_and_recorder(context)
    try:
        stats = await services.container_stats_rich()
    except Exception as e:
        await record_error(
            recorder,
            "dockerstats",
            "container_stats_rich failed",
            e,
            update.message.reply_text,
        )
        return
    msg = view.render_container_stats(stats)
    for part in view.chunk(msg):
        await update.message.reply_text(part, parse_mode=ParseMode.HTML)


async def cmd_dlogs(update, context) -> None:
    """Fetch container logs."""
    if not await guard_sensitive(update, context):
        return

    state, recorder = get_state_and_recorder(context)
    await state.maybe_refresh("containers")

    if not context.args:
        # Show container selection menu
        from .callbacks import build_dlogs_selection_keyboard

        container_names = sorted(state.get_cached("containers"))
        if not container_names:
            await update.message.reply_text("No containers found.")
            return

        msg = "<b>Select a container to view logs:</b>"
        keyboard = build_dlogs_selection_keyboard(container_names, page=0)
        await update.message.reply_text(
            msg, parse_mode=ParseMode.HTML, reply_markup=keyboard
        )
        return

    container_name, page, since, as_file, invalid_since = _parse_dlogs_args(
        context.args
    )
    if not container_name:
        await update.message.reply_text("❌ Invalid arguments.")
        return
    if invalid_since:
        await update.message.reply_text("❌ Invalid --since value.")
        return
    if page is None and not as_file:
        as_file = True
    set_audit_target(context, container_name)
    container_names = state.get_cached("containers")
    if container_names and container_name not in container_names:
        await reply_usage_with_suggestions(
            update,
            "/dlogs &lt;container&gt; [page] [--since <time>] [--file]",
            state.suggest("containers", query=container_name, limit=5),
        )
        return

    try:
        lines = await _get_log_lines(state, container_name, refresh=True, since=since)
    except Exception as e:
        await record_error(
            recorder,
            "dlogs",
            f"dlogs failed for {container_name}",
            e,
            update.message.reply_text,
        )
        return
    if as_file:
        content = "\n".join(lines)
        payload = content.encode(errors="replace")
        filename = f"{container_name}-logs.txt"
        if since:
            filename = f"{container_name}-logs-since-{since}.txt"
        file_obj = io.BytesIO(payload)
        file_obj.name = filename
        await update.message.reply_document(document=file_obj)
        return
    max_start = max(0, len(lines) - LOG_PAGE_SIZE)
    if page is None:
        start = max_start
    else:
        start = max_start - (page * LOG_PAGE_STEP)
        if start < 0:
            start = 0
    msg, keyboard, _ = _render_logs_page(container_name, lines, start, since=since)
    await update.message.reply_text(
        msg, parse_mode=ParseMode.HTML, reply_markup=keyboard
    )


async def cmd_dhealth(update, context) -> None:
    if not await guard_sensitive(update, context):
        return
    state, recorder = get_state_and_recorder(context)
    await state.maybe_refresh("containers")
    if not context.args:
        await reply_usage_with_suggestions(
            update, "/dhealth &lt;container&gt;", state.suggest("containers", limit=5)
        )
        return
    name = context.args[0]
    set_audit_target(context, name)
    container_names = state.get_cached("containers")
    if container_names and name not in container_names:
        await reply_usage_with_suggestions(
            update,
            "/dhealth &lt;container&gt;",
            state.suggest("containers", query=name, limit=5),
        )
        return
    try:
        msg = await services.healthcheck_container(name)
    except Exception as e:
        await record_error(
            recorder,
            "dhealth",
            f"dhealth failed for {name}",
            e,
            update.message.reply_text,
        )
        return
    # Simple formatting
    await update.message.reply_text(f"<pre>{msg}</pre>", parse_mode=ParseMode.HTML)


async def cmd_ports(update, context) -> None:
    if not await guard_sensitive(update, context):
        return
    _, recorder = get_state_and_recorder(context)

    try:
        msg = await services.get_listening_ports()
    except Exception as e:
        await record_error(
            recorder,
            "ports",
            "get_listening_ports failed",
            e,
            update.message.reply_text,
        )
        return

    # Formatting

    formatted = f"{view.bold('Listening Ports:')}\n{view.pre(msg)}"

    for part in view.chunk(formatted, size=4000):
        await update.message.reply_text(part, parse_mode=ParseMode.HTML)


async def cmd_dinspect(update, context) -> None:
    if not await guard_sensitive(update, context):
        return
    state, recorder = get_state_and_recorder(context)
    await state.maybe_refresh("containers")
    if not context.args:
        await reply_usage_with_suggestions(
            update,
            "/dinspect &lt;container&gt;",
            state.suggest("containers", limit=5),
        )
        return
    name = context.args[0]
    set_audit_target(context, name)
    container_names = state.get_cached("containers")
    if container_names and name not in container_names:
        await reply_usage_with_suggestions(
            update,
            "/dinspect &lt;container&gt;",
            state.suggest("containers", query=name, limit=5),
        )
        return
    try:
        data = await services.get_container_inspect(name)
    except Exception as e:
        await record_error(
            recorder,
            "docker",
            f"docker inspect failed for {name}",
            e,
            update.message.reply_text,
        )
        return

    payload = json.dumps(data, indent=2, ensure_ascii=True)
    if len(payload) > 3500:
        filename = f"{name}-inspect.json"
        file_obj = io.BytesIO(payload.encode(errors="replace"))
        file_obj.name = filename
        await update.message.reply_document(document=file_obj)
        return
    await update.message.reply_text(
        f"{view.bold('Docker Inspect:')}\n{view.pre(payload)}",
        parse_mode=ParseMode.HTML,
    )
