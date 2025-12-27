"""AI/LLM handlers for Ollama integration."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, Tuple

import httpx
from telegram import Update
from telegram.constants import ParseMode
from telegram.error import RetryAfter
from telegram.ext import ContextTypes

from .. import config
from ..ai_service import OllamaClient
from ..utils import split_telegram_message
from .common import guard

logger = logging.getLogger(__name__)

STREAM_UPDATE_INTERVAL = 1.8
STREAM_MIN_TOKENS = 12
PULL_TIMEOUT_S = 1800.0
PULL_UPDATE_INTERVAL = 180.0
_OLLAMA_PULL_KEY = "ollama_pull_state"

STYLE_SYSTEM_PROMPT = (
    "Respond in Telegram MarkdownV2. Avoid HTML. "
    "Use fenced code blocks for code or quotes. Keep responses concise."
)


async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ask a question to the local Ollama model with streaming response."""
    if not await guard(update, context):
        return
    if await _ollama_busy_reply(update, context):
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
                # Construct current text
                current_raw = "".join(full_response)
                # Only stream edit if it fits in one message with some buffer
                if len(current_raw) <= 4000:
                    current_text = _format_text(current_raw, done=False)
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

        # Final delivery
        final_raw = "".join(full_response)

        # Split into chunks if needed
        chunks = split_telegram_message(final_raw)

        # Update the original message with the first chunk
        first_chunk = _format_text(chunks[0], done=True)
        first_chunk = _close_unbalanced_fences(first_chunk)

        try:
            await msg.edit_text(first_chunk, parse_mode=ParseMode.MARKDOWN_V2)
        except Exception as e:
            logger.warning("MarkdownV2 render failed for chunk 1; falling back: %s", e)
            await msg.edit_text(first_chunk)

        # Send subsequent chunks as replies
        for i, chunk in enumerate(chunks[1:], start=2):
            # Ensure fences are balanced for each independent message chunk
            # (split_telegram_message handles this, but _close_unbalanced_fences adds safety)
            chunk_fmt = _close_unbalanced_fences(chunk)
            try:
                await update.message.reply_text(
                    chunk_fmt, parse_mode=ParseMode.MARKDOWN_V2
                )
            except Exception as e:
                logger.warning(
                    f"MarkdownV2 render failed for chunk {i}; falling back: {e}"
                )
                await update.message.reply_text(chunk_fmt)

    except Exception as e:
        logger.exception("Ollama request failed")
        await msg.edit_text(
            f"❌ Error: {str(e)}\nHost: {host}",
        )


async def cmd_askreset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    if await _ollama_busy_reply(update, context):
        return
    context.user_data.pop("ollama_params", None)
    await update.message.reply_text("AI generation parameters reset to defaults.")


async def cmd_ollamahost(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    if await _ollama_busy_reply(update, context):
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
    if await _ollama_busy_reply(update, context):
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
    if await _ollama_busy_reply(update, context):
        return
    context.user_data.pop("ollama_host", None)
    context.user_data.pop("ollama_model", None)
    await update.message.reply_text("Ollama host/model reset to defaults.")


async def cmd_ollamashow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    if await _ollama_busy_reply(update, context):
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


async def cmd_ollamalist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    if await _ollama_busy_reply(update, context):
        return
    host, _ = _resolve_ollama_target(context.user_data)
    url = f"{host.rstrip('/')}/api/tags"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        logger.warning("Ollama list failed: %s", exc)
        await update.message.reply_text(f"❌ Failed to fetch models from {host}")
        return
    except ValueError as exc:
        logger.warning("Ollama list response invalid: %s", exc)
        await update.message.reply_text(f"❌ Invalid response from {host}")
        return

    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, list) or not models:
        await update.message.reply_text(f"No models found on {host}.")
        return

    max_items = 30
    lines = [f"Ollama models on {host}:"]
    for item in models[:max_items]:
        name = str(item.get("name") or "unknown")
        lines.append(f"- {name}")
    if len(models) > max_items:
        lines.append(f"...and {len(models) - max_items} more")
    await update.message.reply_text("\n".join(lines))


async def cmd_ollamapull(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    if await _ollama_busy_reply(update, context):
        return
    if not context.args:
        await update.message.reply_text("Usage: /ollamapull <model>")
        return

    model = " ".join(context.args).strip()
    if not model:
        await update.message.reply_text("Usage: /ollamapull <model>")
        return

    host, _ = _resolve_ollama_target(context.user_data)
    msg = await update.message.reply_text(
        f"Starting Ollama download: {model}\nHost: {host}"
    )

    app = context.application
    task = asyncio.create_task(_run_ollama_pull(app, msg, host, model))
    now = time.monotonic()
    app.bot_data[_OLLAMA_PULL_KEY] = {
        "task": task,
        "model": model,
        "host": host,
        "status": "starting",
        "total": None,
        "completed": None,
        "speed": None,
        "eta": None,
        "started_at": now,
        "last_update": now,
    }

    def _clear_task(_task: asyncio.Task) -> None:
        app.bot_data.pop(_OLLAMA_PULL_KEY, None)

    task.add_done_callback(_clear_task)


async def cmd_ollamastatus(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    state = _get_ollama_pull_state(context)
    if not state:
        await update.message.reply_text("No active Ollama download.")
        return
    await update.message.reply_text("\n".join(_format_pull_status(state)))


async def cmd_ollamacancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    state = _get_ollama_pull_state(context)
    if not state:
        await update.message.reply_text("No active Ollama download.")
        return
    task = state.get("task")
    if task is None or (getattr(task, "done", None) and task.done()):
        await update.message.reply_text("No active Ollama download.")
        return
    _update_pull_state(
        context.application,
        status="cancel_requested",
        last_update=time.monotonic(),
    )
    task.cancel()
    await update.message.reply_text(
        f"Cancel requested for {state.get('model', 'unknown')}."
    )


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


async def _ollama_busy_reply(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    state = _get_ollama_pull_state(context)
    if not state:
        return False
    model = state.get("model", "unknown")
    host = state.get("host", "unknown")
    status = state.get("status", "unknown")
    await update.message.reply_text(
        "Ollama is busy downloading a model.\n"
        f"Model: {model}\n"
        f"Host: {host}\n"
        f"Status: {status}\n"
        "Try again later or use /ollamastatus."
    )
    return True


def _get_ollama_pull_state(context: ContextTypes.DEFAULT_TYPE) -> Dict[str, Any] | None:
    app = getattr(context, "application", None)
    if app is None:
        return None
    state = app.bot_data.get(_OLLAMA_PULL_KEY)
    if not isinstance(state, dict):
        return None
    task = state.get("task")
    if task is not None and getattr(task, "done", None) and task.done():
        return None
    return state


def _update_pull_state(app, **updates: Any) -> None:
    state = app.bot_data.get(_OLLAMA_PULL_KEY)
    if not isinstance(state, dict):
        return
    for key, value in updates.items():
        if value is None:
            continue
        state[key] = value


def _format_pull_status(state: Dict[str, Any]) -> list[str]:
    model = state.get("model", "unknown")
    host = state.get("host", "unknown")
    status = state.get("status", "unknown")
    lines = [
        f"Ollama pull: {model}",
        f"Host: {host}",
        f"Status: {status}",
    ]
    total = state.get("total")
    completed = state.get("completed")
    if isinstance(total, int) and isinstance(completed, int):
        percent = (completed / total) * 100 if total else 0
        lines.append(
            "Progress: "
            f"{percent:.1f}% "
            f"({_format_bytes(completed)} / {_format_bytes(total)})"
        )
    speed = state.get("speed")
    if isinstance(speed, (int, float)) and speed > 0:
        lines.append(f"Speed: {speed / 1024:.1f} KiB/s")
    eta = state.get("eta")
    if isinstance(eta, (int, float)):
        lines.append(f"ETA: {_format_eta(eta)}")
    started_at = state.get("started_at")
    if isinstance(started_at, (int, float)):
        elapsed = time.monotonic() - started_at
        lines.append(f"Elapsed: {_format_eta(elapsed)}")
    return lines


def _format_bytes(value: float | int | None) -> str:
    if value is None:
        return "?"
    size = float(value)
    units = ["B", "KiB", "MiB", "GiB"]
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} GiB"


def _format_eta(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "?"
    remaining = int(seconds)
    minutes, secs = divmod(remaining, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


async def _safe_edit_status(app, message, text: str):
    try:
        await message.edit_text(text)
        return message
    except Exception as exc:
        logger.debug("Status edit failed: %s", exc)
        try:
            chat_id = getattr(message, "chat_id", None)
            if chat_id is None and getattr(message, "chat", None):
                chat_id = message.chat.id
            if chat_id is None:
                return message
            return await app.bot.send_message(chat_id=chat_id, text=text)
        except Exception as send_exc:
            logger.debug("Status send failed: %s", send_exc)
            return message


async def _run_ollama_pull(app, message, host: str, model: str) -> None:
    url = f"{host.rstrip('/')}/api/pull"
    payload = {"name": model}
    timeout = httpx.Timeout(PULL_TIMEOUT_S, connect=10.0, read=PULL_TIMEOUT_S)
    last_update = 0.0
    last_completed: int | None = None
    last_time = time.monotonic()
    status = "starting"

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    status = data.get("status", status)
                    total = data.get("total")
                    completed = data.get("completed")
                    now = time.monotonic()
                    speed = None
                    eta = None
                    if isinstance(total, int) and isinstance(completed, int):
                        if last_completed is not None and now > last_time:
                            speed = (completed - last_completed) / (now - last_time)
                            if speed > 0:
                                eta = (total - completed) / speed
                            else:
                                speed = None
                        last_completed = completed
                        last_time = now

                    _update_pull_state(
                        app,
                        status=status,
                        total=total if isinstance(total, int) else None,
                        completed=completed if isinstance(completed, int) else None,
                        speed=speed,
                        eta=eta,
                        last_update=now,
                    )

                    if now - last_update >= PULL_UPDATE_INTERVAL:
                        state = app.bot_data.get(_OLLAMA_PULL_KEY)
                        if isinstance(state, dict):
                            lines = _format_pull_status(state)
                        else:
                            lines = [
                                f"Ollama pull: {model}",
                                f"Status: {status}",
                            ]
                        message = await _safe_edit_status(
                            app, message, "\n".join(lines)
                        )
                        last_update = now

                    if status == "success":
                        break

        _update_pull_state(
            app,
            status="success",
            last_update=time.monotonic(),
        )
        await _safe_edit_status(
            app,
            message,
            "\n".join([f"Ollama pull complete: {model}", f"Host: {host}"]),
        )

    except asyncio.CancelledError:
        _update_pull_state(
            app,
            status="cancelled",
            last_update=time.monotonic(),
        )
        await _safe_edit_status(
            app,
            message,
            "\n".join([f"❌ Ollama pull cancelled: {model}", f"Host: {host}"]),
        )
        raise
    except httpx.HTTPError as exc:
        logger.warning("Ollama pull failed: %s", exc)
        _update_pull_state(
            app,
            status="failed",
            last_update=time.monotonic(),
        )
        await _safe_edit_status(
            app,
            message,
            f"❌ Ollama pull failed for {model}\nHost: {host}",
        )
    except Exception as exc:
        logger.exception("Ollama pull error: %s", exc)
        _update_pull_state(
            app,
            status="failed",
            last_update=time.monotonic(),
        )
        await _safe_edit_status(
            app,
            message,
            f"❌ Ollama pull error for {model}\nHost: {host}",
        )
