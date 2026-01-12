from __future__ import annotations

import html
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest

from ..alerting import (
    DEFAULT_RULE_SPECS,
    METRIC_DEFS,
    format_duration,
    format_threshold,
    get_metric_def,
    normalize_metric,
    parse_duration,
    parse_threshold,
)
from ..state import BotState
from .common import guard_sensitive, get_state, set_audit_target

logger = logging.getLogger(__name__)

_VALID_OPERATORS = {">", ">=", "<", "<=", "=", "==", "!="}
_BOOL_OPERATORS = {"=", "==", "!="}


def _render_alert_rules(rules: list) -> list[str]:
    lines: list[str] = []
    for idx, rule in enumerate(rules, start=1):
        threshold = format_threshold(rule.metric, rule.threshold)
        duration = format_duration(rule.duration_s)
        status = "on" if rule.enabled else "off"
        lines.append(
            f"{idx}. <code>{html.escape(rule.id)}</code> "
            f"{html.escape(rule.metric)} {html.escape(rule.operator)} "
            f"{html.escape(threshold)} for {html.escape(duration)} ({status})"
        )
    return lines


def build_alerts_keyboard(rules: list) -> InlineKeyboardMarkup | None:
    if not rules:
        return None
    rows: list[list[InlineKeyboardButton]] = []
    for rule in rules:
        toggle_label = "Disable" if rule.enabled else "Enable"
        rows.append(
            [
                InlineKeyboardButton(
                    toggle_label, callback_data=f"alerts:toggle:{rule.id}"
                ),
                InlineKeyboardButton("Edit", callback_data=f"alerts:edit:{rule.id}"),
                InlineKeyboardButton(
                    "Remove", callback_data=f"alerts:remove:{rule.id}"
                ),
            ]
        )
    return InlineKeyboardMarkup(rows)


def render_alerts_overview(
    state: BotState, chat_id: int
) -> tuple[str, InlineKeyboardMarkup | None]:
    enabled = state.alerts_enabled_for(chat_id)
    rules = state.alert_rules_for_chat(chat_id)
    lines = [f"<b>Alerts:</b> {'ON' if enabled else 'OFF'}"]
    if rules:
        lines.append("<b>Rules:</b>")
        lines.extend(_render_alert_rules(rules))
    else:
        lines.append("No rules configured.")
    if not rules:
        metrics = ", ".join(sorted(METRIC_DEFS.keys()))
        lines.append(f"<i>Metrics:</i> {html.escape(metrics)}")
    lines.append(
        "<i>Usage:</i> /alerts add &lt;metric&gt; &lt;operator&gt; &lt;value&gt; [duration]"
    )
    lines.append("<i>Duration:</i> 30s, 10m, 1h (numbers default to minutes)")
    return "\n".join(lines), build_alerts_keyboard(rules)


def _add_default_rules(state: BotState, chat_id: int) -> list[str]:
    added: list[str] = []
    for metric, operator, threshold, duration_s in DEFAULT_RULE_SPECS:
        rule = state.add_alert_rule(chat_id, metric, operator, threshold, duration_s)
        added.append(rule.id)
    return added


async def cmd_alerts(update, context) -> None:
    if not await guard_sensitive(update, context):
        return
    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id is None:
        return
    state: BotState = get_state(context.application)

    args = [a.strip() for a in (context.args or []) if a.strip()]
    action = args[0].lower() if args else "status"

    if action in {"status", "list"}:
        msg, keyboard = render_alerts_overview(state, chat_id)
        await update.message.reply_text(
            msg, parse_mode=ParseMode.HTML, reply_markup=keyboard
        )
        return

    if action in {"on", "off"}:
        enabled = state.set_alerts_enabled(chat_id, action == "on")
        added = []
        if enabled and not state.alert_rules_for_chat(chat_id):
            added = _add_default_rules(state, chat_id)
        msg = f"Alerts: <b>{'ON' if enabled else 'OFF'}</b>"
        if added:
            msg += f"\nAdded default rules: {', '.join(added)}"
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
        return

    if action == "add":
        if len(args) < 4:
            await update.message.reply_text(
                "Usage: /alerts add <metric> <operator> <value> [duration]",
                parse_mode=ParseMode.HTML,
            )
            return
        metric = normalize_metric(args[1])
        if not metric:
            await update.message.reply_text(
                "Unknown metric.", parse_mode=ParseMode.HTML
            )
            return
        set_audit_target(context, metric)
        operator = args[2]
        if operator not in _VALID_OPERATORS:
            await update.message.reply_text(
                "Invalid operator. Use one of: > >= < <= = !=",
                parse_mode=ParseMode.HTML,
            )
            return
        definition = get_metric_def(metric)
        if (
            definition
            and definition.kind in {"bool", "event"}
            and operator not in _BOOL_OPERATORS
        ):
            await update.message.reply_text(
                "Boolean metrics support only = or !=",
                parse_mode=ParseMode.HTML,
            )
            return
        operator = "=" if operator == "==" else operator
        value_raw = args[3]
        threshold, error = parse_threshold(metric, value_raw)
        if error:
            await update.message.reply_text(
                f"Invalid threshold: {html.escape(error)}",
                parse_mode=ParseMode.HTML,
            )
            return
        duration_s = parse_duration(
            args[4] if len(args) > 4 else None,
            definition.default_duration_s if definition else 0,
        )
        if duration_s is None:
            await update.message.reply_text(
                "Invalid duration. Use 30s, 10m, or 1h.",
                parse_mode=ParseMode.HTML,
            )
            return
        rule = state.add_alert_rule(
            chat_id=chat_id,
            metric=metric,
            operator=operator,
            threshold=threshold,
            duration_s=duration_s,
        )
        msg = (
            f"Added rule <code>{html.escape(rule.id)}</code>: "
            f"{html.escape(rule.metric)} {html.escape(rule.operator)} "
            f"{html.escape(format_threshold(rule.metric, rule.threshold))} "
            f"for {html.escape(format_duration(rule.duration_s))}"
        )
        if not state.alerts_enabled_for(chat_id):
            msg += "\nAlerts are OFF. Use /alerts on to enable."
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
        return

    if action == "remove":
        if len(args) < 2:
            await update.message.reply_text(
                "Usage: /alerts remove <id>", parse_mode=ParseMode.HTML
            )
            return
        rule_id = args[1]
        set_audit_target(context, rule_id)
        removed = state.remove_alert_rule(chat_id, rule_id)
        msg = "Rule removed." if removed else "Rule not found."
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
        return

    if action == "edit":
        if len(args) < 5:
            await update.message.reply_text(
                "Usage: /alerts edit <id> <metric> <operator> <value> [duration]",
                parse_mode=ParseMode.HTML,
            )
            return
        rule_id = args[1]
        set_audit_target(context, rule_id)
        existing = state.get_alert_rule(rule_id)
        if not existing or existing.chat_id != chat_id:
            await update.message.reply_text(
                "Rule not found.", parse_mode=ParseMode.HTML
            )
            return
        metric = normalize_metric(args[2])
        if not metric:
            await update.message.reply_text(
                "Unknown metric.", parse_mode=ParseMode.HTML
            )
            return
        operator = args[3]
        if operator not in _VALID_OPERATORS:
            await update.message.reply_text(
                "Invalid operator. Use one of: > >= < <= = !=",
                parse_mode=ParseMode.HTML,
            )
            return
        definition = get_metric_def(metric)
        if (
            definition
            and definition.kind in {"bool", "event"}
            and operator not in _BOOL_OPERATORS
        ):
            await update.message.reply_text(
                "Boolean metrics support only = or !=",
                parse_mode=ParseMode.HTML,
            )
            return
        operator = "=" if operator == "==" else operator
        threshold, error = parse_threshold(metric, args[4])
        if error:
            await update.message.reply_text(
                f"Invalid threshold: {html.escape(error)}",
                parse_mode=ParseMode.HTML,
            )
            return
        duration_s = parse_duration(
            args[5] if len(args) > 5 else None,
            definition.default_duration_s if definition else 0,
        )
        if duration_s is None:
            await update.message.reply_text(
                "Invalid duration. Use 30s, 10m, or 1h.",
                parse_mode=ParseMode.HTML,
            )
            return
        rule = state.update_alert_rule(
            rule_id=rule_id,
            metric=metric,
            operator=operator,
            threshold=threshold,
            duration_s=duration_s,
        )
        if not rule:
            await update.message.reply_text(
                "Rule not found.", parse_mode=ParseMode.HTML
            )
            return
        msg = (
            f"Updated rule <code>{html.escape(rule.id)}</code>: "
            f"{html.escape(rule.metric)} {html.escape(rule.operator)} "
            f"{html.escape(format_threshold(rule.metric, rule.threshold))} "
            f"for {html.escape(format_duration(rule.duration_s))}"
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
        return

    await update.message.reply_text(
        "Usage: /alerts [on|off|add|remove|edit]", parse_mode=ParseMode.HTML
    )


async def _safe_edit_message_text(query, text: str, **kwargs) -> None:
    try:
        await query.edit_message_text(text, **kwargs)
    except BadRequest as exc:
        if "Message is not modified" in str(exc):
            return
        raise


async def handle_alerts_callback(query, context, action: str, rule_id: str) -> None:
    state: BotState = get_state(context.application)
    chat_id = query.message.chat_id if query.message else None
    if chat_id is None:
        return
    rule = state.get_alert_rule(rule_id)
    if not rule or rule.chat_id != chat_id:
        await query.message.reply_text("Rule not found.")
        return

    if action == "toggle":
        state.toggle_alert_rule(chat_id, rule_id)
        msg, keyboard = render_alerts_overview(state, chat_id)
        await _safe_edit_message_text(
            query, msg, parse_mode=ParseMode.HTML, reply_markup=keyboard
        )
        return

    if action == "remove":
        state.remove_alert_rule(chat_id, rule_id)
        msg, keyboard = render_alerts_overview(state, chat_id)
        await _safe_edit_message_text(
            query, msg, parse_mode=ParseMode.HTML, reply_markup=keyboard
        )
        return

    if action == "edit":
        threshold = format_threshold(rule.metric, rule.threshold)
        duration = format_duration(rule.duration_s)
        cmd = (
            f"/alerts edit {rule.id} {rule.metric} {rule.operator} "
            f"{threshold} {duration}"
        )
        msg = f"Edit with:\n<code>{html.escape(cmd)}</code>"
        await query.message.reply_text(msg, parse_mode=ParseMode.HTML)
        return

    logger.debug("Unknown alerts callback action: %s", action)
