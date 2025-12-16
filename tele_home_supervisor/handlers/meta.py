from __future__ import annotations

import asyncio

from telegram.constants import ParseMode

from .. import utils
from ..commands import COMMANDS, GROUP_ORDER
from ..background import ensure_started
from .common import guard


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


async def cmd_start(update, context) -> None:
    if not await guard(update, context):
        return
    try:
        ensure_started(context.application)
    except Exception:
        pass
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
    msg = await asyncio.to_thread(utils.get_version_info)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
