"""BotState JSON persistence helpers.

Serialisation and deserialisation are deliberately kept in plain
functions rather than methods on *BotState* itself so that the
persistence layer can be tested and evolved independently.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

from .. import config
from .alerts import AlertRule, AlertState
from .auth import AuthGrantRecord

if TYPE_CHECKING:
    from .bot_state import BotState

logger = logging.getLogger(__name__)


def serialize(state: BotState) -> dict:
    """Build a JSON-safe dict from *state*."""
    return {
        "gameoffers_muted": list(state.gameoffers_muted),
        "hackernews_muted": list(state.hackernews_muted),
        "disabled_intel_modules": {
            str(k): list(v) for k, v in state.disabled_intel_modules.items()
        },
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
        "blocked_ids": sorted(state.blocked_ids),
        "auth_failures": _serialize_auth_failures(state),
        "media_messages": state.media_messages,
    }


def save(state: BotState, path: Path) -> None:
    """Persist *state* to *path* as JSON."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(serialize(state), indent=2, sort_keys=True)
        _atomic_write_text(path, payload)
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

        state.disabled_intel_modules = {}
        raw_disabled = data.get("disabled_intel_modules") or {}
        for k, v in raw_disabled.items():
            try:
                state.disabled_intel_modules[int(k)] = set(v)
            except TypeError, ValueError:
                continue

        state.torrent_completion_subscribers = set(
            data.get("torrent_completion_subscribers", [])
        )
        state.alerts_enabled = set(data.get("alerts_enabled", []))
        state.blocked_ids = _load_blocked_ids(data.get("blocked_ids") or [])

        _load_alert_rules(state, data.get("alert_rules") or [])
        _load_alert_states(state, data.get("alert_states") or {})
        _deserialize_auth_grants(state, data.get("auth_grants") or [])
        _deserialize_auth_failures(state, data.get("auth_failures") or [])
        state.media_messages = _load_media_messages(data.get("media_messages") or [])

        logger.info("Loaded bot state from %s", path)
    except Exception:
        logger.exception("Failed to load bot state")


# ── Auth grants ─────────────────────────────────────────────────────


def _serialize_auth_grants(state: BotState) -> list[dict]:
    now = time.time()
    items: list[dict] = []
    if state.auth_records:
        for uid, record in sorted(state.auth_records.items()):
            if not record.is_active(now):
                continue
            items.append(
                {
                    "user_id": uid,
                    "granted_at": record.granted_at,
                    "expires_at": record.expires_at,
                    "username": record.username,
                    "user_name": record.user_name,
                }
            )
        return items
    for uid, exp in sorted(state.auth_grants.items()):
        if exp <= now:
            continue
        items.append(
            {
                "user_id": uid,
                "granted_at": exp - (config.BOT_AUTH_TTL_HOURS * 3600),
                "expires_at": exp,
            }
        )
    return items


def _deserialize_auth_grants(state: BotState, grants: list) -> None:
    now = time.time()
    state.auth_grants = {}
    state.auth_records = {}
    for item in grants:
        if not isinstance(item, dict):
            continue
        uid = item.get("user_id")
        exp = item.get("expires_at", item.get("expiry"))
        granted_at = item.get("granted_at")
        if uid is None or exp is None:
            continue
        try:
            uid = int(uid)
            exp = float(exp)
            if granted_at is None:
                granted_at = exp - (config.BOT_AUTH_TTL_HOURS * 3600)
            granted_at = float(granted_at)
        except TypeError, ValueError:
            continue
        if exp > now:
            state.auth_grants[uid] = exp
            state.auth_records[uid] = AuthGrantRecord(
                user_id=uid,
                granted_at=granted_at,
                expires_at=exp,
                username=_coerce_optional_str(item.get("username")),
                user_name=_coerce_optional_str(item.get("user_name")),
            )


def _serialize_auth_failures(state: BotState) -> list[dict]:
    now = time.time()
    items: list[dict] = []
    user_ids = set(state.auth_failures) | set(state.auth_cooldowns)
    for uid in sorted(user_ids):
        attempts = int(state.auth_failures.get(uid, 0))
        cooldown_until = state.auth_cooldowns.get(uid)
        if cooldown_until is not None and cooldown_until <= now:
            cooldown_until = None
        if attempts <= 0 and cooldown_until is None:
            continue
        items.append(
            {
                "user_id": uid,
                "attempts": attempts,
                "cooldown_until": cooldown_until,
            }
        )
    return items


def _deserialize_auth_failures(state: BotState, items: list) -> None:
    now = time.time()
    state.auth_failures = {}
    state.auth_cooldowns = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        uid = _coerce_int(item.get("user_id"))
        attempts = _coerce_int(item.get("attempts", 0))
        cooldown_until = item.get("cooldown_until")
        if uid is None:
            continue
        if attempts is not None and attempts > 0:
            state.auth_failures[uid] = attempts
        try:
            cooldown_value = (
                float(cooldown_until) if cooldown_until is not None else None
            )
        except TypeError, ValueError:
            cooldown_value = None
        if cooldown_value is not None and cooldown_value > now:
            state.auth_cooldowns[uid] = cooldown_value


def _load_blocked_ids(raw: list) -> set[int]:
    blocked: set[int] = set()
    for item in raw:
        uid = _coerce_int(item)
        if uid is not None:
            blocked.add(uid)
    return blocked


def _coerce_optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _atomic_write_text(path: Path, payload: str) -> None:
    """Atomically replace *path* with *payload*."""
    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        try:
            dir_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


# ── Alert rules / state ─────────────────────────────────────────────


def _coerce_int(value: object) -> int | None:
    try:
        return int(value)
    except TypeError, ValueError:
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
        except TypeError, ValueError:
            continue
    return result
