"""Entrypoint for running the Telegram bot from the package.

This module wires up the Application, registers handlers and runs polling.
"""

from __future__ import annotations

import logging

from telegram.ext import Application, CommandHandler

from .logger import setup_logging
from . import core
from .commands import COMMANDS
from .handlers import dispatch
from .state import BOT_STATE_KEY, BotState
from .background import ensure_started
from .runtime import STARTUP_TIME

logger = logging.getLogger(__name__)


def build_application() -> Application:
    if core.TOKEN is None:
        raise RuntimeError("BOT_TOKEN environment variable is not set")

    app = Application.builder().token(core.TOKEN).build()

    app.bot_data.setdefault(BOT_STATE_KEY, BotState())

    for spec in COMMANDS:
        fn = getattr(dispatch, spec.handler)
        triggers = [spec.name, *spec.aliases]
        app.add_handler(CommandHandler(triggers, fn))

    return app


async def send_startup_notification(app: Application) -> None:
    """Send startup notification to all allowed chat IDs."""
    try:
        ensure_started(app)
    except Exception as e:
        logger.warning("Failed to start background tasks: %s", e)

    logger.info(f"Sending startup notification to {len(core.ALLOWED)} chat(s)")
    if not core.ALLOWED:
        logger.warning("No ALLOWED_CHAT_IDS configured, skipping startup notification")
        return

    startup_msg = f"🤖 Bot is deployed at {STARTUP_TIME.strftime('%Y-%m-%d %H:%M:%S')}"
    for chat_id in core.ALLOWED:
        try:
            await app.bot.send_message(chat_id=chat_id, text=startup_msg)
            logger.info(f"Sent startup notification to chat_id {chat_id}")
        except Exception as e:
            logger.warning(
                f"Failed to send startup notification to chat_id {chat_id}: {e}"
            )


def run() -> None:
    setup_logging()
    logger.info("Starting tele_home_supervisor")
    app = build_application()

    # Register post_init callback to send startup notification
    app.post_init = send_startup_notification

    # run polling; keep the stop_signals None so container shutdown behaves normally
    app.run_polling(stop_signals=None)


if __name__ == "__main__":
    run()
