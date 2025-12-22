import pytest

from tele_home_supervisor.handlers import meta
from tele_home_supervisor.handlers.common import get_state


class DummyMessage:
    def __init__(self) -> None:
        self.replies: list[str] = []

    async def reply_text(self, text: str, **_) -> None:
        self.replies.append(text)


class DummyUpdate:
    def __init__(self) -> None:
        self.message = DummyMessage()


class DummyApplication:
    def __init__(self) -> None:
        self.bot_data: dict[str, object] = {}


class DummyContext:
    def __init__(self, args: list[str]) -> None:
        self.args = args
        self.application = DummyApplication()


@pytest.mark.asyncio
async def test_debug_command_filters_by_command(monkeypatch) -> None:
    async def allow_guard(update, context) -> bool:
        return True

    monkeypatch.setattr(meta, "guard_sensitive", allow_guard)
    update = DummyUpdate()
    context = DummyContext(args=["imdb"])
    state = get_state(context.application)
    state.add_debug("imdb", "imdb error")
    state.add_debug("rtmovies", "rt error")

    await meta.cmd_debug(update, context)

    assert update.message.replies
    text = update.message.replies[0]
    assert "imdb" in text
    assert "rtmovies" not in text


@pytest.mark.asyncio
async def test_debug_command_truncates_details(monkeypatch) -> None:
    async def allow_guard(update, context) -> bool:
        return True

    monkeypatch.setattr(meta, "guard_sensitive", allow_guard)
    update = DummyUpdate()
    context = DummyContext(args=[])
    state = get_state(context.application)
    state.add_debug("imdb", "imdb error", "x" * 2000)

    await meta.cmd_debug(update, context)

    text = update.message.replies[0]
    assert "x" * 1200 in text
    assert "x" * 1500 not in text
