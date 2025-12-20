import asyncio

import pytest
from telegram.constants import ParseMode

from tele_home_supervisor import config
from tele_home_supervisor.handlers import ai


class DummyChat:
    def __init__(self, chat_id: int) -> None:
        self.id = chat_id
        self.sent: list[str] = []

    async def send_message(self, text: str) -> None:
        self.sent.append(text)


class DummyOutboundMessage:
    def __init__(self, fail_markdown: bool) -> None:
        self.fail_markdown = fail_markdown
        self.edit_calls: list[tuple[str, str | None]] = []

    async def edit_text(self, text: str, parse_mode: str | None = None, **_) -> None:
        self.edit_calls.append((text, parse_mode))
        if self.fail_markdown and parse_mode == ParseMode.MARKDOWN_V2:
            raise RuntimeError("markdown parse error")


class DummyInboundMessage:
    def __init__(self, outbound: DummyOutboundMessage) -> None:
        self.outbound = outbound
        self.reply_calls: list[str] = []

    async def reply_text(self, text: str, **_) -> DummyOutboundMessage:
        self.reply_calls.append(text)
        return self.outbound


class DummyUpdate:
    def __init__(self, message: DummyInboundMessage, chat_id: int) -> None:
        self.message = message
        self.effective_chat = DummyChat(chat_id)


class DummyContext:
    def __init__(self, args: list[str]) -> None:
        self.args = args
        self.user_data: dict[str, object] = {}


@pytest.mark.asyncio
async def test_cmd_ask_stream_fallbacks_on_markdown_error(monkeypatch) -> None:
    monkeypatch.setattr(config, "ALLOWED", {123})
    monkeypatch.setattr(ai, "STREAM_MIN_TOKENS", 1)
    monkeypatch.setattr(ai, "STREAM_UPDATE_INTERVAL", 0)

    tokens = ["Hello"]

    class DummyClient:
        def __init__(self, *_, **__) -> None:
            pass

        async def generate_stream(self, _prompt: str):
            for token in tokens:
                yield token
                await asyncio.sleep(0)

    monkeypatch.setattr(ai, "OllamaClient", DummyClient)

    outbound = DummyOutboundMessage(fail_markdown=True)
    inbound = DummyInboundMessage(outbound)
    update = DummyUpdate(inbound, chat_id=123)
    context = DummyContext(args=["hi"])

    await ai.cmd_ask(update, context)

    parse_modes = [mode for _, mode in outbound.edit_calls]
    assert ParseMode.MARKDOWN_V2 in parse_modes
    assert None in parse_modes
    assert outbound.edit_calls[-1][1] is None


@pytest.mark.asyncio
async def test_cmd_ask_final_fallback_on_markdown_error(monkeypatch) -> None:
    monkeypatch.setattr(config, "ALLOWED", {123})
    monkeypatch.setattr(ai, "STREAM_MIN_TOKENS", 999)
    monkeypatch.setattr(ai, "STREAM_UPDATE_INTERVAL", 999)

    tokens = ["Hello", " world"]

    class DummyClient:
        def __init__(self, *_, **__) -> None:
            pass

        async def generate_stream(self, _prompt: str):
            for token in tokens:
                yield token
                await asyncio.sleep(0)

    monkeypatch.setattr(ai, "OllamaClient", DummyClient)

    outbound = DummyOutboundMessage(fail_markdown=True)
    inbound = DummyInboundMessage(outbound)
    update = DummyUpdate(inbound, chat_id=123)
    context = DummyContext(args=["hi"])

    await ai.cmd_ask(update, context)

    assert len(outbound.edit_calls) == 2
    assert outbound.edit_calls[0][1] == ParseMode.MARKDOWN_V2
    assert outbound.edit_calls[1][1] is None


@pytest.mark.asyncio
async def test_cmd_ask_no_fallback_when_markdown_ok(monkeypatch) -> None:
    monkeypatch.setattr(config, "ALLOWED", {123})
    monkeypatch.setattr(ai, "STREAM_MIN_TOKENS", 999)
    monkeypatch.setattr(ai, "STREAM_UPDATE_INTERVAL", 999)

    tokens = ["All good."]

    class DummyClient:
        def __init__(self, *_, **__) -> None:
            pass

        async def generate_stream(self, _prompt: str):
            for token in tokens:
                yield token
                await asyncio.sleep(0)

    monkeypatch.setattr(ai, "OllamaClient", DummyClient)

    outbound = DummyOutboundMessage(fail_markdown=False)
    inbound = DummyInboundMessage(outbound)
    update = DummyUpdate(inbound, chat_id=123)
    context = DummyContext(args=["hi"])

    await ai.cmd_ask(update, context)

    assert len(outbound.edit_calls) == 1
    assert outbound.edit_calls[0][1] == ParseMode.MARKDOWN_V2
