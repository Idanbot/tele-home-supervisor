"""AI/LLM handlers for Ollama integration."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Tuple

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import RetryAfter
from telegram.ext import ContextTypes

from .. import config
from ..ai_service import OllamaClient
from .common import guard

logger = logging.getLogger(__name__)

STREAM_UPDATE_INTERVAL = 1.8
STREAM_MIN_TOKENS = 12

STYLE_SYSTEM_PROMPT = (
    "Respond in Telegram MarkdownV2. Avoid HTML. "
    "Use fenced code blocks for code or quotes. Keep responses concise."
)


async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ask a question to the local Ollama model with streaming response."""
    if not await guard(update, context):
        return

    prompt, overrides = _parse_generation_flags(context.args, context.user_data)
    host, model = _resolve_ollama_target(context.user_data)

    if not prompt:
        await update.message.reply_text(
            "Usage: /ask <your question> [--temp 0.4 --top-k 40 --top-p 0.9 --num-predict 640]\n"
            f"Model: {model}\n"
            f"Host: {host}\n"
            "Tips: /askreset clears params, /ollamareset clears host/model",
        )
        return

    msg = await update.message.reply_text("🤔 Thinking...")

    client = OllamaClient(
        base_url=host,
        model=model,
        system_prompt=STYLE_SYSTEM_PROMPT,
        **overrides,
    )

    full_response = []
    pending_tokens = []
    last_update_time = time.time()
    think_mode = False
    last_sent_text = ""

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
                current_text = _format_text("".join(full_response), done=False)
                if current_text != last_sent_text:
                    try:
                        await msg.edit_text(current_text)
                        last_sent_text = current_text
                        pending_tokens.clear()
                        last_update_time = now
                    except RetryAfter as e:
                        # Respect Telegram flood control by backing off
                        await asyncio.sleep(e.retry_after)
                    except Exception as e:
                        logger.debug("Stream edit skipped: %s", e)
                        if "Retry in" in str(e):
                            await asyncio.sleep(1)

        final_text = _format_text("".join(full_response), done=True)
        final_text = _close_unbalanced_fences(final_text)
        try:
            await msg.edit_text(final_text, parse_mode=ParseMode.MARKDOWN_V2)
        except Exception as e:
            logger.warning(
                "MarkdownV2 render failed; falling back to plain text: %s", e
            )
            await msg.edit_text(final_text)

    except Exception as e:
        logger.exception("Ollama request failed")
        await msg.edit_text(
            f"❌ Error: {str(e)}\nHost: {config.OLLAMA_HOST}",
        )


async def cmd_askreset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    context.user_data.pop("ollama_params", None)
    await update.message.reply_text("AI generation parameters reset to defaults.")


async def cmd_ollamahost(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    if not context.args:
        host, _ = _resolve_ollama_target(context.user_data)
        await update.message.reply_text(
            f"Usage: /ollamahost <http://host:port>\nCurrent host: {host}",
        )
        return
    host = context.args[0].strip()
    if "://" not in host:
        await update.message.reply_text(
            "Usage: /ollamahost <http://host:port>\n"
            "Example: /ollamahost http://192.168.1.20:11434",
        )
        return
    context.user_data["ollama_host"] = host
    await update.message.reply_text(f"Ollama host set to: {host}")


async def cmd_ollamamodel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    if not context.args:
        _, model = _resolve_ollama_target(context.user_data)
        await update.message.reply_text(
            f"Usage: /ollamamodel <model>\nCurrent model: {model}"
        )
        return
    model = " ".join(context.args).strip()
    if not model:
        await update.message.reply_text("Usage: /ollamamodel <model>")
        return
    context.user_data["ollama_model"] = model
    await update.message.reply_text(f"Ollama model set to: {model}")


async def cmd_ollamareset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    context.user_data.pop("ollama_host", None)
    context.user_data.pop("ollama_model", None)
    await update.message.reply_text("Ollama host/model reset to defaults.")


async def cmd_ollamashow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    host, model = _resolve_ollama_target(context.user_data)
    host_override = context.user_data.get("ollama_host")
    model_override = context.user_data.get("ollama_model")
    lines = [
        "Ollama settings:",
        f"Host: {host}",
        f"Model: {model}",
    ]
    if host_override or model_override:
        lines.append("Overrides:")
        lines.append(f"Host override: {host_override or 'none'}")
        lines.append(f"Model override: {model_override or 'none'}")
    await update.message.reply_text("\n".join(lines))


def _format_text(text: str, done: bool) -> str:
    text = text.strip()

    if not text:
        return "⏳ thinking..."

    if not done:
        if not text.endswith(" "):
            text += " "
        text += "▌"

    return text


def _close_unbalanced_fences(text: str) -> str:
    if text.count("```") % 2 == 1:
        return f"{text}\n```"
    return text


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _parse_generation_flags(
    args: list[str], user_data: Dict[str, Any]
) -> Tuple[str, Dict[str, Any]]:
    overrides: Dict[str, Any] = dict(user_data.get("ollama_params", {}))
    prompt_parts: list[str] = []
    i = 0

    while i < len(args):
        token = args[i]
        if token in {"--temp", "-t"} and i + 1 < len(args):
            try:
                val = float(args[i + 1])
                overrides["temp"] = _clamp(val, 0.1, 1.2)
                i += 2
                continue
            except ValueError:
                pass
        if token in {"--top-k", "-k"} and i + 1 < len(args):
            try:
                val = int(args[i + 1])
                overrides["top_k"] = int(_clamp(val, 10, 200))
                i += 2
                continue
            except ValueError:
                pass
        if token in {"--top-p", "-p"} and i + 1 < len(args):
            try:
                val = float(args[i + 1])
                overrides["top_p"] = _clamp(val, 0.5, 1.0)
                i += 2
                continue
            except ValueError:
                pass
        if token in {"--num-predict", "-n"} and i + 1 < len(args):
            try:
                val = int(args[i + 1])
                overrides["num_predict"] = int(_clamp(val, 64, 640))
                i += 2
                continue
            except ValueError:
                pass

        prompt_parts.append(token)
        i += 1

    user_data["ollama_params"] = overrides
    return " ".join(prompt_parts).strip(), overrides


def _resolve_ollama_target(user_data: Dict[str, Any]) -> Tuple[str, str]:
    host = user_data.get("ollama_host") or config.OLLAMA_HOST
    model = user_data.get("ollama_model") or config.OLLAMA_MODEL
    return str(host), str(model)
