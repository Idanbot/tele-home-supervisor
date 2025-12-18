"""AI/LLM handlers for Ollama integration."""

from __future__ import annotations

import asyncio
import html
import logging
import time

from telegram.constants import ParseMode
from telegram import Update
from telegram.ext import ContextTypes

from .. import config
from ..ai_service import OllamaClient
from .common import guard

logger = logging.getLogger(__name__)

STREAM_UPDATE_INTERVAL = 0.5
STREAM_MIN_TOKENS = 3

STYLE_SYSTEM_PROMPT = (
    "You are a professional assistant. Reply using HTML. "
    "Provide a <b>bold title</b>, one-sentence summary, then 3–10 clear bullets. "
    "Use <pre><code>...</code></pre> for code blocks. "
    "Do NOT include chain-of-thought or <think> tags; answer directly. "
    "Aim for clarity and style."
)


async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ask a question to the local Ollama model with streaming response."""
    if not await guard(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: /ask &lt;your question&gt;\n\n"
            f"Model: <code>{html.escape(config.OLLAMA_MODEL)}</code>\n"
            f"Host: <code>{html.escape(config.OLLAMA_HOST)}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    prompt = " ".join(context.args)

    msg = await update.message.reply_text(
        "🤔 <i>Thinking...</i>",
        parse_mode=ParseMode.HTML,
    )

    client = OllamaClient(
        base_url=config.OLLAMA_HOST,
        model=config.OLLAMA_MODEL,
        system_prompt=STYLE_SYSTEM_PROMPT,
    )

    full_response = []
    pending_tokens = []
    last_update_time = time.time()
    think_mode = False

    try:
        async for token in client.generate_stream(prompt):
            if "<think>" in token:
                think_mode = True
                token = token.replace("<think>", "")
            if "</think>" in token:
                think_mode = False
                token = token.replace("</think>", "")

            if think_mode or not token:
                continue

            full_response.append(token)
            pending_tokens.append(token)

            now = time.time()
            if (
                len(pending_tokens) >= STREAM_MIN_TOKENS
                or (now - last_update_time) >= STREAM_UPDATE_INTERVAL
            ):

                current_text = _format_html("".join(full_response), done=False)

                try:
                    await msg.edit_text(current_text, parse_mode=ParseMode.HTML)
                    pending_tokens.clear()
                    last_update_time = now
                except Exception as e:
                    logger.debug(f"Stream edit skipped: {e}")
                    if "Retry in" in str(e):
                        await asyncio.sleep(1)

        final_text = _format_html("".join(full_response), done=True)
        await msg.edit_text(final_text, parse_mode=ParseMode.HTML)

    except Exception as e:
        logger.exception("Ollama request failed")
        await msg.edit_text(
            f"❌ Error: {html.escape(str(e))}\n\n"
            f"Host: <code>{html.escape(config.OLLAMA_HOST)}</code>",
            parse_mode=ParseMode.HTML,
        )


def _format_html(text: str, done: bool) -> str:
    text = html.escape(text.strip())

    if not text:
        return "⏳ <i>thinking...</i>"

    if not done:
        text += "\n\n⏳"

    return text
