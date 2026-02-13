"""BotState JSON persistence helpers.

Serialisation and deserialisation are deliberately kept in plain
functions rather than methods on *BotState* itself so that the
persistence layer can be tested and evolved independently.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from .alerts import AlertRule, AlertState

if TYPE_CHECKING:
    from .bot_state import BotState

logger = logging.getLogger(__name__)


def serialize(state: BotState) -> dict:
    """Build a JSON-safe dict from *state*."""
    return {
        "gameoffers_muted": list(state.gameoffers_muted),
        "hackernews_muted": list(state.hackernews_muted),
        "torrent_completion_subscribers": list(state.torrent_completion_subscribers),
        "alerts_enabled": list(state.alerts_enabled),
        "alert_rules": [
            {
                "id": rule.id,
                "chat_id": rule.chat_id,
                "metric": rule.metric,
                "operator": rule.operator,
                "threshold": rule.threshold,
                "duration_s": rule.duration_s,
                "enabled": rule.enabled,
            }
            for rule in state.alert_rules.values()
        ],
        "alert_states": {
            rule_id: {
                "last_triggered_at": st.last_triggered_at,
                "last_cleared_at": st.last_cleared_at,
                "last_value": st.last_value,
                "active_since": st.active_since,
            }
            for rule_id, st in state.alert_states.items()
        },
        "auth_grants": _serialize_auth_grants(state),
        "media_messages": state.media_messages,
    }


def save(state: BotState, path: Path) -> None:
    """Persist *state* to *path* as JSON."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(serialize(state), indent=2))
    except Exception:
        logger.exception("Failed to save bot state")


def load(state: BotState, path: Path) -> None:
    """Populate *state* from *path*.  No-op when the file is missing."""
    try:
        if not path.exists():
            return
        data = json.loads(path.read_text())

        legacy_epic = set(data.get("epic_games_muted", []))
        state.gameoffers_muted = set(data.get("gameoffers_muted", [])) or legacy_epic
        state.hackernews_muted = set(data.get("hackernews_muted", []))
        state.torrent_completion_subscribers = set(
            data.get("torrent_completion_subscribers", [])
        )
        state.alerts_enabled = set(data.get("alerts_enabled", []))

        _load_alert_rules(state, data.get("alert_rules") or [])
        _load_alert_states(state, data.get("alert_states") or {})
        _deserialize_auth_grants(state, data.get("auth_grants") or [])
        state.media_messages = _load_media_messages(data.get("media_messages") or [])

        logger.info("Loaded bot state from %s", path)
    except Exception:
        logger.exception("Failed to load bot state")


# ── Auth grants ─────────────────────────────────────────────────────


def _serialize_auth_grants(state: BotState) -> list[dict]:
    now = time.time()
    return [
        {"user_id": uid, "expiry": exp}
        for uid, exp in state.auth_grants.items()
        if exp > now
    ]


def _deserialize_auth_grants(state: BotState, grants: list) -> None:
    now = time.time()
    state.auth_grants = {}
    for item in grants:
        if not isinstance(item, dict):
            continue
        uid = item.get("user_id")
        exp = item.get("expiry")
        if uid is None or exp is None:
            continue
        try:
            uid, exp = int(uid), float(exp)
        except (TypeError, ValueError):
            continue
        if exp > now:
            state.auth_grants[uid] = exp


# ── Alert rules / state ─────────────────────────────────────────────


def _coerce_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _load_alert_rules(state: BotState, items: list) -> None:
    state.alert_rules = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        rule_id = str(item.get("id", ""))
        chat_id = _coerce_int(item.get("chat_id"))
        duration_s = _coerce_int(item.get("duration_s", 0))
        if not rule_id or not chat_id:
            continue
        if duration_s is None:
            duration_s = 0
        rule = AlertRule(
            id=rule_id,
            chat_id=chat_id,
            metric=str(item.get("metric", "")),
            operator=str(item.get("operator", "")),
            threshold=item.get("threshold"),
            duration_s=duration_s,
            enabled=bool(item.get("enabled", True)),
        )
        state.alert_rules[rule.id] = rule


def _load_alert_states(state: BotState, raw: dict) -> None:
    state.alert_states = {}
    for rule_id, st in raw.items():
        if not isinstance(st, dict):
            continue
        state.alert_states[str(rule_id)] = AlertState(
            last_triggered_at=st.get("last_triggered_at"),
            last_cleared_at=st.get("last_cleared_at"),
            last_value=st.get("last_value"),
            active_since=st.get("active_since"),
        )


# ── Media messages ──────────────────────────────────────────────────


def _load_media_messages(raw: list) -> list[list]:
    """Deserialise media message entries, dropping malformed ones."""
    result: list[list] = []
    for entry in raw:
        if not isinstance(entry, (list, tuple)) or len(entry) < 3:
            continue
        try:
            result.append([int(entry[0]), int(entry[1]), float(entry[2])])
        except (TypeError, ValueError):
            continue
    return result
