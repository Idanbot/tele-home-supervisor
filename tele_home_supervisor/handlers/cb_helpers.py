"""Shared helpers used by the callback sub-modules."""

from __future__ import annotations

import logging
import time

from telegram import InlineKeyboardButton
from telegram.error import BadRequest

from .common import record_audit_event

logger = logging.getLogger(__name__)


async def safe_edit_message_text(query, text: str, **kwargs) -> None:
    """Edit a callback message, silently ignoring 'not modified' errors."""
    try:
        await query.edit_message_text(text, **kwargs)
    except BadRequest as exc:
        if "Message is not modified" in str(exc):
            return
        raise


async def run_audit_action(update, context, action: str, target: str | None, coro):
    """Execute *coro* and record an audit event for the callback."""
    start = time.perf_counter()
    status = "ok"
    try:
        await coro
    except Exception:
        status = "error"
        raise
    finally:
        duration_ms = int((time.perf_counter() - start) * 1000)
        try:
            record_audit_event(
                context, update, f"cb:{action}", target, status, duration_ms
            )
        except Exception as audit_error:
            logger.debug("audit record failed: %s", audit_error)


def build_pagination_row(
    page: int, total_pages: int, prefix: str
) -> list[InlineKeyboardButton]:
    """Build a standard prev/page/next navigation row."""
    if total_pages <= 1:
        return []

    nav_row: list[InlineKeyboardButton] = []
    if page > 0:
        nav_row.append(
            InlineKeyboardButton("⬅️ Prev", callback_data=f"{prefix}:{page - 1}")
        )
    nav_row.append(
        InlineKeyboardButton(
            f"📄 {page + 1}/{total_pages}",
            callback_data=f"{prefix.split(':')[0]}:noop",
        )
    )
    if page + 1 < total_pages:
        nav_row.append(
            InlineKeyboardButton("Next ➡️", callback_data=f"{prefix}:{page + 1}")
        )
    return nav_row


def parse_page(data: str, prefix: str) -> int:
    """Extract a page number from a callback data string."""
    token = data[len(prefix) :].strip()
    try:
        return max(int(token), 0)
    except ValueError:
        return 0
