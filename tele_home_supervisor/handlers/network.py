from __future__ import annotations

import io
import logging
import qrcode

from telegram.constants import ParseMode

from .. import services, view
from .common import get_state_and_recorder, guard_sensitive, record_error

logger = logging.getLogger(__name__)


async def cmd_wifiqr(update, context) -> None:
    if not await guard_sensitive(update, context):
        return

    args = context.args
    if not args:
        await update.message.reply_text("Usage: /wifiqr <ssid> [password]")
        return

    ssid = args[0]
    password = args[1] if len(args) > 1 else ""
    # "T" parameter: WPA, WEP, or nopass
    auth_type = "WPA" if password else "nopass"
    # Hidden? (False by default)
    # WIFI:S:<SSID>;T:<WPA|WEP|nopass>;P:<PASSWORD>;;

    # Escape special chars in SSID/Pass if needed (simple semicolon escape usually)
    # But qrcode lib might handle strings roughly.
    # Standard format: special chars like ; , : \ " should be escaped with \
    def escape(s):
        return (
            s.replace("\\", "\\\\")
            .replace(";", "\\;")
            .replace(",", "\\,")
            .replace(":", "\\:")
            .replace('"', '\\"')
        )

    wifi_string = f"WIFI:S:{escape(ssid)};T:{auth_type};P:{escape(password)};;"

    try:
        # Generate generic QR code
        img = qrcode.make(wifi_string)
        bio = io.BytesIO()
        img.save(bio, "PNG")
        bio.seek(0)

        caption = f"WiFi: <code>{ssid}</code>"
        if password:
            caption += f"\nPassword: <code>{password}</code>"

        await update.message.reply_photo(
            photo=bio, caption=caption, parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error("Failed to generate WiFi QR: %s", e)
        await update.message.reply_text("❌ Failed to generate QR code.")


async def cmd_dns(update, context) -> None:
    if not await guard_sensitive(update, context):
        return
    if not context.args:
        await update.message.reply_text("Usage: /dns <name>", parse_mode=ParseMode.HTML)
        return
    name = context.args[0]
    _, recorder = get_state_and_recorder(context)
    try:
        result = await services.dns_lookup(name)
    except Exception as e:
        await record_error(
            recorder,
            "dns",
            f"dns lookup failed for {name}",
            e,
            update.message.reply_text,
        )
        return
    # Result is already a multi-line string from utils, wrap it
    msg = f"{view.bold('DNS ' + name + ':')}\n{view.pre(result)}"
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_traceroute(update, context) -> None:
    if not await guard_sensitive(update, context):
        return
    if not context.args:
        await update.message.reply_text(
            "Usage: /traceroute <host> [max_hops]", parse_mode=ParseMode.HTML
        )
        return
    host = context.args[0]
    max_hops = 20
    if len(context.args) > 1 and context.args[1].isdigit():
        max_hops = max(1, min(int(context.args[1]), 50))

    _, recorder = get_state_and_recorder(context)
    try:
        result = await services.traceroute_host(host, max_hops)
    except Exception as e:
        await record_error(
            recorder,
            "traceroute",
            f"traceroute failed for {host}",
            e,
            update.message.reply_text,
        )
        return

    title = f"Traceroute {host}:"
    msg = f"{view.bold(title)}\n{view.pre(result)}"

    for part in view.chunk(msg, size=4000):
        await update.message.reply_text(part, parse_mode=ParseMode.HTML)


async def cmd_speedtest(update, context) -> None:
    if not await guard_sensitive(update, context):
        return
    mb = 100
    if context.args and context.args[0].isdigit():
        mb = max(1, min(int(context.args[0]), 200))

    msg = await update.message.reply_text(
        "🏃 Running speedtest...", parse_mode=ParseMode.HTML
    )

    _, recorder = get_state_and_recorder(context)
    try:
        result = await services.speedtest_download(mb)
    except Exception as e:
        await record_error(recorder, "speedtest", "speedtest failed", e, msg.edit_text)
        return
    text = f"{view.bold('Speedtest (download):')}\n{result}"
    await msg.edit_text(text, parse_mode=ParseMode.HTML)
