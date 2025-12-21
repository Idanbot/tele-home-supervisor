import time

import pytest

from tele_home_supervisor import config
from tele_home_supervisor.handlers import common, meta
from tele_home_supervisor.handlers.common import get_state


class DummyMessage:
    def __init__(self) -> None:
        self.replies: list[tuple[str, dict]] = []

    async def reply_text(self, text: str, **kwargs) -> None:
        self.replies.append((text, kwargs))


class DummyUpdate:
    def __init__(self) -> None:
        self.effective_message = DummyMessage()
        self.message = self.effective_message


class DummyApplication:
    def __init__(self) -> None:
        self.bot_data: dict[str, object] = {}


class DummyContext:
    def __init__(self) -> None:
        self.application = DummyApplication()


@pytest.mark.asyncio
async def test_rate_limit_records_success(monkeypatch) -> None:
    monkeypatch.setattr(config, "RATE_LIMIT_S", 0.0)
    monkeypatch.setattr(common, "_last_command_ts", 0.0)

    async def handler(update, context) -> None:
        return None

    wrapped = common.rate_limit(handler, name="demo")
    update = DummyUpdate()
    context = DummyContext()

    await wrapped(update, context)

    metrics = get_state(context.application).command_metrics["demo"]
    assert metrics.count == 1
    assert metrics.success == 1
    assert metrics.error == 0


@pytest.mark.asyncio
async def test_rate_limit_records_error(monkeypatch) -> None:
    monkeypatch.setattr(config, "RATE_LIMIT_S", 0.0)
    monkeypatch.setattr(common, "_last_command_ts", 0.0)

    async def handler(update, context) -> None:
        raise RuntimeError("boom")

    wrapped = common.rate_limit(handler, name="boom")
    update = DummyUpdate()
    context = DummyContext()

    with pytest.raises(RuntimeError):
        await wrapped(update, context)

    metrics = get_state(context.application).command_metrics["boom"]
    assert metrics.count == 1
    assert metrics.success == 0
    assert metrics.error == 1
    assert metrics.last_error == "boom"


@pytest.mark.asyncio
async def test_rate_limit_records_rate_limited(monkeypatch) -> None:
    monkeypatch.setattr(config, "RATE_LIMIT_S", 100.0)
    monkeypatch.setattr(common, "_last_command_ts", time.monotonic())

    async def handler(update, context) -> None:
        return None

    wrapped = common.rate_limit(handler, name="limited")
    update = DummyUpdate()
    context = DummyContext()

    await wrapped(update, context)

    metrics = get_state(context.application).command_metrics["limited"]
    assert metrics.rate_limited == 1
    assert metrics.count == 0


@pytest.mark.asyncio
async def test_metrics_command_hides_last_error(monkeypatch) -> None:
    async def allow_guard(update, context) -> bool:
        return True

    monkeypatch.setattr(meta, "guard_sensitive", allow_guard)
    update = DummyUpdate()
    context = DummyContext()
    state = get_state(context.application)
    metrics = state.metrics_for("demo")
    metrics.count = 1
    metrics.error = 1
    metrics.last_error = "secret boom"

    await meta.cmd_metrics(update, context)

    assert update.message.replies
    text, _ = update.message.replies[0]
    assert "secret boom" not in text
