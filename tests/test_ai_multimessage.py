"""Integration tests for multi-message AI responses."""

import asyncio
import pytest

from tele_home_supervisor import config
from tele_home_supervisor.handlers import ai


class DummyChat:
    def __init__(self, chat_id: int) -> None:
        self.id = chat_id
        self.sent: list[str] = []

    async def send_message(self, text: str) -> None:
        self.sent.append(text)


class DummyOutboundMessage:
    def __init__(self) -> None:
        self.edit_calls: list[str] = []

    async def edit_text(self, text: str, parse_mode: str | None = None, **_) -> None:
        self.edit_calls.append(text)


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
        self.application = None  # Not needed for this test


@pytest.mark.asyncio
async def test_cmd_ask_splits_long_response(monkeypatch) -> None:
    """Test that a very long response triggers multiple messages."""

    # Setup mocks
    monkeypatch.setattr(config, "ALLOWED", {123})
    # Disable intermediate streaming updates to focus on final delivery
    monkeypatch.setattr(ai, "STREAM_MIN_TOKENS", 99999)

    # Create a response > 4000 chars
    # 5000 'A's
    long_text = "A" * 5000
    tokens = [long_text]

    class DummyClient:
        def __init__(self, *_, **__) -> None:
            pass

        async def generate_stream(self, _prompt: str):
            for token in tokens:
                yield token
                await asyncio.sleep(0)

    monkeypatch.setattr(ai, "OllamaClient", DummyClient)

    outbound = DummyOutboundMessage()
    inbound = DummyInboundMessage(outbound)
    update = DummyUpdate(inbound, chat_id=123)
    context = DummyContext(args=["test"])

    # Run handler
    await ai.cmd_ask(update, context)

    # Verification

    # 1. The original "Thinking..." message should have been edited with the first chunk
    assert len(outbound.edit_calls) > 0
    first_chunk = outbound.edit_calls[-1]  # The last edit is the final result
    assert len(first_chunk) <= 4096
    assert "Thinking..." not in first_chunk

    # 2. The overflow should have been sent as a NEW reply
    assert (
        len(inbound.reply_calls) > 0
    )  # Should have at least 1 reply (the "Thinking..." one)
    # Wait, in the code: `msg = await update.message.reply_text("🤔 Thinking...")`
    # So reply_calls[0] is "Thinking...".
    # Subsequent calls are the chunks.

    # Let's check inbound.reply_calls
    # Index 0: "Thinking..."
    # Index 1: The second chunk of the response (if split happened)

    assert inbound.reply_calls[0] == "🤔 Thinking..."
    assert len(inbound.reply_calls) >= 2

    second_chunk = inbound.reply_calls[1]
    assert len(second_chunk) > 0

    # Verify content reconstruction
    total_content = first_chunk + second_chunk
    # Note: formatting logic adds " " or "▌", so strict equality might be tricky
    # But for "A" * 5000, we expect "A"s.
    assert total_content.count("A") == 5000
    assert first_chunk.count("A") > 3000
    assert second_chunk.count("A") > 0
