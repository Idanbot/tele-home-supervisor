from __future__ import annotations

import html
import logging
import re
import time

import pyotp
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from .. import config, services, view
from ..background import ensure_started
from ..commands import COMMANDS, GROUP_ORDER
from .common import (
    auth_ttl_seconds,
    get_state,
    guard,
    guard_sensitive,
    tracked_reply_photo,
)

logger = logging.getLogger(__name__)


def _render_help() -> str:
    by_group: dict[str, list[str]] = {}
    for spec in COMMANDS:
        line = (
            f"<code>{html.escape(spec.usage)}</code> – {html.escape(spec.description)}"
        )
        by_group.setdefault(spec.group, []).append(line)
    lines: list[str] = ["Hi! Commands:\n"]
    for group in GROUP_ORDER:
        entries = by_group.get(group, [])
        if not entries:
            continue
        lines.append(f"<b>{html.escape(group)}</b>")
        lines.extend(entries)
        lines.append("")
    return "\n".join(lines).strip()


def _escape_md_v2(text: str) -> str:
    return re.sub(r"([\\_*[\]()~`>#+\-=\|{}.!])", r"\\\1", text)


def _code(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("`", "\\`")
    return f"`{escaped}`"


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    try:
        ensure_started(context.application)
    except Exception as e:
        logger.debug("ensure_started failed: %s", e)
    await update.message.reply_text(_render_help(), parse_mode=ParseMode.HTML)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, context)


async def cmd_whoami(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    c = update.effective_chat
    u = update.effective_user
    username = f"@{u.username}" if u and u.username else "(no username)"
    msg = f"chat_id: {c.id}\nchat_type: {c.type}\nuser: {username}"
    await update.message.reply_text(msg)


async def cmd_version(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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


async def cmd_auth(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
    ttl = auth_ttl_seconds()
    expiry = time.time() + ttl
    state.grant_auth(user_id, expiry)
    hours = ttl / 3600
    if hours % 24 == 0 and hours >= 24:
        duration = f"{int(hours // 24)} day{'s' if hours // 24 != 1 else ''}"
    else:
        duration = f"{int(hours)} hour{'s' if int(hours) != 1 else ''}"
    await update.message.reply_text(f"✅ Authorized for {duration}.")


async def cmd_check_auth(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    if not config.BOT_AUTH_TOTP_SECRET:
        await update.message.reply_text("⛔ BOT_AUTH_TOTP_SECRET is not configured.")
        return
    user_id = update.effective_user.id
    state = get_state(context.application)
    expiry = state.auth_grants.get(user_id)
    now = time.time()
    if not expiry or expiry <= now:
        state.auth_grants.pop(user_id, None)
        await update.message.reply_text(
            "🔒 Not authenticated. Use /auth <code> to authenticate."
        )
        return
    remaining = expiry - now
    days, day_rem = divmod(int(remaining), 86400)
    hours, remainder = divmod(day_rem, 3600)
    minutes, seconds = divmod(remainder, 60)
    if days > 0:
        time_str = f"{days}d {hours}h {minutes}m"
    elif hours > 0:
        time_str = f"{hours}h {minutes}m"
    elif minutes > 0:
        time_str = f"{minutes}m {seconds}s"
    else:
        time_str = f"{seconds}s"
    await update.message.reply_text(f"✅ Authenticated. Expires in {time_str}.")


async def cmd_auth_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show all authenticated user IDs and expiry from the persistence file."""
    if not await guard_sensitive(update, context):
        return

    state = get_state(context.application)
    now = time.time()
    grants = state.auth_grants

    if not grants:
        await update.message.reply_text(
            "No active authentication grants found in memory."
        )
        return

    lines = ["🔐 <b>Active Auth Grants</b>\n"]
    for uid, expiry in sorted(grants.items(), key=lambda x: x[1]):
        if expiry <= now:
            continue

        exp_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(expiry))
        # We don't have start date stored, but we know it lasts 7 days
        # So start is roughly expiry - 7 days
        start_time = expiry - (config.BOT_AUTH_TTL_HOURS * 3600)
        start_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start_time))

        lines.append(f"👤 <code>{uid}</code>")
        lines.append(f"  🏁 Start: {html.escape(start_str)}")
        lines.append(f"  ⌛ End:   {html.escape(exp_str)}")
        lines.append("")

    msg = "\n".join(lines).strip()
    if not msg or msg == "🔐 <b>Active Auth Grants</b>":
        await update.message.reply_text("No active authentication grants found.")
    else:
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_metrics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard_sensitive(update, context):
        return
    state = get_state(context.application)
    metrics = state.command_metrics

    # Generate chart image
    chart = view.render_metrics_chart(metrics)
    if chart:
        caption = view.render_command_metrics(metrics)
        # Truncate caption if too long for photo caption (1024 chars)
        if len(caption) > 1000:
            caption = caption[:997] + "..."
        try:
            await tracked_reply_photo(
                update.message,
                state,
                photo=chart,
                caption=caption,
                parse_mode=ParseMode.HTML,
            )
            return
        except Exception as e:
            logger.warning("Failed to send metrics chart: %s", e)
            # Fall through to text-only response

    # Fallback to text-only
    msg = view.render_command_metrics(metrics)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_debug(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard_sensitive(update, context):
        return
    state = get_state(context.application)
    command = context.args[0].lower() if context.args else None
    data = state.get_debug(command)
    if not data:
        await update.message.reply_text("No debug entries.")
        return
    lines: list[str] = []
    for key in sorted(data.keys()):
        entries = data[key][-10:]
        lines.append(view.bold(f"Debug: {html.escape(key)}"))
        for entry in entries:
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(entry.timestamp))
            lines.append(f"{html.escape(ts)} - {html.escape(entry.message)}")
            if entry.details:
                detail = entry.details
                if len(detail) > 1200:
                    detail = f"{detail[:1200]}..."
                lines.append(view.pre(detail))
        lines.append("")
    msg = "\n".join(lines).strip()
    for part in view.chunk(msg, size=4000):
        await update.message.reply_text(part, parse_mode=ParseMode.HTML)
