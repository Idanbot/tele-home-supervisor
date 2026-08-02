"""BotState SQLite persistence and legacy JSON import helpers.

Serialisation and deserialisation are deliberately kept in plain
functions rather than methods on *BotState* itself so that the
persistence layer can be tested and evolved independently.
"""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING

from .. import config
from . import database
from .alerts import AlertRule, AlertState
from .audit import AuditEntry
from .auth import AuthGrantRecord
from .magnet import MagnetEntry
from .network_inventory import (
    NetworkDeviceScan,
    NetworkInventoryScanSummary,
    NetworkService,
)
from .reddit_settings import RedditBriefingSettings
from .release_watch import ReleaseWatch

if TYPE_CHECKING:
    from .bot_state import BotState

logger = logging.getLogger(__name__)


def serialize(state: BotState) -> dict:
    """Build a JSON-safe dict from *state* (excluding high-frequency caches)."""
    return {
        "gameoffers_muted": list(state.gameoffers_muted),
        "hackernews_muted": list(state.hackernews_muted),
        "disabled_intel_modules": {
            str(k): list(v) for k, v in state.disabled_intel_modules.items()
        },
        "intel_fire_time": {str(k): list(v) for k, v in state.intel_fire_time.items()},
        "intel_tts_announcer": list(state.intel_tts_announcer),
        "disabled_tts_sections": {
            str(k): list(v) for k, v in state.disabled_tts_sections.items()
        },
        "cf_run_logs": [r.to_dict() for r in state.cf_run_logs],
        "cf_model_preferences": {
            str(chat_id): preferences
            for chat_id, preferences in state.cf_model_preferences.items()
        },
        "cf_voice_preferences": {
            str(chat_id): alias for chat_id, alias in state.cf_voice_preferences.items()
        },
        "reddit_briefing_settings": {
            str(chat_id): settings.to_dict()
            for chat_id, settings in state.reddit_briefing_settings.items()
        },
        "release_watches": [watch.to_dict() for watch in state.release_watches],
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
        "reminders": state.reminders,
        "last_game_offers_run": state.last_game_offers_run,
        "last_intel_briefing_run": state.last_intel_briefing_run,
        "last_intel_briefing_runs": {
            str(chat_id): timestamp
            for chat_id, timestamp in state.last_intel_briefing_runs.items()
        },
        "last_release_watch_run": state.last_release_watch_run,
    }


def save(state: BotState, path: Path) -> None:
    """Persist compact state as a single SQLite document."""
    try:
        payload = json.dumps(serialize(state), separators=(",", ":"), sort_keys=True)
        with database.connect(path) as connection:
            connection.execute(
                """
                INSERT INTO state_documents(key, payload, updated_at)
                VALUES ('core', ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (payload, time.time()),
            )
    except Exception:
        logger.exception("Failed to save bot state")


def load(state: BotState, path: Path) -> None:
    """Populate compact state from SQLite."""
    try:
        with database.connect(path) as connection:
            row = connection.execute(
                "SELECT payload FROM state_documents WHERE key = 'core'"
            ).fetchone()
        if row is None:
            return
        _deserialize_core(state, json.loads(row["payload"]))
        logger.info("Loaded bot state from %s", path)
    except Exception:
        logger.exception("Failed to load bot state")


def _deserialize_core(state: BotState, data: dict) -> None:
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

    state.intel_fire_time = {}
    raw_fire_time = data.get("intel_fire_time") or {}
    if isinstance(raw_fire_time, dict):
        for k, v in raw_fire_time.items():
            try:
                if isinstance(v, (list, tuple)) and len(v) == 2:
                    state.intel_fire_time[int(k)] = (int(v[0]), int(v[1]))
            except TypeError, ValueError:
                continue

    state.intel_tts_announcer = set(data.get("intel_tts_announcer", []))

    state.disabled_tts_sections = {}
    raw_disabled_tts = data.get("disabled_tts_sections") or {}
    if isinstance(raw_disabled_tts, dict):
        for k, v in raw_disabled_tts.items():
            try:
                state.disabled_tts_sections[int(k)] = set(v)
            except TypeError, ValueError:
                continue

    from .bot_state import CFRunRecord

    state.cf_run_logs = []
    raw_cf_logs = data.get("cf_run_logs") or []
    if isinstance(raw_cf_logs, list):
        for item in raw_cf_logs:
            if isinstance(item, dict):
                try:
                    state.cf_run_logs.append(CFRunRecord.from_dict(item))
                except TypeError, ValueError:
                    continue

    state.cf_model_preferences = {}
    raw_model_preferences = data.get("cf_model_preferences") or {}
    if isinstance(raw_model_preferences, dict):
        for chat_id, preferences in raw_model_preferences.items():
            if not isinstance(preferences, dict):
                continue
            try:
                state.cf_model_preferences[int(chat_id)] = {
                    str(kind): str(alias)
                    for kind, alias in preferences.items()
                    if kind in {"speech", "image"}
                }
            except TypeError, ValueError:
                continue

    state.cf_voice_preferences = {}
    raw_voice_preferences = data.get("cf_voice_preferences") or {}
    if isinstance(raw_voice_preferences, dict):
        for chat_id, alias in raw_voice_preferences.items():
            try:
                state.cf_voice_preferences[int(chat_id)] = str(alias)
            except TypeError, ValueError:
                continue

    state.reddit_briefing_settings = {}

    raw_reddit_settings = data.get("reddit_briefing_settings") or {}
    if isinstance(raw_reddit_settings, dict):
        for chat_id, raw_settings in raw_reddit_settings.items():
            try:
                state.reddit_briefing_settings[int(chat_id)] = (
                    RedditBriefingSettings.from_dict(raw_settings)
                )
            except TypeError, ValueError:
                continue

    state.release_watches = []
    for raw_watch in data.get("release_watches") or []:
        watch = ReleaseWatch.from_dict(raw_watch)
        if watch is not None:
            state.release_watches.append(watch)

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
    state.reminders = data.get("reminders") or []

    state.last_game_offers_run = float(data.get("last_game_offers_run") or 0.0)
    state.last_intel_briefing_run = float(data.get("last_intel_briefing_run") or 0.0)
    state.last_intel_briefing_runs = {}
    raw_intel_runs = data.get("last_intel_briefing_runs") or {}
    if isinstance(raw_intel_runs, dict):
        for chat_id, timestamp in raw_intel_runs.items():
            try:
                state.last_intel_briefing_runs[int(chat_id)] = float(timestamp)
            except TypeError, ValueError:
                continue
    state.last_release_watch_run = float(data.get("last_release_watch_run") or 0.0)

    if "audit_log" in data:
        _deserialize_audit_log(state, data["audit_log"])
    if "magnet_cache" in data:
        _deserialize_magnet_cache(state, data["magnet_cache"])


# ── Audit Log ───────────────────────────────────────────────────────


def save_audit(state: BotState, path: Path) -> None:
    try:
        rows = [
            (
                entry.id,
                chat_id,
                entry.created_at,
                json.dumps(entry.__dict__, separators=(",", ":"), sort_keys=True),
            )
            for chat_id, entries in state.audit_log.items()
            for entry in entries
        ]
        with database.connect(path) as connection:
            connection.execute("DELETE FROM audit_entries")
            connection.executemany(
                """
                INSERT INTO audit_entries(id, chat_id, created_at, payload)
                VALUES (?, ?, ?, ?)
                """,
                rows,
            )
    except Exception:
        logger.exception("Failed to save audit log")


def load_audit(state: BotState, path: Path) -> None:
    try:
        with database.connect(path) as connection:
            rows = connection.execute(
                """
                SELECT chat_id, payload
                FROM audit_entries
                ORDER BY chat_id, created_at, id
                """
            ).fetchall()
        data: dict[str, list[dict]] = {}
        for row in rows:
            data.setdefault(str(row["chat_id"]), []).append(json.loads(row["payload"]))
        _deserialize_audit_log(state, data)
    except Exception:
        logger.exception("Failed to load audit log")


def _deserialize_audit_log(state: BotState, data: dict) -> None:
    state.audit_log = {}
    for chat_id_str, entries_raw in data.items():
        try:
            chat_id = int(chat_id_str)
            entries = deque(maxlen=200)
            for e in entries_raw:
                entries.append(AuditEntry(**e))
            state.audit_log[chat_id] = entries
        except TypeError, ValueError:
            continue


# ── Magnet Cache ─────────────────────────────────────────────────────


def save_magnets(state: BotState, path: Path) -> None:
    try:
        rows = []
        for key, (cached_at, entry) in state.magnet_cache.items():
            payload = json.dumps(
                {
                    "name": entry.name,
                    "magnet": entry.magnet,
                    "seeders": entry.seeders,
                    "leechers": entry.leechers,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
            rows.append((key, cached_at, payload))
        with database.connect(path) as connection:
            connection.execute("DELETE FROM magnet_cache")
            connection.executemany(
                """
                INSERT INTO magnet_cache(cache_key, cached_at, payload)
                VALUES (?, ?, ?)
                """,
                rows,
            )
    except Exception:
        logger.exception("Failed to save magnet cache")


def load_magnets(state: BotState, path: Path) -> None:
    try:
        with database.connect(path) as connection:
            rows = connection.execute(
                """
                SELECT cache_key, cached_at, payload
                FROM magnet_cache
                ORDER BY cached_at, cache_key
                """
            ).fetchall()
        data = [
            [row["cache_key"], [row["cached_at"], json.loads(row["payload"])]]
            for row in rows
        ]
        _deserialize_magnet_cache(state, data)
    except Exception:
        logger.exception("Failed to load magnet cache")


def _deserialize_magnet_cache(state: BotState, data: list) -> None:
    from collections import OrderedDict

    state.magnet_cache = OrderedDict()
    for item in data:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            key, raw = item
            if isinstance(raw, list) and len(raw) == 2:
                ts, entry_data = raw
                if isinstance(entry_data, dict):
                    entry = MagnetEntry(
                        name=entry_data.get("name", ""),
                        magnet=entry_data.get("magnet", ""),
                        seeders=entry_data.get("seeders", 0),
                        leechers=entry_data.get("leechers", 0),
                    )
                elif isinstance(entry_data, (list, tuple)):
                    if len(entry_data) == 4:
                        entry = MagnetEntry(
                            name=entry_data[0],
                            magnet=entry_data[1],
                            seeders=entry_data[2],
                            leechers=entry_data[3],
                        )
                    elif len(entry_data) == 2:
                        entry = MagnetEntry(name=entry_data[0], magnet=entry_data[1])
                    else:
                        continue
                else:
                    continue
                state.magnet_cache[key] = (float(ts), entry)


# ── Network Inventory ─────────────────────────────────────────────────


def save_network_inventory(state: BotState, path: Path) -> None:
    try:
        rows = [
            (
                ip,
                record.scan_id,
                record.scanned_at,
                json.dumps(
                    _network_scan_to_dict(record),
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            )
            for ip, records in state.network_inventory.items()
            for record in records
        ]
        summary = state.network_inventory_last_summary
        with database.connect(path) as connection:
            connection.execute("DELETE FROM network_device_scans")
            connection.executemany(
                """
                INSERT INTO network_device_scans(ip, scan_id, scanned_at, payload)
                VALUES (?, ?, ?, ?)
                """,
                rows,
            )
            if summary is None:
                connection.execute("DELETE FROM network_inventory_summary")
            else:
                connection.execute(
                    """
                    INSERT INTO network_inventory_summary(
                        singleton, payload, updated_at
                    )
                    VALUES (1, ?, ?)
                    ON CONFLICT(singleton) DO UPDATE SET
                        payload = excluded.payload,
                        updated_at = excluded.updated_at
                    """,
                    (
                        json.dumps(
                            summary.__dict__, separators=(",", ":"), sort_keys=True
                        ),
                        time.time(),
                    ),
                )
    except Exception:
        logger.exception("Failed to save network inventory")


def load_network_inventory(state: BotState, path: Path) -> None:
    try:
        with database.connect(path) as connection:
            rows = connection.execute(
                """
                SELECT ip, payload
                FROM network_device_scans
                ORDER BY ip, scanned_at, scan_id
                """
            ).fetchall()
            summary_row = connection.execute(
                """
                SELECT payload
                FROM network_inventory_summary
                WHERE singleton = 1
                """
            ).fetchone()
        devices: dict[str, list[dict]] = {}
        for row in rows:
            devices.setdefault(str(row["ip"]), []).append(json.loads(row["payload"]))
        data = {
            "devices": devices,
            "last_summary": (
                json.loads(summary_row["payload"]) if summary_row is not None else None
            ),
        }
        _deserialize_network_inventory(state, data)
        state.prune_network_inventory(
            retention_days=config.NETWORK_INVENTORY_RETENTION_DAYS,
            max_scans_per_device=config.NETWORK_INVENTORY_MAX_SCANS_PER_DEVICE,
        )
    except Exception:
        logger.exception("Failed to load network inventory")


def _network_scan_to_dict(record: NetworkDeviceScan) -> dict:
    data = record.__dict__.copy()
    data["services"] = [service.__dict__ for service in record.services]
    return data


def _deserialize_network_inventory(state: BotState, data: dict) -> None:
    state.network_inventory = {}
    raw_devices = data.get("devices") if isinstance(data, dict) else None
    if isinstance(raw_devices, dict):
        for ip, records in raw_devices.items():
            loaded: list[NetworkDeviceScan] = []
            if not isinstance(records, list):
                continue
            for item in records:
                record = _load_network_device_scan(item)
                if record is not None:
                    loaded.append(record)
            if loaded:
                state.network_inventory[str(ip)] = loaded

    raw_summary = data.get("last_summary") if isinstance(data, dict) else None
    if isinstance(raw_summary, dict):
        try:
            state.network_inventory_last_summary = NetworkInventoryScanSummary(
                scan_id=str(raw_summary.get("scan_id") or ""),
                scanned_at=float(raw_summary.get("scanned_at") or 0.0),
                targets=[str(item) for item in raw_summary.get("targets") or []],
                devices_seen=int(raw_summary.get("devices_seen") or 0),
                new_devices=[
                    str(item) for item in raw_summary.get("new_devices") or []
                ],
                missing_devices=[
                    str(item) for item in raw_summary.get("missing_devices") or []
                ],
                scanner=str(raw_summary.get("scanner") or ""),
                error=str(raw_summary.get("error") or ""),
            )
        except TypeError, ValueError:
            state.network_inventory_last_summary = None


def _load_network_device_scan(raw: object) -> NetworkDeviceScan | None:
    if not isinstance(raw, dict):
        return None
    try:
        services = []
        for item in raw.get("services") or []:
            if not isinstance(item, dict):
                continue
            services.append(
                NetworkService(
                    port=int(item.get("port") or 0),
                    protocol=str(item.get("protocol") or "tcp"),
                    service=str(item.get("service") or ""),
                )
            )
        return NetworkDeviceScan(
            scan_id=str(raw.get("scan_id") or ""),
            scanned_at=float(raw.get("scanned_at") or 0.0),
            ip=str(raw.get("ip") or ""),
            status=str(raw.get("status") or "up"),
            hostname=str(raw.get("hostname") or ""),
            mac=str(raw.get("mac") or ""),
            vendor=str(raw.get("vendor") or ""),
            services=services,
        )
    except TypeError, ValueError:
        return None


# ── Legacy JSON import ──────────────────────────────────────────────


def initialize_and_import_legacy(
    state: BotState,
    database_path: Path,
    *,
    state_path: Path,
    audit_path: Path,
    magnet_path: Path,
    network_inventory_path: Path,
) -> None:
    """Initialize SQLite and import each legacy JSON store at most once."""
    database.migrate(database_path)
    _import_legacy_core(state, database_path, state_path)
    _import_legacy_audit(state, database_path, audit_path)
    _import_legacy_magnets(state, database_path, magnet_path)
    _import_legacy_network_inventory(state, database_path, network_inventory_path)


def _legacy_imported(database_path: Path, source: str) -> bool:
    with database.connect(database_path) as connection:
        row = connection.execute(
            "SELECT 1 FROM legacy_imports WHERE source = ?", (source,)
        ).fetchone()
    return row is not None


def _mark_legacy_imported(database_path: Path, source: str) -> None:
    with database.connect(database_path) as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO legacy_imports(source, imported_at)
            VALUES (?, ?)
            """,
            (source, time.time()),
        )


def _table_has_rows(database_path: Path, table: str) -> bool:
    queries = {
        "state_documents": "SELECT 1 FROM state_documents LIMIT 1",
        "audit_entries": "SELECT 1 FROM audit_entries LIMIT 1",
        "magnet_cache": "SELECT 1 FROM magnet_cache LIMIT 1",
        "network_device_scans": "SELECT 1 FROM network_device_scans LIMIT 1",
    }
    query = queries.get(table)
    if query is None:
        raise ValueError(f"Unsupported table: {table}")
    with database.connect(database_path) as connection:
        row = connection.execute(query).fetchone()
    return row is not None


def _read_legacy_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _import_legacy_core(state: BotState, database_path: Path, path: Path) -> None:
    source = "bot_state.json"
    if _legacy_imported(database_path, source) or not path.exists():
        return
    if _table_has_rows(database_path, "state_documents"):
        _mark_legacy_imported(database_path, source)
        return
    try:
        data = _read_legacy_json(path)
        if not isinstance(data, dict):
            raise ValueError("legacy bot state must be a JSON object")
        _deserialize_core(state, data)
        save(state, database_path)
        if "audit_log" in data:
            save_audit(state, database_path)
        if "magnet_cache" in data:
            _reset_legacy_magnet_timestamps(state)
            save_magnets(state, database_path)
        _mark_legacy_imported(database_path, source)
        logger.info("Imported legacy state from %s", path)
    except Exception:
        logger.exception("Failed to import legacy state from %s", path)


def _import_legacy_audit(state: BotState, database_path: Path, path: Path) -> None:
    source = "audit_log.json"
    if _legacy_imported(database_path, source) or not path.exists():
        return
    if _table_has_rows(database_path, "audit_entries"):
        _mark_legacy_imported(database_path, source)
        return
    try:
        data = _read_legacy_json(path)
        if not isinstance(data, dict):
            raise ValueError("legacy audit log must be a JSON object")
        _deserialize_audit_log(state, data)
        save_audit(state, database_path)
        _mark_legacy_imported(database_path, source)
        logger.info("Imported legacy audit log from %s", path)
    except Exception:
        logger.exception("Failed to import legacy audit log from %s", path)


def _reset_legacy_magnet_timestamps(state: BotState) -> None:
    now = time.time()
    state.magnet_cache = type(state.magnet_cache)(
        (key, (now, entry)) for key, (_, entry) in state.magnet_cache.items()
    )


def _import_legacy_magnets(state: BotState, database_path: Path, path: Path) -> None:
    source = "magnet_cache.json"
    if _legacy_imported(database_path, source) or not path.exists():
        return
    if _table_has_rows(database_path, "magnet_cache"):
        _mark_legacy_imported(database_path, source)
        return
    try:
        data = _read_legacy_json(path)
        if not isinstance(data, list):
            raise ValueError("legacy magnet cache must be a JSON array")
        _deserialize_magnet_cache(state, data)
        _reset_legacy_magnet_timestamps(state)
        save_magnets(state, database_path)
        _mark_legacy_imported(database_path, source)
        logger.info("Imported legacy magnet cache from %s", path)
    except Exception:
        logger.exception("Failed to import legacy magnet cache from %s", path)


def _import_legacy_network_inventory(
    state: BotState, database_path: Path, path: Path
) -> None:
    source = "network_inventory.json"
    if _legacy_imported(database_path, source) or not path.exists():
        return
    if _table_has_rows(database_path, "network_device_scans"):
        _mark_legacy_imported(database_path, source)
        return
    try:
        data = _read_legacy_json(path)
        if not isinstance(data, dict):
            raise ValueError("legacy network inventory must be a JSON object")
        _deserialize_network_inventory(state, data)
        state.prune_network_inventory(
            retention_days=config.NETWORK_INVENTORY_RETENTION_DAYS,
            max_scans_per_device=config.NETWORK_INVENTORY_MAX_SCANS_PER_DEVICE,
        )
        save_network_inventory(state, database_path)
        _mark_legacy_imported(database_path, source)
        logger.info("Imported legacy network inventory from %s", path)
    except Exception:
        logger.exception("Failed to import legacy network inventory from %s", path)


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
        backoff_level = int(state.auth_backoff_level.get(uid, 0))
        cooldown_until = state.auth_cooldowns.get(uid)
        if cooldown_until is not None and cooldown_until <= now:
            cooldown_until = None
        if attempts <= 0 and backoff_level <= 0 and cooldown_until is None:
            continue
        items.append(
            {
                "user_id": uid,
                "attempts": attempts,
                "backoff_level": backoff_level,
                "cooldown_until": cooldown_until,
            }
        )
    return items


def _deserialize_auth_failures(state: BotState, items: list) -> None:
    now = time.time()
    state.auth_failures = {}
    state.auth_backoff_level = {}
    state.auth_cooldowns = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        uid = _coerce_int(item.get("user_id"))
        attempts = _coerce_int(item.get("attempts", 0))
        backoff_level = _coerce_int(item.get("backoff_level", 0))
        cooldown_until = item.get("cooldown_until")
        if uid is None:
            continue
        if attempts is not None and attempts > 0:
            state.auth_failures[uid] = attempts
        if backoff_level is not None and backoff_level > 0:
            state.auth_backoff_level[uid] = backoff_level
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
