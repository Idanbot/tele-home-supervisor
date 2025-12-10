"""Entrypoint for running the Telegram bot from the package.

This module wires up the Application, registers handlers and runs polling.
"""
from __future__ import annotations

import logging
from typing import Any

# The telegram package is an external dependency; Pylance in CI/editors
# may not have the packages installed. Silence unresolved-import errors
# here and avoid strict typing of `Application` to keep diagnostics clean.
from telegram.ext import Application, CommandHandler  # type: ignore[import]

from .logger import setup_logging
from . import core

logger = logging.getLogger(__name__)


def build_application() -> Any:
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

    return app


def run():
    setup_logging()
    logger.info("Starting tele_home_supervisor")
    app = build_application()
    # run polling; keep the stop_signals None so container shutdown behaves normally
    app.run_polling(stop_signals=None)


if __name__ == "__main__":
    run()
