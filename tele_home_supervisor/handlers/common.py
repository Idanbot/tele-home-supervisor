"""Shared handler helpers: auth guard, rate limit, suggestions."""

from __future__ import annotations

import asyncio
import functools
import html
import logging
import time
from typing import TYPE_CHECKING, Awaitable, Callable

from telegram.constants import ParseMode

from .. import config
from ..state import BOT_STATE_KEY, BotState

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from telegram import Update
    from telegram.ext import ContextTypes


# Global rate limit (seconds) for all commands.
_last_command_ts = 0.0
# We use a simple timestamp check. Since we are in asyncio,
# strictly speaking race conditions are only possible at await points.
# A simple float comparison is atomic enough for this use case.


def get_state(app) -> BotState:
    return app.bot_data.setdefault(BOT_STATE_KEY, BotState())


def allowed(update: "Update") -> bool:
    if not config.ALLOWED:
        return False
    chat_id = update.effective_chat.id if update.effective_chat else None
    return chat_id in config.ALLOWED


async def guard(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> bool:
    if allowed(update):
        return True
    if update and update.effective_chat:
        await update.effective_chat.send_message("⛔ Not authorized")
    return False


def rate_limit(func: Callable) -> Callable:
    """Decorator to enforce global rate limit."""

    @functools.wraps(func)
    async def wrapper(
        update: "Update", context: "ContextTypes.DEFAULT_TYPE", *args, **kwargs
    ):
        global _last_command_ts
        now = time.monotonic()
        elapsed = now - _last_command_ts

        if elapsed < config.RATE_LIMIT_S:
            try:
                if update and getattr(update, "effective_message", None):
                    await update.effective_message.reply_text(
                        f"⏱ Rate limit: please wait {config.RATE_LIMIT_S - elapsed:.1f}s",
                    )
            except Exception as e:
                logger.debug("rate-limit notice failed to send: %s", e)
            return

        _last_command_ts = now
        return await func(update, context, *args, **kwargs)

    return wrapper


def _format_suggestions(names: list[str]) -> str:
    if not names:
        return ""
    return "\n<i>Suggestions:</i>\n" + "\n".join(
        f"• <code>{html.escape(n)}</code>" for n in names
    )


async def reply_usage_with_suggestions(
    update: "Update",
    usage_html: str,
    names: list[str] | None = None,
) -> None:
    hint = _format_suggestions(names or [])
    await update.message.reply_text(
        f"<i>Usage:</i> {usage_html}{hint}", parse_mode=ParseMode.HTML
    )
