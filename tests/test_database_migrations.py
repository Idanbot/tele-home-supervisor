from __future__ import annotations

import json
import sqlite3
import time
from collections import deque

import pytest

from tele_home_supervisor.models import database
from tele_home_supervisor.models.audit import AuditEntry
from tele_home_supervisor.models.bot_state import BotState


def test_fresh_database_applies_all_migrations(tmp_path) -> None:
    path = tmp_path / "state.sqlite3"

    assert database.migrate(path) == database.SCHEMA_VERSION
    assert database.schema_version(path) == database.SCHEMA_VERSION

    with database.connect(path) as connection:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]

    assert {
        "state_documents",
        "audit_entries",
        "magnet_cache",
        "legacy_imports",
        "network_device_scans",
        "network_inventory_summary",
    } <= tables
    assert journal_mode == "wal"
    assert path.stat().st_mode & 0o777 == 0o600


def test_upgrade_from_v1_preserves_existing_data(tmp_path) -> None:
    path = tmp_path / "state.sqlite3"
    connection = sqlite3.connect(path)
    try:
        for statement in database._MIGRATIONS[1]:
            connection.execute(statement)
        connection.execute("PRAGMA user_version = 1")
        connection.execute(
            """
            INSERT INTO state_documents(key, payload, updated_at)
            VALUES ('core', '{"gameoffers_muted":[7]}', 1.0)
            """
        )
        connection.commit()
    finally:
        connection.close()

    database.migrate(path)

    with database.connect(path) as connection:
        payload = connection.execute(
            "SELECT payload FROM state_documents WHERE key = 'core'"
        ).fetchone()["payload"]
        network_table = connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'network_device_scans'
            """
        ).fetchone()

    assert json.loads(payload)["gameoffers_muted"] == [7]
    assert network_table is not None
    assert database.schema_version(path) == 2


def test_newer_database_schema_is_rejected(tmp_path) -> None:
    path = tmp_path / "state.sqlite3"
    connection = sqlite3.connect(path)
    try:
        connection.execute(f"PRAGMA user_version = {database.SCHEMA_VERSION + 1}")
    finally:
        connection.close()

    with pytest.raises(RuntimeError, match="newer than supported"):
        database.migrate(path)


def test_legacy_json_stores_import_once(tmp_path) -> None:
    now = time.time()
    core_path = tmp_path / "bot_state.json"
    audit_path = tmp_path / "audit_log.json"
    magnet_path = tmp_path / "magnet_cache.json"
    inventory_path = tmp_path / "network_inventory.json"
    database_path = tmp_path / "state.sqlite3"

    core_path.write_text(
        json.dumps(
            {
                "gameoffers_muted": [11],
                "torrent_completion_subscribers": [22],
                "media_messages": [[11, 99, now]],
            }
        )
    )
    audit_path.write_text(
        json.dumps(
            {
                "11": [
                    {
                        "id": "audit-1",
                        "chat_id": 11,
                        "user_id": 12,
                        "user_name": "Idan",
                        "action": "health",
                        "target": None,
                        "status": "ok",
                        "duration_ms": 5,
                        "created_at": now,
                    }
                ]
            }
        )
    )
    magnet_path.write_text(
        json.dumps(
            [
                [
                    "magnet-1",
                    [
                        1.0,
                        {
                            "name": "Ubuntu",
                            "magnet": "magnet:?xt=urn:btih:test",
                            "seeders": 10,
                            "leechers": 2,
                        },
                    ],
                ]
            ]
        )
    )
    inventory_path.write_text(
        json.dumps(
            {
                "last_summary": {
                    "scan_id": "scan-1",
                    "scanned_at": now,
                    "targets": ["192.168.1.0/24"],
                    "devices_seen": 1,
                    "scanner": "nmap",
                },
                "devices": {
                    "192.168.1.10": [
                        {
                            "scan_id": "scan-1",
                            "scanned_at": now,
                            "ip": "192.168.1.10",
                            "status": "up",
                            "services": [
                                {"port": 22, "protocol": "tcp", "service": "ssh"}
                            ],
                        }
                    ]
                },
            }
        )
    )

    state = _legacy_state(
        database_path, core_path, audit_path, magnet_path, inventory_path
    )
    state.load_state()

    assert state.gameoffers_muted == {11}
    assert state.torrent_completion_subscribers == {22}
    assert state.get_audit_entries(11, 10)[0].action == "health"
    assert state.get_magnet("magnet-1") is not None
    assert state.latest_network_inventory()[0].services[0].service == "ssh"

    core_path.write_text(json.dumps({"gameoffers_muted": [999]}))
    reloaded = _legacy_state(
        database_path, core_path, audit_path, magnet_path, inventory_path
    )
    reloaded.load_state()

    assert reloaded.gameoffers_muted == {11}
    with database.connect(database_path) as connection:
        imports = connection.execute("SELECT source FROM legacy_imports").fetchall()
    assert {row["source"] for row in imports} == {
        "bot_state.json",
        "audit_log.json",
        "magnet_cache.json",
        "network_inventory.json",
    }


def test_audit_rows_remain_bounded_per_chat(tmp_path) -> None:
    state = BotState()
    state._database_file = tmp_path / "state.sqlite3"
    state.audit_log[5] = deque(maxlen=200)
    for index in range(250):
        state.audit_log[5].append(
            AuditEntry(
                id=f"audit-{index}",
                chat_id=5,
                user_id=5,
                user_name="user",
                action="test",
                target=None,
                status="ok",
                duration_ms=1,
                created_at=float(index),
            )
        )

    state.save_audit(force=True)

    with database.connect(state._database_file) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM audit_entries WHERE chat_id = 5"
        ).fetchone()[0]
    assert count == 200


def _legacy_state(
    database_path,
    core_path,
    audit_path,
    magnet_path,
    inventory_path,
) -> BotState:
    state = BotState()
    state._database_file = database_path
    state._state_file = core_path
    state._audit_file = audit_path
    state._magnet_file = magnet_path
    state._network_inventory_file = inventory_path
    return state
