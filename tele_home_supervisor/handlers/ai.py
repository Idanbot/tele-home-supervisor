"""AI/LLM handlers for Ollama integration."""

from __future__ import annotations

import asyncio
import html
import json
import logging
import time

import requests
from telegram.constants import ParseMode

from .. import core
from .common import guard

logger = logging.getLogger(__name__)

# Update interval for streaming (seconds) to avoid Telegram rate limits
STREAM_UPDATE_INTERVAL = 1.0


async def cmd_ask(update, context) -> None:
    """Ask a question to the local Ollama model with streaming response.

    Usage: /ask <your question>
    """
    if not await guard(update, context):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: /ask &lt;your question&gt;\n\n"
            f"Model: <code>{html.escape(core.OLLAMA_MODEL)}</code>\n"
            f"Host: <code>{html.escape(core.OLLAMA_HOST)}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    prompt = " ".join(context.args)

    # Send initial message
    msg = await update.message.reply_text(
        "🤔 <i>Thinking...</i>",
        parse_mode=ParseMode.HTML,
    )

    try:
        # Get the event loop to schedule coroutines from the thread
        loop = asyncio.get_running_loop()

        result = await asyncio.to_thread(
            _stream_ollama_generate,
            prompt=prompt,
            loop=loop,
            callback=lambda text: asyncio.run_coroutine_threadsafe(
                _update_message(msg, text), loop
            ),
        )

        # Final update with complete response
        await msg.edit_text(result, parse_mode=ParseMode.HTML)

    except Exception as e:
        logger.exception("Ollama request failed")
        await msg.edit_text(
            f"❌ Error: {html.escape(str(e))}\n\n"
            f"Host: <code>{html.escape(core.OLLAMA_HOST)}</code>\n"
            f"Model: <code>{html.escape(core.OLLAMA_MODEL)}</code>",
            parse_mode=ParseMode.HTML,
        )


async def _update_message(msg, text: str) -> None:
    """Helper to update message with rate limiting."""
    try:
        await msg.edit_text(text, parse_mode=ParseMode.HTML)
    except Exception as e:
        # Ignore Telegram rate limit or "message not modified" errors
        logger.debug("Message edit failed: %s", e)


def _stream_ollama_generate(prompt: str, loop=None, callback=None) -> str:
    """Stream generate from Ollama and accumulate response.

    Args:
        prompt: The prompt to send
        loop: Event loop for scheduling async callbacks from thread
        callback: Optional callback for incremental updates

    Returns:
        Complete response text
    """
    url = f"{core.OLLAMA_HOST}/api/generate"
    payload = {
        "model": core.OLLAMA_MODEL,
        "prompt": prompt,
        "stream": True,
    }

    accumulated = []
    last_update = 0.0
    think_mode = False

    try:
        with requests.post(url, json=payload, stream=True, timeout=60) as resp:
            resp.raise_for_status()

            for line in resp.iter_lines():
                if not line:
                    continue

                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue

                token = chunk.get("response", "")
                done = chunk.get("done", False)

                if token:
                    # Handle <think> tags by filtering them out or marking thinking
                    if "<think>" in token:
                        think_mode = True
                        token = token.replace("<think>", "")
                    if "</think>" in token:
                        think_mode = False
                        token = token.replace("</think>", "")

                    # Only accumulate non-thinking tokens
                    if not think_mode and token.strip():
                        accumulated.append(token)

                    # Periodically update the message
                    now = time.time()
                    if callback and (now - last_update) >= STREAM_UPDATE_INTERVAL:
                        current_text = _format_response(accumulated, done=False)
                        if current_text:
                            callback(current_text)
                        last_update = now

                if done:
                    break

        # Return final formatted response
        return _format_response(accumulated, done=True)

    except requests.RequestException as e:
        raise RuntimeError(f"Ollama request failed: {e}") from e


def _format_response(tokens: list[str], done: bool) -> str:
    """Format accumulated tokens for display."""
    text = "".join(tokens).strip()

    if not text:
        return "🤔 <i>Thinking...</i>"

    # Escape HTML
    text = html.escape(text)

    # Add typing indicator if not done
    if not done:
        text = f"{text}<i>▌</i>"

    # Limit message length for Telegram
    if len(text) > 4000:
        text = text[:3900] + "\n\n<i>... (truncated)</i>"

    return text
