from __future__ import annotations

import logging
import re
import time

import pyotp
from telegram.constants import ParseMode

from .. import config, services, view
from ..background import ensure_started
from ..commands import COMMANDS, GROUP_ORDER
from .common import auth_ttl_seconds, get_state, guard, guard_sensitive

logger = logging.getLogger(__name__)


def _render_help() -> str:
    by_group: dict[str, list[str]] = {}
    for spec in COMMANDS:
        line = f"{spec.usage} – {spec.description}"
        by_group.setdefault(spec.group, []).append(line)
    lines: list[str] = ["Hi! Commands:\n"]
    for group in GROUP_ORDER:
        entries = by_group.get(group, [])
        if not entries:
            continue
        lines.append(group)
        lines.extend(entries)
        lines.append("")
    return "\n".join(lines).strip()


def _escape_md_v2(text: str) -> str:
    return re.sub(r"([\\_*[\]()~`>#+\-=\|{}.!])", r"\\\1", text)


def _code(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("`", "\\`")
    return f"`{escaped}`"


async def cmd_start(update, context) -> None:
    if not await guard(update, context):
        return
    try:
        ensure_started(context.application)
    except Exception as e:
        logger.debug("ensure_started failed: %s", e)
    await update.message.reply_text(_render_help())


async def cmd_help(update, context) -> None:
    await cmd_start(update, context)


async def cmd_whoami(update, context) -> None:
    c = update.effective_chat
    u = update.effective_user
    username = f"@{u.username}" if u and u.username else "(no username)"
    msg = f"chat_id: {c.id}\nchat_type: {c.type}\nuser: {username}"
    await update.message.reply_text(msg)


async def cmd_version(update, context) -> None:
    if not await guard(update, context):
        return
    try:
        info = await services.get_version_info()
        lines = ["*Version Info*"]

        def add(label: str, key: str) -> None:
            val = info.get(key)
            if val:
                lines.append(f"• {_escape_md_v2(label)}: {_code(val)}")

        add("Build", "build")
        add("Deployed", "started")
        add("Run Number", "run_number")
        add("Run ID", "run_id")
        add("Workflow", "workflow")
        add("Repository", "repository")
        add("Ref", "ref_name")
        add("Commit", "commit_hash")
        add("Commit Time", "last_commit")
        add("Image", "image")
        add("Image Tag", "image_tag")
        add("Image Digest", "image_digest")
        add("Python", "python")
        add("Host", "host")

        msg = "\n".join(lines)
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        logger.exception("Version command failed")
        await update.message.reply_text(f"❌ Error getting version info: {e}")


async def cmd_auth(update, context) -> None:
    if not await guard(update, context):
        return
    if not config.BOT_AUTH_TOTP_SECRET:
        await update.message.reply_text("⛔ BOT_AUTH_TOTP_SECRET is not configured.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /auth <code>")
        return
    provided = "".join(context.args).strip().replace("-", "")
    if not provided.isdigit():
        await update.message.reply_text("❌ Invalid auth code.")
        return
    try:
        totp = pyotp.TOTP(config.BOT_AUTH_TOTP_SECRET)
        valid = totp.verify(provided, valid_window=1)
    except Exception as e:
        logger.exception("TOTP validation failed")
        await update.message.reply_text(f"❌ Auth error: {e}")
        return
    if not valid:
        await update.message.reply_text("❌ Invalid auth code.")
        return
    state = get_state(context.application)
    user_id = update.effective_user.id
    expiry = time.monotonic() + auth_ttl_seconds()
    state.auth_grants[user_id] = expiry
    await update.message.reply_text("✅ Authorized for 24 hours.")


async def cmd_metrics(update, context) -> None:
    if not await guard_sensitive(update, context):
        return
    state = get_state(context.application)
    msg = view.render_command_metrics(state.command_metrics)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
