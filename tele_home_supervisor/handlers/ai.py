"""AI/LLM handlers for Ollama integration."""

from __future__ import annotations

import asyncio
import html
import json
import logging
import re
import time

import requests
from telegram.constants import ParseMode

from .. import core
from .common import guard

logger = logging.getLogger(__name__)

# Streaming controls
# How often we edit the Telegram message (seconds)
STREAM_UPDATE_INTERVAL = 0.4
# Minimum tokens to batch before pushing an update
STREAM_MIN_TOKENS = 3

# Ollama decode defaults tuned for small CPU models
OLLAMA_TEMP = 0.5
OLLAMA_TOP_K = 80
OLLAMA_TOP_P = 0.92
OLLAMA_NUM_PREDICT = 512  # allow richer responses while staying under Telegram limits

# Default formatting guidance for Ollama responses (safe for HTML parse_mode with escaping)
STYLE_SYSTEM_PROMPT = (
    "You are a professional assistant. Reply using Telegram MarkdownV2. "
    "Provide a bold title, one-sentence summary, then 3–10 clear bullets. "
    "Use fenced code blocks for code. Escape special characters required by MarkdownV2. "
    "Do NOT include chain-of-thought or <think> tags; answer directly. "
    "Aim for clarity and style and you may use up to ~3500 characters."
)

# Shared HTTP session to keep the TCP connection warm
_SESSION: requests.Session | None = None

# Edit rate limiting to avoid Telegram flood control
EDIT_MIN_INTERVAL = 0.5  # seconds between edits per message
_LATEST_TEXT: dict[int, str] = {}
_LAST_EDIT_AT: dict[int, float] = {}
_FLUSH_TASKS: dict[int, asyncio.Task] = {}


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

        # Final update with complete response (MarkdownV2 with fallback)
        await _edit_text_markdown(msg, result)

    except Exception as e:
        logger.exception("Ollama request failed")
        await msg.edit_text(
            f"❌ Error: {html.escape(str(e))}\n\n"
            f"Host: <code>{html.escape(core.OLLAMA_HOST)}</code>\n"
            f"Model: <code>{html.escape(core.OLLAMA_MODEL)}</code>",
            parse_mode=ParseMode.HTML,
        )


async def _update_message(msg, text: str) -> None:
    """Coalesce edits and respect rate limits to avoid flood control."""
    mid = msg.message_id
    _LATEST_TEXT[mid] = text
    # If no flush task or finished, schedule one
    task = _FLUSH_TASKS.get(mid)
    if task is None or task.done():
        _FLUSH_TASKS[mid] = asyncio.create_task(_flush_update(msg))


async def _flush_update(msg) -> None:
    """Flush latest text with interval/backoff, handling flood control."""
    mid = msg.message_id
    try:
        while True:
            now = time.time()
            last = _LAST_EDIT_AT.get(mid, 0.0)
            wait = max(0.0, EDIT_MIN_INTERVAL - (now - last))
            if wait > 0:
                await asyncio.sleep(wait)

            text = _LATEST_TEXT.get(mid)
            if not text:
                break

            try:
                await _edit_text_markdown(msg, text)
                _LAST_EDIT_AT[mid] = time.time()
            except Exception as e:
                s = str(e)
                # Parse flood control hint: "Retry in N seconds"
                m = re.search(r"Retry in (\d+) seconds", s)
                if m:
                    delay = int(m.group(1))
                    await asyncio.sleep(delay)
                    continue
                # Other errors: break and let final update handle
                logger.debug("Edit error: %s", e)
                break

            # If no new text after edit, stop; otherwise loop to push latest
            if _LATEST_TEXT.get(mid) == text:
                break
    finally:
        _FLUSH_TASKS.pop(mid, None)


async def _edit_text_markdown(msg, text: str) -> None:
    """Try MarkdownV2, then Markdown, then HTML-escaped fallback."""
    try:
        await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN_V2)
        return
    except Exception:
        pass
    try:
        await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN)
        return
    except Exception:
        pass
    # Fallback: escape for HTML
    await msg.edit_text(html.escape(text), parse_mode=ParseMode.HTML)


def _get_session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
    return _SESSION


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
        "system": STYLE_SYSTEM_PROMPT,
        "temperature": OLLAMA_TEMP,
        "top_k": OLLAMA_TOP_K,
        "top_p": OLLAMA_TOP_P,
        "num_predict": OLLAMA_NUM_PREDICT,
        "repeat_penalty": 1.2,
    }

    accumulated: list[str] = []  # committed tokens
    pending: list[str] = []  # batch to flush on interval/size
    last_update = 0.0
    think_mode = False

    try:
        session = _get_session()
        with session.post(url, json=payload, stream=True, timeout=60) as resp:
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
                        pending.append(token)

                    # Periodically update the message (batch by time or token count)
                    now = time.time()
                    if (
                        callback
                        and pending
                        and (
                            len(pending) >= STREAM_MIN_TOKENS
                            or (now - last_update) >= STREAM_UPDATE_INTERVAL
                        )
                    ):
                        accumulated.extend(pending)
                        pending.clear()
                        current_text = _format_response(accumulated, done=False)
                        if current_text:
                            callback(current_text)
                        last_update = now

                if done:
                    break

        # Flush any remaining pending tokens
        if pending:
            accumulated.extend(pending)
            pending.clear()

        # Return final formatted response
        return _format_response(accumulated, done=True)

    except requests.RequestException as e:
        raise RuntimeError(f"Ollama request failed: {e}") from e


def _format_response(tokens: list[str], done: bool) -> str:
    """Format accumulated tokens for display."""
    text = "".join(tokens).strip()

    if not text:
        return "⏳ _thinking..._"

    # Light post-processing: escape MarkdownV2 special chars outside code
    text = _escape_markdown_v2_light(text)

    # Add typing indicator if not done (Markdown-friendly)
    if not done:
        text = f"{text}\n\n⏳"

    # Limit message length for Telegram
    if len(text) > 4000:
        text = text[:3900] + "\n\n_(truncated)_"

    return text


def _escape_markdown_v2_light(text: str) -> str:
    """Escape MarkdownV2 special characters while preserving formatting.

    - Skips escaping inside fenced (```) and inline (`...`) code.
    - Preserves `*` and `_` to allow bold/italic produced by the model.
    - Does not escape leading '-' used for bullet lists.
    - Escapes common troublemakers: []()~>#+=|{}.! and standalone '-'.
    """

    def escape_chunk(chunk: str) -> str:
        out = []
        i = 0
        start_of_line = True
        while i < len(chunk):
            ch = chunk[i]
            if ch == "\n":
                out.append(ch)
                start_of_line = True
                i += 1
                continue
            esc_set = set("[]()~>#+=|{}.!")
            # Hyphen: escape unless line-start bullet "- "
            if ch == "-":
                if not (start_of_line and i + 1 < len(chunk) and chunk[i + 1] == " "):
                    out.append("\\-")
                else:
                    out.append("-")
                start_of_line = False
                i += 1
                continue
            # Preserve * and _ for formatting
            if ch in esc_set:
                out.append("\\" + ch)
            else:
                out.append(ch)
            start_of_line = False
            i += 1
        return "".join(out)

    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text.startswith("```", i):
            # fenced code block
            end = text.find("```", i + 3)
            if end == -1:
                out.append(text[i:])
                break
            out.append(text[i : end + 3])
            i = end + 3
        elif text[i] == "`":
            # inline code
            end = text.find("`", i + 1)
            if end == -1:
                out.append(text[i:])
                break
            out.append(text[i : end + 1])
            i = end + 1
        else:
            # normal chunk until next backtick or fence
            next_fence = text.find("```", i)
            next_tick = text.find("`", i)
            next_stop = min(x for x in [next_fence, next_tick, n] if x != -1)
            chunk = text[i:next_stop]
            out.append(escape_chunk(chunk))
            i = next_stop
    return "".join(out)
