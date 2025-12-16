"""Shared handler helpers: auth guard, rate limit, suggestions."""

from __future__ import annotations

import asyncio
import html
import threading
import time
from typing import TYPE_CHECKING, Awaitable, Callable

from telegram.constants import ParseMode

from .. import core
from ..state import BOT_STATE_KEY, BotState

if TYPE_CHECKING:
    from telegram import Update
    from telegram.ext import ContextTypes


# Global rate limit (seconds) for all commands.
_last_command_ts = 0.0
_rate_lock = threading.Lock()


def get_state(app) -> BotState:
    return app.bot_data.setdefault(BOT_STATE_KEY, BotState())


def allowed(update: "Update") -> bool:
    if not core.ALLOWED:
        return False
    chat_id = update.effective_chat.id if update.effective_chat else None
    return chat_id in core.ALLOWED


async def guard(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> bool:
    if allowed(update):
        return True
    if update and update.effective_chat:
        await update.effective_chat.send_message("⛔ Not authorized")
    return False


async def run_rate_limited(
    update: "Update",
    context: "ContextTypes.DEFAULT_TYPE",
    func: Callable[["Update", "ContextTypes.DEFAULT_TYPE"], Awaitable[None]],
) -> None:
    try:
        now = time.monotonic()
        with _rate_lock:
            global _last_command_ts
            elapsed = now - _last_command_ts
            if elapsed < core.RATE_LIMIT_S:
                try:
                    if update and getattr(update, "effective_message", None):
                        await update.effective_message.reply_text(
                            f"⏱ Rate limit: please wait {core.RATE_LIMIT_S - elapsed:.1f}s",
                        )
                except Exception:
                    pass
                return
            _last_command_ts = now
    except Exception:
        pass
    await func(update, context)


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


async def maybe_refresh_containers(context: "ContextTypes.DEFAULT_TYPE") -> None:
    await asyncio.to_thread(get_state(context.application).maybe_refresh, "containers")


async def maybe_refresh_torrents(context: "ContextTypes.DEFAULT_TYPE") -> None:
    await asyncio.to_thread(get_state(context.application).maybe_refresh, "torrents")
