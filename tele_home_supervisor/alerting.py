"""Alert metric definitions and parsing helpers."""

from __future__ import annotations

import asyncio
import html
import logging
import os
import re
import shutil
import time
from dataclasses import dataclass

import psutil

from . import cli, config, services, utils
from .state import BotState


@dataclass(frozen=True)
class MetricDef:
    name: str
    label: str
    kind: str  # number, bool, event
    unit: str | None
    default_duration_s: int


logger = logging.getLogger(__name__)

METRIC_DEFS: dict[str, MetricDef] = {
    "disk_used": MetricDef(
        name="disk_used",
        label="Disk usage",
        kind="number",
        unit="percent",
        default_duration_s=10 * 60,
    ),
    "load": MetricDef(
        name="load",
        label="Load (1m)",
        kind="number",
        unit="load",
        default_duration_s=5 * 60,
    ),
    "mem_used": MetricDef(
        name="mem_used",
        label="Memory usage",
        kind="number",
        unit="percent",
        default_duration_s=10 * 60,
    ),
    "temp": MetricDef(
        name="temp",
        label="CPU temperature",
        kind="number",
        unit="temp",
        default_duration_s=5 * 60,
    ),
    "lan_up": MetricDef(
        name="lan_up",
        label="LAN reachability",
        kind="bool",
        unit=None,
        default_duration_s=60,
    ),
    "wan_up": MetricDef(
        name="wan_up",
        label="WAN reachability",
        kind="bool",
        unit=None,
        default_duration_s=60,
    ),
    "torrent_stalled": MetricDef(
        name="torrent_stalled",
        label="Torrent stalled",
        kind="bool",
        unit=None,
        default_duration_s=15 * 60,
    ),
    "torrent_zero_speed": MetricDef(
        name="torrent_zero_speed",
        label="Torrent zero speed",
        kind="bool",
        unit=None,
        default_duration_s=15 * 60,
    ),
    "torrent_complete": MetricDef(
        name="torrent_complete",
        label="Torrent complete",
        kind="event",
        unit=None,
        default_duration_s=0,
    ),
}

METRIC_ALIASES: dict[str, str] = {
    "disk": "disk_used",
    "disk_usage": "disk_used",
    "mem": "mem_used",
    "memory": "mem_used",
    "temperature": "temp",
    "lan": "lan_up",
    "wan": "wan_up",
    "torrent_zero": "torrent_zero_speed",
    "torrent_zero_speed": "torrent_zero_speed",
    "torrent_completed": "torrent_complete",
}

DEFAULT_RULE_SPECS: tuple[tuple[str, str, object, int], ...] = (
    ("disk_used", ">", 90.0, 10 * 60),
    ("load", ">", 2.5, 5 * 60),
    ("mem_used", ">", 90.0, 10 * 60),
    ("torrent_stalled", "=", True, 15 * 60),
)

_BOOL_TRUE = {"true", "yes", "1", "on"}
_BOOL_FALSE = {"false", "no", "0", "off"}


def normalize_metric(name: str) -> str | None:
    key = (name or "").strip().lower()
    if not key:
        return None
    key = METRIC_ALIASES.get(key, key)
    return key if key in METRIC_DEFS else None


def get_metric_def(metric: str) -> MetricDef | None:
    key = normalize_metric(metric)
    if not key:
        return None
    return METRIC_DEFS.get(key)


def parse_duration(raw: str | None, default_s: int) -> int | None:
    if raw is None:
        return default_s
    text = raw.strip().lower()
    if not text:
        return default_s
    unit = text[-1]
    if unit in {"s", "m", "h"}:
        number = text[:-1]
    else:
        unit = "m"
        number = text
    try:
        value = float(number)
    except ValueError:
        return None
    if value < 0:
        return None
    multiplier = 1 if unit == "s" else 60 if unit == "m" else 3600
    return int(value * multiplier)


def _parse_bool(text: str) -> bool | None:
    value = text.strip().lower()
    if value in _BOOL_TRUE:
        return True
    if value in _BOOL_FALSE:
        return False
    return None


def parse_threshold(metric: str, raw: str) -> tuple[object | None, str | None]:
    definition = get_metric_def(metric)
    if not definition:
        return None, "Unknown metric"
    if definition.kind == "bool":
        parsed = _parse_bool(raw)
        if parsed is None:
            return None, "Expected boolean value"
        return parsed, None
    if definition.kind == "event":
        parsed = _parse_bool(raw)
        if parsed is not None:
            return parsed, None
    cleaned = raw.strip().lower()
    if cleaned.endswith("%"):
        cleaned = cleaned[:-1]
    if cleaned.endswith("c"):
        cleaned = cleaned[:-1]
    try:
        value = float(cleaned)
    except ValueError:
        return None, "Expected numeric value"
    if definition.unit == "percent" and value <= 1.0:
        value *= 100.0
    return value, None


def format_duration(duration_s: int) -> str:
    if duration_s % 3600 == 0 and duration_s >= 3600:
        return f"{duration_s // 3600}h"
    if duration_s % 60 == 0 and duration_s >= 60:
        return f"{duration_s // 60}m"
    return f"{duration_s}s"


def format_threshold(metric: str, value: object) -> str:
    definition = get_metric_def(metric)
    if not definition or value is None:
        return "n/a"
    if definition.kind == "bool":
        return "true" if bool(value) else "false"
    if isinstance(value, (int, float)):
        if definition.unit == "percent":
            return f"{value:.0f}%"
        if definition.unit == "temp":
            return f"{value:.1f}C"
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)


@dataclass
class AlertMetricValue:
    value: object | None
    display: str
    is_event: bool = False


def _format_list(values: list[str], limit: int = 3) -> str:
    if not values:
        return "none"
    if len(values) <= limit:
        return ", ".join(values)
    return f"{', '.join(values[:limit])} +{len(values) - limit} more"


def _parse_temp_value(raw: str) -> float | None:
    if not raw:
        return None
    match = re.search(r"(-?\d+(?:\.\d+)?)", raw)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


async def _ping_once(host: str) -> bool:
    ping_bin = shutil.which("ping") or "/bin/ping"
    rc, _, _ = await cli.run_cmd([ping_bin, "-c", "1", "-W", "2", host], timeout=4)
    return rc == 0


async def _ping_any(targets: list[str]) -> bool | None:
    if not targets:
        return None
    for target in targets:
        try:
            if await _ping_once(target):
                return True
        except Exception:
            continue
    return False


async def collect_alert_metrics(state: BotState) -> dict[str, AlertMetricValue]:
    disk_task = asyncio.create_task(utils.get_disk_usage_stats(config.WATCH_PATHS))
    temp_task = asyncio.create_task(utils.get_cpu_temp())
    torrent_task = asyncio.create_task(services.get_torrent_list())
    lan_task = asyncio.create_task(_ping_any(config.ALERT_PING_LAN_TARGETS))
    wan_task = asyncio.create_task(_ping_any(config.ALERT_PING_WAN_TARGETS))

    try:
        disk_stats, temp_raw, torrents, lan_up, wan_up = await asyncio.gather(
            disk_task, temp_task, torrent_task, lan_task, wan_task
        )
    except Exception:
        logger.exception("Failed collecting alert metrics")
        return {}

    max_disk = None
    max_path = None
    for item in disk_stats or []:
        try:
            pct = float(item.get("percent", 0))
        except (TypeError, ValueError):
            continue
        if max_disk is None or pct > max_disk:
            max_disk = pct
            max_path = str(item.get("path") or "")
    disk_display = "n/a"
    if max_disk is not None:
        disk_display = f"{max_disk:.0f}%"
        if max_path:
            disk_display = f"{disk_display} ({max_path})"

    try:
        load1, _, _ = os.getloadavg()
    except (OSError, AttributeError):
        load1 = None
    load_display = "n/a" if load1 is None else f"{load1:.2f}"

    mem_pct = None
    try:
        mem_pct = float(psutil.virtual_memory().percent)
    except Exception:
        mem_pct = None
    mem_display = "n/a" if mem_pct is None else f"{mem_pct:.0f}%"

    temp_val = _parse_temp_value(temp_raw)
    temp_display = "n/a" if temp_val is None else f"{temp_val:.1f}C"

    torrents = torrents or []
    stalled_names: list[str] = []
    zero_names: list[str] = []
    current_seen: dict[str, bool] = {}
    completed_names: list[str] = []

    for t in torrents:
        name = str(t.get("name") or "")
        torrent_hash = str(t.get("hash") or "")
        progress = float(t.get("progress") or 0.0)
        state_name = str(t.get("state") or "")
        dlspeed = float(t.get("dlspeed") or 0.0)
        complete = progress >= 99.9
        if torrent_hash:
            current_seen[torrent_hash] = complete
        if state_name == "stalledDL" and not complete and name:
            stalled_names.append(name)
        if (
            state_name in {"downloading", "stalledDL", "queuedDL"}
            and dlspeed <= 0
            and not complete
            and name
        ):
            zero_names.append(name)

    if not state.alert_torrent_seen:
        state.alert_torrent_seen = current_seen
    else:
        for torrent_hash, is_complete in current_seen.items():
            if is_complete and not state.alert_torrent_seen.get(torrent_hash, False):
                name = next(
                    (t.get("name") for t in torrents if t.get("hash") == torrent_hash),
                    "",
                )
                if name:
                    completed_names.append(str(name))
        state.alert_torrent_seen = current_seen

    return {
        "disk_used": AlertMetricValue(
            value=max_disk,
            display=disk_display,
        ),
        "load": AlertMetricValue(
            value=load1,
            display=load_display,
        ),
        "mem_used": AlertMetricValue(
            value=mem_pct,
            display=mem_display,
        ),
        "temp": AlertMetricValue(
            value=temp_val,
            display=temp_display,
        ),
        "lan_up": AlertMetricValue(
            value=lan_up if lan_up is not None else None,
            display="up" if lan_up else "down" if lan_up is not None else "n/a",
        ),
        "wan_up": AlertMetricValue(
            value=wan_up if wan_up is not None else None,
            display="up" if wan_up else "down" if wan_up is not None else "n/a",
        ),
        "torrent_stalled": AlertMetricValue(
            value=bool(stalled_names),
            display=_format_list(stalled_names),
        ),
        "torrent_zero_speed": AlertMetricValue(
            value=bool(zero_names),
            display=_format_list(zero_names),
        ),
        "torrent_complete": AlertMetricValue(
            value=bool(completed_names),
            display=_format_list(completed_names),
            is_event=True,
        ),
    }


def _compare(operator: str, left: object, right: object) -> bool:
    if left is None or right is None:
        return False
    if operator in {"=", "=="}:
        return left == right
    if operator == "!=":
        return left != right
    try:
        left_val = float(left)
        right_val = float(right)
    except (TypeError, ValueError):
        return False
    if operator == ">":
        return left_val > right_val
    if operator == ">=":
        return left_val >= right_val
    if operator == "<":
        return left_val < right_val
    if operator == "<=":
        return left_val <= right_val
    return False


def _is_active(state) -> bool:
    if state.last_triggered_at is None:
        return False
    if state.last_cleared_at is None:
        return True
    return state.last_triggered_at > state.last_cleared_at


def _build_alert_message(rule, metric_value: AlertMetricValue, recovered: bool) -> str:
    definition = get_metric_def(rule.metric)
    label = definition.label if definition else rule.metric
    value_display = html.escape(metric_value.display or "n/a")
    threshold = html.escape(format_threshold(rule.metric, rule.threshold))
    operator = html.escape(rule.operator)
    rule_id = html.escape(rule.id)
    if metric_value.is_event:
        return f"<b>ALERT</b> {html.escape(label)}: {value_display} [rule {rule_id}]"
    if recovered:
        return (
            f"<b>RECOVERED</b> {html.escape(label)}: "
            f"{html.escape(rule.metric)} now {value_display} [rule {rule_id}]"
        )
    duration = format_duration(rule.duration_s)
    duration_part = f" for {html.escape(duration)}" if rule.duration_s else ""
    return (
        f"<b>ALERT</b> {html.escape(label)}: {html.escape(rule.metric)} "
        f"{operator} {threshold} (value {value_display}){duration_part} "
        f"[rule {rule_id}]"
    )


def evaluate_alert_rules(
    state: BotState, metrics: dict[str, AlertMetricValue]
) -> tuple[list[tuple[int, str]], bool]:
    notifications: list[tuple[int, str]] = []
    now = time.time()
    changed = False

    for rule in state.alert_rules.values():
        if not rule.enabled:
            continue
        if not state.alerts_enabled_for(rule.chat_id):
            continue
        metric_value = metrics.get(rule.metric)
        if not metric_value:
            continue
        state_entry = state.alert_state_for(rule.id)
        state_entry.last_value = metric_value.display

        triggered = _compare(rule.operator, metric_value.value, rule.threshold)
        if metric_value.is_event:
            if triggered:
                state_entry.last_triggered_at = now
                notifications.append(
                    (rule.chat_id, _build_alert_message(rule, metric_value, False))
                )
                changed = True
            continue

        if triggered:
            if state_entry.active_since is None:
                state_entry.active_since = now
            duration_s = max(0, int(rule.duration_s or 0))
            elapsed = now - state_entry.active_since
            if elapsed >= duration_s and not _is_active(state_entry):
                state_entry.last_triggered_at = now
                notifications.append(
                    (rule.chat_id, _build_alert_message(rule, metric_value, False))
                )
                changed = True
        else:
            state_entry.active_since = None
            if _is_active(state_entry):
                state_entry.last_cleared_at = now
                notifications.append(
                    (rule.chat_id, _build_alert_message(rule, metric_value, True))
                )
                changed = True

    return notifications, changed
