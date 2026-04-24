from __future__ import annotations

import asyncio
import io
import logging
import html
import re
import socket
import time

import qrcode

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from .. import cli, config, services, view
from ..models.managed_host import ManagedHost
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


async def cmd_wol(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send Magic Packet Wake-on-LAN to a MAC or IP address."""
    if not await guard_sensitive(update, context):
        return

    target = context.args[0].strip() if context.args else ""
    set_audit_target(context, target)
    resolved = _resolve_wol_request(target)
    if not resolved.ok:
        logger.warning(
            "WOL rejected for target=%r: %s",
            target,
            resolved.error or "invalid WOL target configuration",
        )
        await update.message.reply_text(
            resolved.error or "❌ Invalid WOL target configuration."
        )
        return

    try:
        _send_wol_packet(
            resolved.mac,
            broadcast_ips=resolved.broadcast_ips,
            port=resolved.wol_port,
        )
    except Exception as e:
        logger.exception(
            "WOL send failed for target=%r mac=%s ping_host=%s",
            target,
            resolved.mac,
            resolved.ping_host,
        )
        await update.message.reply_text(f"❌ WOL failed: {html.escape(str(e))}")
        return

    lines = [
        f"✅ Sent WOL Magic Packet to <code>{html.escape(resolved.mac)}</code>.",
    ]
    if resolved.ping_host:
        lines.append(
            "📡 Watching <code>"
            f"{html.escape(resolved.ping_host)}</code> for ping response."
        )
        _schedule_power_state_watch(
            context,
            chat_id=update.effective_chat.id,
            host=resolved.ping_host,
            online=True,
        )
    else:
        lines.append("ℹ️ No ping host configured, so power-up verification is skipped.")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_wolshutdown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a remote shutdown command and watch for the host to disappear."""
    if not await guard_sensitive(update, context):
        return

    target = context.args[0].strip() if context.args else ""
    resolved = _resolve_shutdown_request(target)
    set_audit_target(context, target or resolved.ssh_target or resolved.ping_host)
    if not resolved.ok:
        logger.warning(
            "WOL shutdown rejected for target=%r: %s",
            target,
            resolved.error or "WOL shutdown is not configured",
        )
        await update.message.reply_text(
            resolved.error or "❌ WOL shutdown is not configured.",
        )
        return

    rc, out, err = await cli.run_cmd(_build_shutdown_ssh_command(resolved), timeout=15)
    if rc != 0:
        details = err or out or f"exit code {rc}"
        logger.warning(
            "WOL shutdown command failed for target=%r ssh_target=%s host=%s: %s",
            target,
            resolved.ssh_target,
            resolved.ping_host,
            details,
        )
        await update.message.reply_text(
            f"❌ WOL shutdown failed: <code>{html.escape(details)}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    _schedule_power_state_watch(
        context,
        chat_id=update.effective_chat.id,
        host=resolved.ping_host,
        online=False,
    )
    await update.message.reply_text(
        "✅ Sent shutdown command via <code>"
        f"{html.escape(resolved.ssh_target)}</code>.\n"
        "📡 Watching <code>"
        f"{html.escape(resolved.ping_host)}</code> for ping failure.",
        parse_mode=ParseMode.HTML,
    )


class _ResolvedWolRequest:
    def __init__(
        self,
        *,
        ok: bool,
        mac: str = "",
        ping_host: str | None = None,
        broadcast_ips: list[str] | None = None,
        wol_port: int = 9,
        host: ManagedHost | None = None,
        error: str | None = None,
    ) -> None:
        self.ok = ok
        self.mac = mac
        self.ping_host = ping_host
        self.broadcast_ips = broadcast_ips or ["255.255.255.255"]
        self.wol_port = wol_port
        self.host = host
        self.error = error


class _ResolvedShutdownRequest:
    def __init__(
        self,
        *,
        ok: bool,
        ping_host: str = "",
        ssh_target: str = "",
        ssh_port: int = 22,
        shutdown_command: str = "",
        host: ManagedHost | None = None,
        error: str | None = None,
    ) -> None:
        self.ok = ok
        self.ping_host = ping_host
        self.ssh_target = ssh_target
        self.ssh_port = ssh_port
        self.shutdown_command = shutdown_command
        self.host = host
        self.error = error


def _resolve_wol_request(target: str) -> _ResolvedWolRequest:
    requested = target.strip()
    selected_host = _select_managed_host(requested)
    if selected_host is not None:
        mac = _normalize_mac(selected_host.mac) or (
            _resolve_mac_from_arp(selected_host.ping_host)
            if selected_host.ping_host
            else None
        )
        if not mac:
            return _ResolvedWolRequest(
                ok=False,
                error=(
                    f"❌ Host <code>{html.escape(selected_host.name)}</code> has no "
                    "usable MAC address configured.\nSet its <code>mac</code> in "
                    "<code>MANAGED_HOSTS_JSON</code> or ensure its IP exists in ARP."
                ),
            )
        return _ResolvedWolRequest(
            ok=True,
            mac=mac,
            ping_host=selected_host.ping_host or None,
            broadcast_ips=_get_wol_broadcast_targets(selected_host),
            wol_port=selected_host.wol_port,
            host=selected_host,
        )

    default_ip, default_mac = _legacy_defaults()
    if not requested:
        ping_host = default_ip or None
        mac = default_mac or (_resolve_mac_from_arp(default_ip) if default_ip else None)
        if not mac:
            return _ResolvedWolRequest(
                ok=False,
                error="Usage: /wol <mac|ip>\n"
                "Or configure MANAGED_HOSTS_JSON and optionally DEFAULT_MANAGED_HOST.",
            )
        return _ResolvedWolRequest(
            ok=True,
            mac=mac,
            ping_host=ping_host,
            broadcast_ips=_get_wol_broadcast_targets(None),
            wol_port=config.WOL_PORT,
        )

    if _looks_like_mac(requested):
        return _ResolvedWolRequest(
            ok=True,
            mac=_normalize_mac(requested) or requested,
            ping_host=default_ip or None,
            broadcast_ips=_get_wol_broadcast_targets(None),
            wol_port=config.WOL_PORT,
        )

    if _looks_like_ipv4(requested):
        mac = (
            default_mac
            if default_ip and requested == default_ip and default_mac
            else None
        )
        if not mac:
            mac = _resolve_mac_from_arp(requested)
        if not mac:
            return _ResolvedWolRequest(
                ok=False,
                error=(
                    f"❌ Could not resolve MAC for IP {requested}.\n"
                    "Set WOL_TARGET_MAC for this host, or make sure the host exists "
                    "in the ARP cache."
                ),
            )
        return _ResolvedWolRequest(
            ok=True,
            mac=mac,
            ping_host=requested,
            broadcast_ips=_get_wol_broadcast_targets(None),
            wol_port=config.WOL_PORT,
        )

    if requested:
        available = []
        for host in config.MANAGED_HOSTS:
            aliases = ", ".join(host.aliases)
            if aliases:
                available.append(f"{host.name} ({aliases})")
            else:
                available.append(host.name)
        extra = ""
        if available:
            extra = (
                "\nConfigured managed hosts: <code>"
                + html.escape("; ".join(available))
                + "</code>"
            )
        return _ResolvedWolRequest(
            ok=False,
            error=(
                "❌ Unknown host/device name.\n"
                "Use a managed host name, alias, MAC address, or IPv4 address."
                f"{extra}"
            ),
        )

    return _ResolvedWolRequest(ok=False, error="❌ Invalid MAC or IPv4 address format.")


def _resolve_shutdown_request(target: str) -> _ResolvedShutdownRequest:
    requested = target.strip()
    selected_host = _select_managed_host(requested)
    if selected_host is not None:
        if not selected_host.ssh_target or not selected_host.shutdown_command:
            return _ResolvedShutdownRequest(
                ok=False,
                error=(
                    f"❌ Host <code>{html.escape(selected_host.name)}</code> is missing "
                    "<code>ssh_target</code> or <code>shutdown_command</code>."
                ),
            )
        if not selected_host.ping_host:
            return _ResolvedShutdownRequest(
                ok=False,
                error=(
                    f"❌ Host <code>{html.escape(selected_host.name)}</code> is missing "
                    "<code>ping_host</code> for shutdown verification."
                ),
            )
        return _ResolvedShutdownRequest(
            ok=True,
            ping_host=selected_host.ping_host,
            ssh_target=selected_host.ssh_target,
            ssh_port=selected_host.ssh_port,
            shutdown_command=selected_host.shutdown_command,
            host=selected_host,
        )

    if requested and not _looks_like_ipv4(requested):
        return _ResolvedShutdownRequest(
            ok=False,
            error=(
                "❌ Unknown host/device name.\nUse a managed host name, alias, or an "
                "IPv4 ping host."
            ),
        )

    ping_host = requested or config.WOL_TARGET_IP
    if not config.WOL_SSH_TARGET or not config.WOL_SHUTDOWN_REMOTE_CMD:
        return _ResolvedShutdownRequest(
            ok=False,
            error="❌ WOL shutdown is not configured. Set MANAGED_HOSTS_JSON for a host "
            "or set legacy WOL_SSH_TARGET and WOL_SHUTDOWN_REMOTE_CMD.",
        )
    if not ping_host:
        return _ResolvedShutdownRequest(
            ok=False,
            error="❌ No ping host configured. Set a host ping IP in MANAGED_HOSTS_JSON, "
            "set WOL_TARGET_IP, or pass an IPv4 host to /wolshutdown.",
        )
    return _ResolvedShutdownRequest(
        ok=True,
        ping_host=ping_host,
        ssh_target=config.WOL_SSH_TARGET,
        ssh_port=config.WOL_SSH_PORT,
        shutdown_command=config.WOL_SHUTDOWN_REMOTE_CMD,
    )


def _select_managed_host(target: str) -> ManagedHost | None:
    requested = (target or "").strip()
    if requested:
        return config.get_managed_host(requested)
    return config.default_managed_host()


def _legacy_defaults() -> tuple[str, str | None]:
    default_ip = (config.WOL_TARGET_IP or "").strip()
    default_mac = _normalize_mac(config.WOL_TARGET_MAC)
    return default_ip, default_mac


def _resolve_mac_from_arp(ip: str) -> str | None:
    """Try to find MAC address for a given IP in the system ARP cache."""
    try:
        with open("/proc/net/arp", "r") as f:
            for line in f.readlines()[1:]:
                parts = line.split()
                if len(parts) >= 4 and parts[0] == ip:
                    res = parts[3]
                    if res != "00:00:00:00:00:00":
                        return res
    except OSError as exc:
        logger.debug("Failed to read /proc/net/arp while resolving %s: %s", ip, exc)

    return None


def _normalize_mac(mac: str) -> str | None:
    clean_mac = re.sub(r"[^0-9a-fA-F]", "", mac or "")
    if len(clean_mac) != 12:
        return None
    return ":".join(clean_mac[i : i + 2] for i in range(0, 12, 2)).lower()


def _looks_like_mac(value: str) -> bool:
    return bool(re.fullmatch(r"([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}", value.strip()))


def _looks_like_ipv4(value: str) -> bool:
    if not re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", value.strip()):
        return False
    return all(0 <= int(part) <= 255 for part in value.split("."))


def _get_wol_broadcast_targets(host: ManagedHost | None) -> list[str]:
    targets: list[str] = []
    configured = ""
    if host is not None:
        configured = (host.wol_broadcast_ip or "").strip()
    if not configured:
        configured = (config.WOL_BROADCAST_IP or "").strip()
    if configured:
        targets.append(configured)
    targets.append("255.255.255.255")
    return list(dict.fromkeys(targets))


def _send_wol_packet(mac: str, *, broadcast_ips: list[str], port: int) -> None:
    """Construct and send a WOL Magic Packet."""
    clean_mac = re.sub(r"[^0-9a-fA-F]", "", mac)
    if len(clean_mac) != 12:
        raise ValueError("Invalid MAC address length")

    data = bytes.fromhex("ff" * 6 + clean_mac * 16)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for broadcast_ip in broadcast_ips:
            s.sendto(data, (broadcast_ip, port))


def _build_shutdown_ssh_command(resolved: _ResolvedShutdownRequest) -> list[str]:
    return [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-p",
        str(resolved.ssh_port),
        resolved.ssh_target,
        resolved.shutdown_command,
    ]


def _schedule_power_state_watch(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    host: str,
    online: bool,
) -> None:
    async def _watch() -> None:
        timeout_s = max(1.0, config.WOL_VERIFY_TIMEOUT_S)
        interval_s = max(1.0, config.WOL_VERIFY_INTERVAL_S)
        start = time.monotonic()
        target_state = "online" if online else "offline"
        while (time.monotonic() - start) < timeout_s:
            is_online = await _ping_once(host)
            if is_online == online:
                elapsed = int(time.monotonic() - start)
                emoji = "🟢" if online else "⚫"
                verb = "powered up" if online else "powered off"
                await context.application.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"{emoji} Host <code>{html.escape(host)}</code> appears to have "
                        f"{verb} after {elapsed}s."
                    ),
                    parse_mode=ParseMode.HTML,
                )
                return
            await asyncio.sleep(interval_s)

        await context.application.bot.send_message(
            chat_id=chat_id,
            text=(
                "⚠️ Timed out waiting for <code>"
                f"{html.escape(host)}</code> to become {target_state}."
            ),
            parse_mode=ParseMode.HTML,
        )

    app = getattr(context, "application", None)
    if app is not None and hasattr(app, "create_task"):
        app.create_task(_watch())
    else:
        asyncio.create_task(_watch())


async def _ping_once(host: str) -> bool:
    rc, _, _ = await cli.run_cmd(["ping", "-c", "1", "-W", "1", host], timeout=3)
    return rc == 0
