from __future__ import annotations

import time

from telegram.constants import ParseMode

from .. import view
from ..state import BotState
from .common import guard_sensitive, get_state


def _format_entry(entry) -> str:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(entry.created_at))
    user = entry.user_name or "unknown"
    target = entry.target or "-"
    duration = f"{entry.duration_ms}ms"
    return f"{timestamp} {user} {entry.action} {target} ({entry.status}, {duration})"


async def cmd_audit(update, context) -> None:
    if not await guard_sensitive(update, context):
        return
    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id is None:
        return
    state: BotState = get_state(context.application)

    args = [a.strip() for a in (context.args or []) if a.strip()]
    if args and args[0].lower() == "clear":
        state.clear_audit_entries(chat_id)
        await update.message.reply_text("Audit log cleared.", parse_mode=ParseMode.HTML)
        return

    limit = 20
    if args and args[0].isdigit():
        limit = max(1, min(int(args[0]), 100))

    entries = state.get_audit_entries(chat_id, limit)
    if not entries:
        await update.message.reply_text("No audit entries.", parse_mode=ParseMode.HTML)
        return

    lines = [_format_entry(entry) for entry in entries]
    msg = f"{view.bold('Audit log:')}\n{view.pre('\\n'.join(lines))}"
    for part in view.chunk(msg, size=4000):
        await update.message.reply_text(part, parse_mode=ParseMode.HTML)
