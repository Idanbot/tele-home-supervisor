from __future__ import annotations

import io
import logging
import qrcode

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from .. import services, view
from .common import (
    get_state,
    get_state_and_recorder,
    guard_sensitive,
    record_error,
    set_audit_target,
    tracked_reply_photo,
)

logger = logging.getLogger(__name__)


async def cmd_wifiqr(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard_sensitive(update, context):
        return

    args = context.args
    if not args:
        await update.message.reply_text("Usage: /wifiqr <ssid> [password]")
        return

    ssid = args[0]
    password = args[1] if len(args) > 1 else ""
    set_audit_target(context, ssid)
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

        state = get_state(context.application)
        await tracked_reply_photo(
            update.message, state, photo=bio, caption=caption, parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error("Failed to generate WiFi QR: %s", e)
        await update.message.reply_text("❌ Failed to generate QR code.")


async def cmd_dns(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard_sensitive(update, context):
        return
    if not context.args:
        await update.message.reply_text("Usage: /dns <name>", parse_mode=ParseMode.HTML)
        return
    name = context.args[0]
    set_audit_target(context, name)
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


async def cmd_traceroute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard_sensitive(update, context):
        return
    if not context.args:
        await update.message.reply_text(
            "Usage: /traceroute <host> [max_hops]", parse_mode=ParseMode.HTML
        )
        return
    host = context.args[0]
    set_audit_target(context, host)
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

    # Parse traceroute output for chart
    import re

    hops = []
    for line in result.split("\n"):
        # Match typical traceroute/tracepath output: "1:  192.168.1.1  0.5ms"
        m = re.match(r"\s*(\d+)[:\s]+([0-9.*]+)\s+(.+)?", line.strip())
        if m:
            hop_num = int(m.group(1))
            ip = m.group(2).strip()
            rest = m.group(3) or ""
            # Try to extract RTT
            rtt_match = re.search(r"([0-9.]+)\s*ms", rest)
            rtt = float(rtt_match.group(1)) if rtt_match else 0
            hops.append({"hop": hop_num, "ip": ip, "hostname": "", "rtt": rtt})

    if hops:
        chart = view.render_traceroute_chart(hops)
        if chart:
            state = get_state(context.application)
            await tracked_reply_photo(
                update.message, state, photo=chart, caption=f"Traceroute to {host}"
            )

    title = f"Traceroute {host}:"
    msg = f"{view.bold(title)}\n{view.pre(result)}"

    for part in view.chunk(msg, size=4000):
        await update.message.reply_text(part, parse_mode=ParseMode.HTML)


async def cmd_speedtest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard_sensitive(update, context):
        return
    mb = 100
    if context.args and context.args[0].isdigit():
        mb = max(1, min(int(context.args[0]), 200))
    set_audit_target(context, f"{mb}MB")

    msg = await update.message.reply_text(
        "🏃 Running speedtest...", parse_mode=ParseMode.HTML
    )

    _, recorder = get_state_and_recorder(context)
    try:
        result = await services.speedtest_download(mb)
    except Exception as e:
        await record_error(recorder, "speedtest", "speedtest failed", e, msg.edit_text)
        return

    # Try to parse Mbps for chart rendering
    import re

    mbps_match = re.search(r"Rate:\s*([0-9.]+)\s*Mb/s", result)
    if mbps_match:
        download_mbps = float(mbps_match.group(1))
        chart = view.render_speedtest_chart(download_mbps)
        if chart:
            state = get_state(context.application)
            await tracked_reply_photo(
                update.message, state, photo=chart, caption="Speedtest Results"
            )

    text = f"{view.bold('Speedtest (download):')}\n{result}"
    await msg.edit_text(text, parse_mode=ParseMode.HTML)
