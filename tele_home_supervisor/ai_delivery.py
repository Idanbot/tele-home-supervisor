"""Telegram delivery helpers for streaming AI responses."""

from __future__ import annotations

import logging
import secrets
from typing import Protocol

from telegram.constants import ParseMode

logger = logging.getLogger(__name__)


class StreamingDelivery(Protocol):
    """Interface for incremental and final AI response delivery."""

    async def push(self, text: str) -> None:
        """Deliver partial text progress."""

    async def finalize(self, chunks: list[str]) -> None:
        """Deliver the final response chunks."""

    async def error(self, text: str) -> None:
        """Deliver a terminal error."""


async def _send_markdown_reply(message, text: str):
    try:
        return await message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as exc:
        logger.warning("MarkdownV2 reply failed; falling back: %s", exc)
        return await message.reply_text(text)


async def _edit_or_reply_markdown(message, text: str):
    try:
        await message.edit_text(text, parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as exc:
        logger.warning("MarkdownV2 edit failed; falling back: %s", exc)
        await message.edit_text(text)


class EditStreamingDelivery:
    """Fallback delivery that edits a bot message as tokens arrive."""

    def __init__(self, update) -> None:
        self._update = update
        self._message = None

    async def _ensure_message(self):
        if self._message is None:
            self._message = await self._update.message.reply_text("🤔 Thinking...")
        return self._message

    async def push(self, text: str) -> None:
        message = await self._ensure_message()
        await message.edit_text(text)

    async def finalize(self, chunks: list[str]) -> None:
        if not chunks:
            await self.error("❌ Empty AI response.")
            return

        message = await self._ensure_message()
        await _edit_or_reply_markdown(message, chunks[0])

        for chunk in chunks[1:]:
            await _send_markdown_reply(self._update.message, chunk)

    async def error(self, text: str) -> None:
        message = await self._ensure_message()
        await message.edit_text(text)


class DraftStreamingDelivery:
    """Preferred delivery using Telegram's draft streaming API."""

    def __init__(self, update, bot, chat_id: int) -> None:
        self._update = update
        self._bot = bot
        self._chat_id = chat_id
        self._draft_id = secrets.randbelow(2_147_483_647) + 1

    async def push(self, text: str) -> None:
        await self._bot.send_message_draft(
            chat_id=self._chat_id, draft_id=self._draft_id, text=text
        )

    async def finalize(self, chunks: list[str]) -> None:
        if not chunks:
            await self.error("❌ Empty AI response.")
            return

        await _send_markdown_reply(self._update.message, chunks[0])
        for chunk in chunks[1:]:
            await _send_markdown_reply(self._update.message, chunk)

    async def error(self, text: str) -> None:
        await self._update.message.reply_text(text)


class FallbackStreamingDelivery:
    """Try draft streaming first and fall back to edit-based updates."""

    def __init__(
        self, preferred: StreamingDelivery | None, fallback: StreamingDelivery
    ):
        self._preferred = preferred
        self._fallback = fallback
        self._active = preferred or fallback

    async def push(self, text: str) -> None:
        if self._active is self._fallback or self._preferred is None:
            await self._fallback.push(text)
            return
        try:
            await self._preferred.push(text)
        except Exception as exc:
            logger.warning(
                "Draft streaming unavailable, falling back to edits: %s", exc
            )
            self._active = self._fallback
            await self._fallback.push(text)

    async def finalize(self, chunks: list[str]) -> None:
        if self._active is self._fallback:
            await self._fallback.finalize(chunks)
            return
        if self._preferred is None:
            await self._fallback.finalize(chunks)
            return
        await self._preferred.finalize(chunks)

    async def error(self, text: str) -> None:
        if self._active is self._fallback:
            await self._fallback.error(text)
            return
        if self._preferred is None:
            await self._fallback.error(text)
            return
        try:
            await self._preferred.error(text)
        except Exception as exc:
            logger.warning(
                "Draft-stream error delivery failed, using fallback: %s", exc
            )
            await self._fallback.error(text)


def build_streaming_delivery(update, context) -> StreamingDelivery:
    """Create the best available delivery strategy for the current update."""
    fallback = EditStreamingDelivery(update)

    bot = getattr(context, "bot", None)
    if bot is None:
        app = getattr(context, "application", None)
        bot = getattr(app, "bot", None)

    chat = getattr(update, "effective_chat", None)
    chat_id = getattr(chat, "id", None)
    send_message_draft = getattr(bot, "send_message_draft", None)
    preferred = None
    if callable(send_message_draft) and isinstance(chat_id, int):
        preferred = DraftStreamingDelivery(update, bot, chat_id)

    return FallbackStreamingDelivery(preferred, fallback)
