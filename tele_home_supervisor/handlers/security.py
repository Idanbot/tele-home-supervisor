"""Owner-only security activity review."""

import asyncio
import time
from datetime import datetime

from .. import security
from .common import get_state, guard_owner


async def cmd_security(update, context):
    if not await guard_owner(update, context):
        return
    if context.args:
        if len(context.args) == 2 and context.args[0] == "ban":
            from .meta import cmd_ban

            previous = context.args
            try:
                context.args = previous[1:]
                await cmd_ban(update, context)
            finally:
                context.args = previous
        else:
            await update.message.reply_text(
                "Usage: /security or /security ban <user_id>"
            )
        return
    state = get_state(context.application)
    try:
        rows = await asyncio.to_thread(
            security.recent_attempts, state._database_file, time.time()
        )
    except Exception:
        await update.message.reply_text(
            "Security history is unavailable; check database permissions."
        )
        return
    lines = ["Security activity (latest 10 identities, retained for 90 days)"]
    for row in rows:
        first = datetime.fromtimestamp(row["first_seen"]).isoformat(timespec="minutes")
        last = datetime.fromtimestamp(row["last_seen"]).isoformat(timespec="minutes")
        lines.append(
            f"\n{row['user_name'][:80]} · user {row['user_id']} · chat {row['chat_id']}\n"
            f"Attempts: {row['attempts']} · latest: {row['action'][:80]}\n"
            f"First: {first} · Last: {last}"
        )
    if not rows:
        lines.append("No unauthorized attempts recorded.")
    lines.append("\nBlock a user: /security ban <user_id>")
    await update.message.reply_text("\n".join(lines))
