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
    guard_owner,
    guard_sensitive,
    tracked_reply_photo,
)

logger = logging.getLogger(__name__)
_FAILED_AUTH_LIMIT = 5
_FAILED_AUTH_COOLDOWN_S = 3600.0


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
    state = get_state(context.application)
    user_id = update.effective_user.id
    cooldown_until = state.auth_cooldown_until(user_id)
    if cooldown_until is not None:
        remaining = max(0, int(cooldown_until - time.time()))
        minutes, seconds = divmod(remaining, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            cooldown_text = f"{hours}h {minutes}m"
        elif minutes:
            cooldown_text = f"{minutes}m {seconds}s"
        else:
            cooldown_text = f"{seconds}s"
        await update.message.reply_text(
            f"⏳ Too many failed auth attempts. Try again in {cooldown_text}."
        )
        return
    provided = "".join(context.args).strip().replace("-", "")
    if not provided.isdigit():
        cooldown_until = await _handle_failed_auth(
            update, context, state, reason="non-digit auth code"
        )
        if cooldown_until is not None:
            await update.message.reply_text(
                "⏳ Too many failed auth attempts. Try again in 1h 0m."
            )
        else:
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
        cooldown_until = await _handle_failed_auth(
            update, context, state, reason="invalid TOTP code"
        )
        if cooldown_until is not None:
            await update.message.reply_text(
                "⏳ Too many failed auth attempts. Try again in 1h 0m."
            )
        else:
            await update.message.reply_text("❌ Invalid auth code.")
        return
    ttl = auth_ttl_seconds()
    granted_at = time.time()
    expiry = granted_at + ttl
    user = update.effective_user
    full_name = " ".join(
        part
        for part in (
            getattr(user, "first_name", "") or "",
            getattr(user, "last_name", "") or "",
        )
        if part
    ).strip()
    state.grant_auth(
        user_id,
        expiry,
        granted_at=granted_at,
        username=getattr(user, "username", None),
        user_name=full_name or getattr(user, "username", None),
    )
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
        state.revoke_auth(user_id)
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
    state.prune_expired_auth()
    records = sorted(state.auth_records.values(), key=lambda record: record.expires_at)
    if not records:
        records = [
            state.auth_record_for(uid)
            for uid in sorted(state.auth_grants)
            if state.auth_record_for(uid) is not None
        ]

    if not records:
        await update.message.reply_text(
            "No active authentication grants found in memory."
        )
        return

    lines = ["🔐 <b>Active Auth Grants</b>\n"]
    for record in records:
        if record is None:
            continue
        start_str = time.strftime(
            "%Y-%m-%d %H:%M:%S", time.localtime(record.granted_at)
        )
        exp_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.expires_at))
        header = f"👤 <code>{record.user_id}</code>"
        if record.username:
            header = f"{header} (@{html.escape(record.username)})"
        lines.append(header)
        if record.user_name:
            lines.append(f"  🙍 Name:  {html.escape(record.user_name)}")
        lines.append(f"  🏁 Start: {html.escape(start_str)}")
        lines.append(f"  ⌛ End:   {html.escape(exp_str)}")
        lines.append("")

    msg = "\n".join(lines).strip()
    if not msg or msg == "🔐 <b>Active Auth Grants</b>":
        await update.message.reply_text("No active authentication grants found.")
    else:
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Persistently ban a user ID. Owner only."""
    if not await guard_owner(update, context):
        return
    if not context.args or not context.args[0].strip().isdigit():
        await update.message.reply_text("Usage: /ban <user_id>")
        return
    target_id = int(context.args[0].strip())
    if config.OWNER_ID is not None and target_id == config.OWNER_ID:
        await update.message.reply_text("⛔ Cannot ban OWNER_ID.")
        return

    state = get_state(context.application)
    if target_id in config.BLOCKED_IDS and target_id not in state.blocked_ids:
        await update.message.reply_text(
            f"🚫 <code>{target_id}</code> is already blocked via BLOCKED_IDS.",
            parse_mode=ParseMode.HTML,
        )
        return

    if not state.block_user(target_id):
        await update.message.reply_text(
            f"🚫 <code>{target_id}</code> is already blocked.",
            parse_mode=ParseMode.HTML,
        )
        return

    await update.message.reply_text(
        f"✅ Blocked <code>{target_id}</code> persistently.",
        parse_mode=ParseMode.HTML,
    )


async def cmd_unban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove a user ID from the persistent ban list. Owner only."""
    if not await guard_owner(update, context):
        return
    if not context.args or not context.args[0].strip().isdigit():
        await update.message.reply_text("Usage: /unban <user_id>")
        return
    target_id = int(context.args[0].strip())
    state = get_state(context.application)
    removed = state.unblock_user(target_id)
    if removed and target_id in config.BLOCKED_IDS:
        await update.message.reply_text(
            f"⚠️ Removed <code>{target_id}</code> from persisted blocks, but it is still blocked via BLOCKED_IDS.",
            parse_mode=ParseMode.HTML,
        )
        return
    if removed:
        await update.message.reply_text(
            f"✅ Unblocked <code>{target_id}</code> from persisted blocks.",
            parse_mode=ParseMode.HTML,
        )
        return
    if target_id in config.BLOCKED_IDS:
        await update.message.reply_text(
            f"⚠️ <code>{target_id}</code> is blocked via BLOCKED_IDS and cannot be removed by /unban.",
            parse_mode=ParseMode.HTML,
        )
        return
    await update.message.reply_text(
        f"ℹ️ <code>{target_id}</code> is not in the persisted block list.",
        parse_mode=ParseMode.HTML,
    )


async def cmd_banlist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show aggregated blocked IDs from env and persisted state. Owner only."""
    if not await guard_owner(update, context):
        return
    state = get_state(context.application)
    aggregated = sorted(set(config.BLOCKED_IDS) | set(state.blocked_ids))
    persisted = set(state.blocked_ids)
    env_blocked = set(config.BLOCKED_IDS)

    if config.OWNER_ID is not None:
        aggregated = [uid for uid in aggregated if uid != config.OWNER_ID]
        persisted.discard(config.OWNER_ID)
        env_blocked.discard(config.OWNER_ID)

    if not aggregated:
        await update.message.reply_text("No blocked user IDs found.")
        return

    lines = ["🚫 <b>Blocked User IDs</b>\n"]
    for uid in aggregated:
        sources: list[str] = []
        if uid in env_blocked:
            sources.append("env")
        if uid in persisted:
            sources.append("file")
        source_text = ", ".join(sources) if sources else "runtime"
        lines.append(f"• <code>{uid}</code> <i>({html.escape(source_text)})</i>")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def _handle_failed_auth(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    state,
    *,
    reason: str,
) -> float | None:
    user = getattr(update, "effective_user", None)
    user_id = getattr(user, "id", None)
    if user_id is None:
        return None
    attempts, cooldown_until = state.record_failed_auth(
        user_id,
        max_failures=_FAILED_AUTH_LIMIT,
        cooldown_s=_FAILED_AUTH_COOLDOWN_S,
    )
    await _notify_owner_auth_failure(
        update,
        context,
        reason=reason,
        attempts=attempts,
        cooldown_until=cooldown_until,
    )
    return cooldown_until


async def _notify_owner_auth_failure(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    reason: str,
    attempts: int,
    cooldown_until: float | None,
) -> None:
    owner_id = config.OWNER_ID
    if owner_id is None:
        return
    app = getattr(context, "application", None)
    bot = getattr(app, "bot", None)
    send_message = getattr(bot, "send_message", None)
    if not callable(send_message):
        return

    user = getattr(update, "effective_user", None)
    chat = getattr(update, "effective_chat", None)
    user_id = getattr(user, "id", None)
    username = getattr(user, "username", None) or "-"
    chat_id = getattr(chat, "id", None)
    lines = [
        "🚨 Failed /auth",
        f"User ID: {user_id}",
        f"Chat ID: {chat_id}",
        f"Username: @{username}" if username != "-" else "Username: -",
        f"Reason: {reason}",
        f"Attempts: {min(max(attempts, 1), _FAILED_AUTH_LIMIT)}/{_FAILED_AUTH_LIMIT}",
    ]
    if cooldown_until is not None:
        lines.append(
            "Cooldown until: "
            f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(cooldown_until))}"
        )
    try:
        await send_message(chat_id=owner_id, text="\n".join(lines))
    except Exception as exc:
        logger.warning("Failed to notify owner about failed auth: %s", exc)


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
