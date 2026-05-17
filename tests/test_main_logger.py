from __future__ import annotations

import logging
from unittest.mock import AsyncMock, Mock

import pytest

from tele_home_supervisor import main
from tele_home_supervisor.logger import JsonFormatter, setup_logging
from tele_home_supervisor.state import BOT_STATE_KEY


class FakeBuilder:
    def __init__(self, app) -> None:
        self.app = app
        self.token_value = None

    def token(self, token: str):
        self.token_value = token
        return self

    def build(self):
        return self.app


class FakeApplication:
    def __init__(self) -> None:
        self.bot_data = {}
        self.handlers = []
        self.bot = Mock()

    def add_handler(self, handler) -> None:
        self.handlers.append(handler)


def test_build_application_registers_handlers(monkeypatch, tmp_path):
    app = FakeApplication()
    monkeypatch.setattr(main.config, "TOKEN", "token")
    monkeypatch.setattr(main.config, "validate_settings", Mock())
    monkeypatch.setattr(main.Application, "builder", lambda: FakeBuilder(app))
    monkeypatch.setattr(
        main, "CommandHandler", lambda triggers, fn: ("cmd", triggers, fn)
    )
    monkeypatch.setattr(main, "CallbackQueryHandler", lambda fn: ("cb", fn))

    result = main.build_application()

    assert result is app
    assert BOT_STATE_KEY in app.bot_data
    assert len(app.handlers) == len(main.COMMANDS) + 1


def test_build_application_requires_token(monkeypatch):
    monkeypatch.setattr(main.config, "TOKEN", None)
    monkeypatch.setattr(main.config, "validate_settings", Mock())

    with pytest.raises(RuntimeError, match="BOT_TOKEN"):
        main.build_application()


@pytest.mark.asyncio
async def test_register_commands_and_startup_notification(monkeypatch):
    app = FakeApplication()
    app.bot.set_my_commands = AsyncMock()
    app.bot.send_message = AsyncMock()
    monkeypatch.setattr(main.config, "ALLOWED", {1, 2})
    monkeypatch.setattr(main, "ensure_started", Mock())

    await main.register_bot_commands(app)
    await main.send_startup_notification(app)

    assert app.bot.set_my_commands.await_count == 2
    assert app.bot.send_message.await_count == 2


@pytest.mark.asyncio
async def test_post_shutdown_saves_state():
    state = Mock()
    app = FakeApplication()
    app.bot_data[BOT_STATE_KEY] = state

    await main._post_shutdown(app)

    state.save.assert_called_once()


def test_run_wires_callbacks(monkeypatch):
    app = FakeApplication()
    app.run_polling = Mock()
    monkeypatch.setattr(main, "setup_logging", Mock())
    monkeypatch.setattr(main, "build_application", Mock(return_value=app))

    main.run()

    assert app.post_init is main.send_startup_notification
    assert app.post_shutdown is main._post_shutdown
    app.run_polling.assert_called_once_with(stop_signals=None)


def test_json_formatter_and_setup_logging(monkeypatch):
    record = logging.LogRecord(
        "name", logging.INFO, __file__, 1, "hello %s", ("world",), None
    )
    record.extra = {"request_id": "abc"}
    payload = JsonFormatter().format(record)

    assert '"message": "hello world"' in payload
    assert '"request_id": "abc"' in payload

    root = logging.getLogger()
    old_handlers = root.handlers[:]
    root.handlers.clear()
    monkeypatch.setenv("LOG_FORMAT", "json")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    try:
        setup_logging()
        assert root.level == logging.INFO
        assert root.handlers
    finally:
        root.handlers[:] = old_handlers
