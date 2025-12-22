"""Shared handler helpers: auth guard, rate limit, suggestions."""

from __future__ import annotations

import functools
import html
import logging
import time
from typing import TYPE_CHECKING, Callable

from telegram.constants import ParseMode

from .. import config
from ..state import BOT_STATE_KEY, BotState, DebugRecorder

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from telegram import Update
    from telegram.ext import ContextTypes


# Global rate limit (seconds) for all commands.
_last_command_ts = 0.0
# We use a simple timestamp check. Since we are in asyncio,
# strictly speaking race conditions are only possible at await points.
# A simple float comparison is atomic enough for this use case.
_DAY_S = 24 * 60 * 60  # 24 hours
_AUTH_TTL_S = _DAY_S


def auth_ttl_seconds() -> int:
    return _AUTH_TTL_S


def get_state(app) -> BotState:
    """Retrieve or initialize the bot state from application data.

    Args:
        app: The Telegram Application instance

    Returns:
        BotState object containing runtime state, caches, and subscriptions.
    """
    return app.bot_data.setdefault(BOT_STATE_KEY, BotState())


def get_state_and_recorder(context) -> tuple[BotState, DebugRecorder]:
    state = get_state(context.application)
    return state, state.debug_recorder()


async def record_error(
    recorder,
    command: str,
    message: str,
    exc: Exception,
    reply,
    log: logging.Logger | None = None,
):
    (log or logger).exception(message)
    recorder.record(command, message, str(exc))
    await reply(f"❌ Error: {html.escape(str(exc))}", parse_mode=ParseMode.HTML)


def allowed(update: "Update") -> bool:
    """Check if the update sender is authorized to use the bot.

    Args:
        update: Telegram Update object containing chat information

    Returns:
        True if the chat ID is in the ALLOWED list, False otherwise.

    Note:
        Returns False if ALLOWED_CHAT_IDS is empty or update has no chat.
    """
    if not config.ALLOWED:
        return False
    if not update.effective_chat:
        return False
    chat_id = update.effective_chat.id
    effective_user = getattr(update, "effective_user", None)
    user_id = getattr(effective_user, "id", None)
    # Allow only private chats where chat_id == user_id and user is on the allowlist.
    if user_id is None:
        return chat_id in config.ALLOWED
    return chat_id == user_id and user_id in config.ALLOWED


async def guard(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> bool:
    """Guard function to check authorization before executing commands.

    Args:
        update: Telegram Update object
        context: Telegram context object

    Returns:
        True if authorized, False otherwise. Sends unauthorized message on failure.

    Note:
        This is the primary authorization mechanism for all guarded commands.
    """
    if allowed(update):
        return True
    if update and update.effective_chat:
        await update.effective_chat.send_message("⛔ Not authorized")
    return False


def _auth_valid(state: BotState, user_id: int) -> bool:
    now = time.monotonic()
    expiry = state.auth_grants.get(user_id)
    if not expiry or expiry <= now:
        state.auth_grants.pop(user_id, None)
        return False
    return True


async def guard_sensitive(
    update: "Update", context: "ContextTypes.DEFAULT_TYPE"
) -> bool:
    if not await guard(update, context):
        return False
    if not config.BOT_AUTH_TOTP_SECRET:
        if update and update.effective_chat:
            await update.effective_chat.send_message(
                "⛔ Auth secret not configured. Set BOT_AUTH_TOTP_SECRET."
            )
        return False
    if not update or not update.effective_user:
        return False
    state = get_state(context.application)
    if _auth_valid(state, update.effective_user.id):
        return True
    if update and update.effective_chat:
        await update.effective_chat.send_message(
            "🔒 Please authenticate with /auth <secret> (valid for 24 hours)."
        )
    return False


def rate_limit(func: Callable, name: str | None = None) -> Callable:
    """Decorator to enforce global rate limiting on command handlers.

    Args:
        func: The async command handler function to wrap

    Returns:
        Wrapped function that enforces rate limiting based on config.RATE_LIMIT_S

    Note:
        Uses a global timestamp check. Rate limit applies across all commands.
        If rate limit is exceeded, sends a message to the user with wait time.
    """

    command_name = name or func.__name__.removeprefix("cmd_")

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
            try:
                state = get_state(context.application)
                state.record_rate_limited(command_name)
            except Exception as e:
                logger.debug("metrics rate-limit record failed: %s", e)
            return

        _last_command_ts = now
        start = time.perf_counter()
        try:
            result = await func(update, context, *args, **kwargs)
        except Exception as e:
            latency_s = time.perf_counter() - start
            try:
                state = get_state(context.application)
                state.record_command(
                    command_name, latency_s, ok=False, error_msg=str(e)
                )
            except Exception as metrics_error:
                logger.debug("metrics record failed: %s", metrics_error)
            raise
        else:
            latency_s = time.perf_counter() - start
            try:
                state = get_state(context.application)
                state.record_command(command_name, latency_s, ok=True, error_msg=None)
            except Exception as metrics_error:
                logger.debug("metrics record failed: %s", metrics_error)
            return result

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
