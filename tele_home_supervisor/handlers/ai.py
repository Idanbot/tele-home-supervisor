"""AI/LLM handlers for Ollama integration."""

from __future__ import annotations

import asyncio
import html
import json
import logging
import time
from io import BytesIO
from typing import Any

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import RetryAfter
from telegram.ext import ContextTypes

from .. import config
from ..ai_delivery import build_streaming_delivery
from ..ai_service import GenerationTarget, create_text_provider
from ..models.bot_state import CFRunRecord
from ..orange_echo import (
    FALLBACK_MODELS,
    FALLBACK_VOICE_PRESETS,
    ModelChoice,
    OrangeEchoClient,
    OrangeEchoError,
    VoicePreset,
    track_cf_action,
)
from ..utils import split_telegram_message
from .common import get_state, guard, tracked_reply_photo, tracked_reply_voice

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
    """Ask a question using the active AI provider with streaming response."""
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

    delivery = build_streaming_delivery(update, context)
    provider = create_text_provider(
        _resolve_generation_target(
            user_data=context.user_data,
            system_prompt=STYLE_SYSTEM_PROMPT,
            overrides=overrides,
        )
    )

    full_response = []
    pending_tokens = []
    last_update_time = time.time()
    think_mode = False
    last_sent_text = ""

    try:
        async for token in provider.generate_stream(prompt):
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
                            await delivery.push(current_text)
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

        first_chunk = _close_unbalanced_fences(_format_text(chunks[0], done=True))
        final_chunks = [
            first_chunk,
            *(_close_unbalanced_fences(chunk) for chunk in chunks[1:]),
        ]
        await delivery.finalize(final_chunks)

    except Exception as e:
        logger.exception("Ollama request failed")
        await delivery.error(f"❌ Error: {str(e)}\nHost: {host}")


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
    args: list[str], user_data: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    overrides: dict[str, Any] = dict(user_data.get("ollama_params", {}))
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


def _resolve_ollama_target(user_data: dict[str, Any]) -> tuple[str, str]:
    host = user_data.get("ollama_host") or config.OLLAMA_HOST
    model = user_data.get("ollama_model") or config.OLLAMA_MODEL
    return str(host), str(model)


def _resolve_generation_target(
    *,
    user_data: dict[str, Any],
    system_prompt: str,
    overrides: dict[str, Any],
) -> GenerationTarget:
    host, model = _resolve_ollama_target(user_data)
    return GenerationTarget(
        provider=str(user_data.get("ai_provider") or "ollama"),
        model=model,
        base_url=host,
        system_prompt=system_prompt,
        options=dict(overrides),
    )


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


def _get_ollama_pull_state(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any] | None:
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


def _format_pull_status(state: dict[str, Any]) -> list[str]:
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


async def extract_text_prompt(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> str:
    """Extract text prompt from command args or replied text message/file."""
    if context.args:
        return " ".join(context.args).strip()

    reply = update.message.reply_to_message if update and update.message else None
    if reply:
        if reply.document:
            try:
                tg_file = await context.bot.get_file(reply.document.file_id)
                data = await tg_file.download_as_bytearray()
                return data.decode("utf-8", errors="replace").strip()
            except Exception as e:
                logger.warning(
                    "Failed to download or decode text file from reply: %s", e
                )
                return ""
        if reply.text:
            return reply.text.strip()
        if reply.caption:
            return reply.caption.strip()


async def cmd_cftts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate speech audio via Cloudflare Workers AI."""
    if not await guard(update, context):
        return

    prompt = await extract_text_prompt(update, context)
    if not prompt:
        await update.message.reply_text(
            "Usage: /cftts <prompt> (or reply to a text message or file)"
        )
        return

    if not config.ORANGE_ECHO_API_KEY:
        await update.message.reply_text(
            "❌ ORANGE_ECHO_API_KEY environment variable is not configured."
        )
        return

    if len(prompt) > 1600:
        prompt = prompt[:1600]

    status_msg = await update.message.reply_text(
        "🔄 Synthesizing speech via Cloudflare AI..."
    )

    client = OrangeEchoClient(
        base_url=config.ORANGE_ECHO_BASE_URL,
        api_key=config.ORANGE_ECHO_API_KEY,
    )
    try:
        state = get_state(context.application)
        model = state.get_cf_model(update.effective_chat.id, "speech")
        voice_preset = state.get_cf_voice(update.effective_chat.id)
        audio_bytes = await track_cf_action(
            client,
            state,
            "TTS (/cftts)",
            client.synthesize(prompt, model=model, voice_preset=voice_preset),
        )
        voice_file = BytesIO(audio_bytes)
        voice_file.name = "speech.ogg"

        if status_msg:
            try:
                await status_msg.delete()
            except Exception as exc:
                logger.debug("Failed to delete status message: %s", exc)

        await tracked_reply_voice(
            update.message,
            state,
            voice=voice_file,
            caption=f"🗣️ Cloudflare TTS · {model}/{voice_preset} ({len(prompt)} chars)",
        )
    except OrangeEchoError as e:
        logger.warning("Cloudflare TTS API error: %s", e)
        error_text = e.user_friendly_message()
        if status_msg:
            await status_msg.edit_text(error_text, parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text(error_text, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.exception("Cloudflare TTS failed: %s", e)
        error_text = f"❌ <b>Cloudflare TTS failed</b>: {html.escape(str(e))}"
        if status_msg:
            await status_msg.edit_text(error_text, parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text(error_text, parse_mode=ParseMode.HTML)

    finally:
        await client.close()


async def cmd_cfimagegen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate an image via Cloudflare Workers AI."""
    if not await guard(update, context):
        return

    prompt = await extract_text_prompt(update, context)
    if not prompt:
        await update.message.reply_text(
            "Usage: /cfimagegen <prompt> (or reply to a text message or file)"
        )
        return

    if not config.ORANGE_ECHO_API_KEY:
        await update.message.reply_text(
            "❌ ORANGE_ECHO_API_KEY environment variable is not configured."
        )
        return

    if len(prompt) > 2048:
        prompt = prompt[:2048]

    status_msg = await update.message.reply_text(
        "🎨 Generating image via Cloudflare AI..."
    )

    client = OrangeEchoClient(
        base_url=config.ORANGE_ECHO_BASE_URL,
        api_key=config.ORANGE_ECHO_API_KEY,
    )
    try:
        state = get_state(context.application)
        model = state.get_cf_model(update.effective_chat.id, "image")
        generated = await track_cf_action(
            client,
            state,
            "ImageGen (/cfimagegen)",
            client.generate_image(prompt, model=model),
        )
        suffix = {
            "image/jpeg": "jpg",
            "image/png": "png",
            "image/webp": "webp",
        }.get(generated.mime_type, "jpg")

        photo_file = BytesIO(generated.content)
        photo_file.name = f"image.{suffix}"

        state = get_state(context.application)
        if status_msg:
            try:
                await status_msg.delete()
            except Exception as exc:
                logger.debug("Failed to delete status message: %s", exc)

        caption = f"🎨 Model: {generated.model}\nPrompt: {prompt[:200]}"
        await tracked_reply_photo(
            update.message,
            state,
            photo=photo_file,
            caption=caption,
        )
    except OrangeEchoError as e:
        logger.warning("Cloudflare ImageGen API error: %s", e)
        error_text = e.user_friendly_message()
        if status_msg:
            await status_msg.edit_text(error_text, parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text(error_text, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.exception("Cloudflare ImageGen failed: %s", e)
        error_text = f"❌ <b>Cloudflare ImageGen failed</b>: {html.escape(str(e))}"
        if status_msg:
            await status_msg.edit_text(error_text, parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text(error_text, parse_mode=ParseMode.HTML)

    finally:
        await client.close()


def _relative_rating(value: float) -> str:
    return f"{value:g}"


def build_cf_models_keyboard(
    state, chat_id: int, catalog: dict[str, list[ModelChoice]]
) -> InlineKeyboardMarkup:
    """Build both model selectors through one shared renderer."""
    rows: list[list[InlineKeyboardButton]] = []
    for kind, icon in (("speech", "🗣️"), ("image", "🎨")):
        selected = state.get_cf_model(chat_id, kind)
        for choice in catalog.get(kind, []):
            marker = "✅" if choice.alias == selected else icon
            quality = _relative_rating(choice.relative_quality)
            rows.append(
                [
                    InlineKeyboardButton(
                        f"{marker} {choice.label} · "
                        f"~{choice.estimated_neurons_at_limit:,} neurons · {quality}Q",
                        callback_data=f"cfmodel:{kind}:{choice.alias}",
                    )
                ]
            )
    return InlineKeyboardMarkup(rows)


async def _load_cf_model_catalog(
    client: OrangeEchoClient,
) -> dict[str, list[ModelChoice]]:
    try:
        catalog = await client.get_models()
        if catalog.get("speech") and catalog.get("image"):
            return catalog
    except Exception as exc:
        logger.warning("Using fallback Cloudflare model catalog: %s", exc)
    return FALLBACK_MODELS


async def _load_cf_voice_presets(client: OrangeEchoClient) -> list[VoicePreset]:
    try:
        presets = await client.get_voice_presets()
        if presets:
            return presets
    except Exception as exc:
        if isinstance(exc, OrangeEchoError) and exc.code == "not_found":
            logger.info("Cloudflare worker has no voice preset catalog yet")
        else:
            logger.warning("Using fallback Cloudflare voice presets: %s", exc)
    return FALLBACK_VOICE_PRESETS


def build_cf_voice_keyboard(
    state, chat_id: int, presets: list[VoicePreset]
) -> InlineKeyboardMarkup:
    selected = state.get_cf_voice(chat_id)
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"{'✅' if preset.alias == selected else '🗣️'} "
                    f"{preset.label} · {preset.accent}",
                    callback_data=f"cfvoice:{preset.alias}",
                )
            ]
            for preset in presets
        ]
    )


async def cmd_cfmodels(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Select persistent Cloudflare speech and image models."""
    if not await guard(update, context):
        return
    state = get_state(context.application)
    client = OrangeEchoClient(
        base_url=config.ORANGE_ECHO_BASE_URL,
        api_key=config.ORANGE_ECHO_API_KEY,
    )
    try:
        catalog = await _load_cf_model_catalog(client)
        await update.message.reply_text(
            "Cloudflare AI models\nNeurons = estimated use at limit · Q = relative quality",
            reply_markup=build_cf_models_keyboard(
                state, update.effective_chat.id, catalog
            ),
        )
    finally:
        await client.close()


async def cmd_cfvoice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Select a persistent Aura news voice preset and matching model."""
    if not await guard(update, context):
        return
    state = get_state(context.application)
    client = OrangeEchoClient(
        base_url=config.ORANGE_ECHO_BASE_URL,
        api_key=config.ORANGE_ECHO_API_KEY,
    )
    try:
        presets = await _load_cf_voice_presets(client)
        await update.message.reply_text(
            "Aura news voice\nSelecting a preset also selects its matching model.",
            reply_markup=build_cf_voice_keyboard(
                state, update.effective_chat.id, presets
            ),
        )
    finally:
        await client.close()


async def handle_cf_model_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    parts = (query.data or "").split(":", 2)
    if len(parts) != 3 or parts[1] not in {"speech", "image"}:
        await query.edit_message_text("Invalid Cloudflare model selection.")
        return
    _, kind, alias = parts
    state = get_state(context.application)
    client = OrangeEchoClient(
        base_url=config.ORANGE_ECHO_BASE_URL,
        api_key=config.ORANGE_ECHO_API_KEY,
    )
    try:
        catalog = await _load_cf_model_catalog(client)
        choices = catalog.get(kind, [])
        if alias not in {choice.alias for choice in choices}:
            await query.edit_message_text("That model is no longer available.")
            return
        if kind == "speech":
            default_voice = "angus" if alias == "balanced" else "luna"
            state.set_cf_voice_preset(update.effective_chat.id, default_voice, alias)
        else:
            state.set_cf_model(update.effective_chat.id, kind, alias)
        await query.edit_message_text(
            "Cloudflare AI models\nNeurons = estimated use at limit · Q = relative quality",
            reply_markup=build_cf_models_keyboard(
                state, update.effective_chat.id, catalog
            ),
        )
    finally:
        await client.close()


async def handle_cf_voice_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    _, _, alias = (query.data or "").partition(":")
    if not alias:
        await query.edit_message_text("Invalid Cloudflare voice selection.")
        return
    state = get_state(context.application)
    if state.get_cf_voice(update.effective_chat.id) == alias:
        return
    client = OrangeEchoClient(
        base_url=config.ORANGE_ECHO_BASE_URL,
        api_key=config.ORANGE_ECHO_API_KEY,
    )
    try:
        presets = await _load_cf_voice_presets(client)
        if alias not in {preset.alias for preset in presets}:
            await query.edit_message_text("That voice preset is no longer available.")
            return
        preset = next(preset for preset in presets if preset.alias == alias)
        state.set_cf_voice_preset(
            update.effective_chat.id, preset.alias, preset.model_alias
        )
        await query.edit_message_text(
            "Aura news voice\nSelecting a preset also selects its matching model.",
            reply_markup=build_cf_voice_keyboard(
                state, update.effective_chat.id, presets
            ),
        )
    finally:
        await client.close()


def _format_allowances_json(
    data: dict[str, object],
    recent_logs: list[CFRunRecord] | None = None,
    averages: dict[str, tuple[float, int]] | None = None,
) -> str:
    """Format allowances dictionary into a readable Telegram HTML message with averages and local run logs."""
    lines = [
        "📊 <b>Cloudflare Workers AI Allowances & Usage</b>",
        "<i>Free tier provides 10,000 Neurons daily (resets 00:00 UTC).</i>\n",
    ]

    reset_info = ""
    reset_in = data.get("reset_in")
    if isinstance(reset_in, dict) and "formatted" in reset_in:
        reset_info = f"Resets in: {html.escape(str(reset_in['formatted']))}"

    target_dict = data
    if "allowances" in data and isinstance(data["allowances"], dict):
        target_dict = data["allowances"]

    for key, value in target_dict.items():
        label = html.escape(key.replace("_", " ").title())
        if isinstance(value, dict):
            used = value.get("used")
            limit = value.get("limit")
            remaining = value.get("remaining")
            unit = "neurons" if "neuron" in key.lower() else "uses"
            details = []
            if used is not None and limit is not None:
                details.append(
                    f"{_format_allowance_count(used)} / "
                    f"{_format_allowance_count(limit)} {unit}"
                )
            elif used is not None:
                details.append(f"used: {_format_allowance_count(used)} {unit}")
            if remaining is not None:
                details.append(
                    f"remaining: {_format_allowance_count(remaining)} {unit}"
                )

            if not details:
                details = [f"{k}: {v}" for k, v in value.items()]

            lines.append(
                f"• <b>{label}</b>: {html.escape(', '.join(str(d) for d in details))}"
            )
        elif key not in ("date", "reset_at", "reset_in"):
            lines.append(f"• <b>{label}</b>: <code>{html.escape(str(value))}</code>")

    if reset_info:
        lines.append(f"\n⏳ <b>Reset Window</b>: <code>{reset_info}</code>")

    if len(lines) <= 2:
        lines.append("No detailed allowance breakdown returned by Worker.")

    if averages:
        lines.append("\n📈 <b>Average Neurons per Command (Last 5 Runs):</b>")
        for action, (avg, count) in averages.items():
            lines.append(
                f"• <b>{html.escape(action)}</b>: <code>~{avg:,.1f} neurons/run</code> ({count} samples)"
            )

    if recent_logs:
        lines.append("\n🕒 <b>Recent Cloudflare Runs (Last 5):</b>")
        for rec in reversed(recent_logs[-5:]):
            lines.append(
                f"• <b>{rec.timestamp}</b> — {html.escape(rec.action)}: "
                f"<code>+{rec.neurons_used:,} neurons</code> (Total: {rec.total_used_after:,})"
            )

    return "\n".join(lines)


def _format_allowance_count(value: object) -> str:
    """Format numeric API values while tolerating string-valued JSON fields."""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    try:
        return f"{int(str(value)):,}"
    except ValueError:
        return str(value)


async def cmd_cfusage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check Cloudflare Workers AI usage and daily allowances."""
    if not await guard(update, context):
        return

    if not config.ORANGE_ECHO_API_KEY:
        await update.message.reply_text(
            "❌ ORANGE_ECHO_API_KEY environment variable is not configured."
        )
        return

    status_msg = await update.message.reply_text(
        "🔄 Fetching Cloudflare AI allowances..."
    )

    client = OrangeEchoClient(
        base_url=config.ORANGE_ECHO_BASE_URL,
        api_key=config.ORANGE_ECHO_API_KEY,
    )
    try:
        state = get_state(context.application)
        data = await client.get_allowances()
        recent_logs = state.get_recent_cf_run_logs(5)
        averages = state.get_cf_command_averages(5)
        message_text = _format_allowances_json(
            data, recent_logs=recent_logs, averages=averages
        )
        if status_msg:
            await status_msg.edit_text(message_text, parse_mode=ParseMode.HTML)

        else:
            await update.message.reply_text(message_text, parse_mode=ParseMode.HTML)
    except OrangeEchoError as e:
        logger.warning("Cloudflare allowances API error: %s", e)
        error_text = e.user_friendly_message()
        if status_msg:
            await status_msg.edit_text(error_text, parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text(error_text, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.exception("Failed to fetch Cloudflare allowances: %s", e)
        error_text = f"❌ <b>Failed to fetch allowances</b>: {html.escape(str(e))}"
        if status_msg:
            await status_msg.edit_text(error_text, parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text(error_text, parse_mode=ParseMode.HTML)

    finally:
        await client.close()
