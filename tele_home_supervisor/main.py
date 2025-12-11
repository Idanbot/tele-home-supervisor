"""Entrypoint for running the Telegram bot from the package.

This module wires up the Application, registers handlers and runs polling.
"""
from __future__ import annotations

import logging
from datetime import datetime

from telegram.ext import Application, CommandHandler

# Track startup time
STARTUP_TIME = datetime.now()

from .logger import setup_logging
from . import core

logger = logging.getLogger(__name__)


def build_application() -> Application:
    if core.TOKEN is None:
        raise RuntimeError("BOT_TOKEN environment variable is not set")

    app = Application.builder().token(core.TOKEN).build()

    app.add_handler(CommandHandler(["start"], core.cmd_start))
    app.add_handler(CommandHandler(["whoami"], core.cmd_whoami))
    app.add_handler(CommandHandler(["help"], core.cmd_help))
    app.add_handler(CommandHandler(["ip"], core.cmd_ip))
    app.add_handler(CommandHandler(["health"], core.cmd_health))
    app.add_handler(CommandHandler(["docker"], core.cmd_docker))
    app.add_handler(CommandHandler(["dockerstats"], core.cmd_dockerstats))
    app.add_handler(CommandHandler(["dstatsrich"], core.cmd_dstats_rich))
    app.add_handler(CommandHandler(["logs"], core.cmd_logs))
    app.add_handler(CommandHandler(["dhealth"], core.cmd_dhealth))
    app.add_handler(CommandHandler(["ping"], core.cmd_ping))
    app.add_handler(CommandHandler(["temp"], core.cmd_temp))
    app.add_handler(CommandHandler(["tadd"], core.cmd_torrent_add))
    app.add_handler(CommandHandler(["tstatus"], core.cmd_torrent_status))
    app.add_handler(CommandHandler(["uptime"], core.cmd_uptime))
    app.add_handler(CommandHandler(["version"], core.cmd_version))

    return app


async def send_startup_notification(app: Application) -> None:
    """Send startup notification to all allowed chat IDs."""
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
            logger.warning(f"Failed to send startup notification to chat_id {chat_id}: {e}")


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
