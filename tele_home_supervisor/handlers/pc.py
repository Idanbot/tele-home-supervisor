"""Managed-PC controls with observed network state and bounded wake verification."""

from __future__ import annotations

import asyncio
import html
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from .. import config, network_inventory
from . import network
from .common import get_state, guard_sensitive, set_audit_target


def _target():
    host = config.get_managed_host("pc1")
    if host is None:
        return None
    return network._resolve_wol_request(host.name)


def _latest(state, mac):
    matches = [
        scan
        for scans in state.network_inventory.values()
        for scan in scans
        if mac and network._normalize_mac(scan.mac) == network._normalize_mac(mac)
    ]
    return max(matches, key=lambda scan: scan.scanned_at, default=None)


def _keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Wake", callback_data="pc1:wake"),
                InlineKeyboardButton("Scan", callback_data="pc1:scan"),
                InlineKeyboardButton("Refresh", callback_data="pc1:status"),
            ]
        ]
    )


async def _show_status(message, state, resolved):
    latest = _latest(state, resolved.mac)
    address = latest.ip if latest else resolved.ping_host
    online = await network._ping_once(address) if address else False
    status = "Reachable" if online else "Not reachable by ping"
    seen = (
        datetime.fromtimestamp(latest.scanned_at).isoformat(timespec="minutes")
        if latest
        else "No scan observation"
    )
    await message.reply_text(
        f"<b>PC1</b> · {status}\n"
        f"MAC: <code>{html.escape(resolved.mac or 'Not configured')}</code>\n"
        f"Last observed IP: <code>{html.escape(latest.ip if latest else 'Unknown')}</code>\n"
        f"Ping target: <code>{html.escape(address or 'Not configured')}</code>\n"
        f"Last seen: {html.escape(seen)}",
        parse_mode=ParseMode.HTML,
        reply_markup=_keyboard(),
    )


async def cmd_pc1(update, context):
    if not await guard_sensitive(update, context):
        return
    resolved = _target()
    if resolved is None:
        await update.message.reply_text(
            'Configure a managed host named pc1 (or add "pc1" to its aliases) in MANAGED_HOSTS_JSON.'
        )
        return
    await _show_status(update.message, get_state(context.application), resolved)


async def handle_pc_callback(update, context):
    if not await guard_sensitive(update, context):
        return
    query = update.callback_query
    action = query.data.removeprefix("pc1:")
    if action not in {"status", "wake", "scan"}:
        return
    resolved = _target()
    if resolved is None:
        await query.message.reply_text("PC1 is no longer configured.")
        return
    state = get_state(context.application)
    set_audit_target(context, "pc1")
    if action == "status":
        await _show_status(query.message, state, resolved)
        return

    key = f"pc1:{update.effective_chat.id}"
    existing = state.tasks.get(key)
    if existing is not None and not existing.done():
        await query.message.reply_text("A PC1 operation is already running.")
        return

    async def operate():
        try:
            if not resolved.ok:
                await query.message.reply_text(
                    resolved.error or "PC1 needs a valid MAC address."
                )
                return
            if action == "scan":
                targets = network._resolve_default_scan_targets()
                if not targets:
                    await query.message.reply_text(
                        "Set NETWORK_INVENTORY_TARGETS to your LAN subnet."
                    )
                    return
                found, _, summary = await network_inventory.find_device_by_mac(
                    resolved.mac,
                    targets,
                    timeout_s=min(60, config.NETWORK_INVENTORY_SCAN_TIMEOUT_S),
                )
                if found:
                    state.network_inventory.setdefault(found.ip, []).append(found)
                    state.prune_network_inventory(
                        retention_days=config.NETWORK_INVENTORY_RETENTION_DAYS,
                        max_scans_per_device=config.NETWORK_INVENTORY_MAX_SCANS_PER_DEVICE,
                    )
                    await asyncio.to_thread(state.save_network_inventory)
                else:
                    await query.message.reply_text(
                        "PC1 MAC was not detected."
                        + (f" {summary.error}" if summary.error else "")
                    )
                await _show_status(query.message, state, resolved)
                return

            latest = _latest(state, resolved.mac)
            address = latest.ip if latest else resolved.ping_host
            if address and await network._ping_once(address):
                await query.message.reply_text("PC1 is already reachable.")
                return
            await network._send_wol_packet(
                resolved.mac,
                broadcast_ips=resolved.broadcast_ips,
                port=resolved.wol_port,
            )
            if not address:
                await query.message.reply_text(
                    "Wake packet sent. Configure ping_host to verify startup."
                )
                return
            await query.message.reply_text(
                "Wake packet sent. Checking reachability for up to 60 seconds."
            )
            try:
                async with asyncio.timeout(60):
                    while True:
                        if await network._ping_once(address):
                            await query.message.reply_text(
                                f"PC1 is reachable at {address}."
                            )
                            return
                        await asyncio.sleep(3)
            except TimeoutError:
                await query.message.reply_text(
                    "PC1 did not respond to ping within 60 seconds. Its power state is unconfirmed."
                )
        except Exception:
            network.logger.exception("PC1 %s failed", action)
            await query.message.reply_text(
                "PC1 operation failed. Check bot logs for details."
            )
        finally:
            state.tasks.pop(key, None)

    task = context.application.create_task(operate())
    state.tasks[key] = task
