"""Entrypoint for running the Telegram bot from the package.

This module wires up the Application, registers handlers and runs polling.
"""

from __future__ import annotations

import logging

from telegram import BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler

from .logger import setup_logging
from . import config
from .commands import COMMANDS, GROUP_ORDER
from .handlers import dispatch
from .handlers.callbacks import handle_callback_query
from .state import BOT_STATE_KEY, BotState
from .background import ensure_started
from .runtime import STARTUP_TIME

logger = logging.getLogger(__name__)


def build_application() -> Application:
    if config.TOKEN is None:
        raise RuntimeError("BOT_TOKEN environment variable is not set")

    app = Application.builder().token(config.TOKEN).build()

    app.bot_data.setdefault(BOT_STATE_KEY, BotState())

    for spec in COMMANDS:
        fn = getattr(dispatch, spec.handler)
        triggers = [spec.name, *spec.aliases]
        app.add_handler(CommandHandler(triggers, fn))

    # Register callback query handler for inline keyboards
    app.add_handler(CallbackQueryHandler(handle_callback_query))

    return app


async def register_bot_commands(app: Application) -> None:
    """Register bot commands for Telegram autocomplete."""
    try:
        # Build command list from COMMANDS registry
        bot_commands = []
        for spec in COMMANDS:
            # Skip aliases, only register primary command names
            bot_commands.append(BotCommand(spec.name, spec.description))

        await app.bot.set_my_commands(bot_commands)
        logger.info(f"Registered {len(bot_commands)} commands for autocomplete")
    except Exception as e:
        logger.warning(f"Failed to register bot commands: {e}")


async def send_startup_notification(app: Application) -> None:
    """Send startup notification to all allowed chat IDs."""
    try:
        ensure_started(app)
    except Exception as e:
        logger.warning("Failed to start background tasks: %s", e)

    # Register commands for autocomplete
    await register_bot_commands(app)

    logger.info(f"Sending startup notification to {len(config.ALLOWED)} chat(s)")
    if not config.ALLOWED:
        logger.warning("No ALLOWED_CHAT_IDS configured, skipping startup notification")
        return

    startup_msg = f"🤖 Bot is deployed at {STARTUP_TIME.strftime('%Y-%m-%d %H:%M:%S')}"
    for chat_id in config.ALLOWED:
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
