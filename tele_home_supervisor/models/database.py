"""SQLite connection and schema migration support."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 2

_MIGRATIONS: dict[int, tuple[str, ...]] = {
    1: (
        """
        CREATE TABLE state_documents (
            key TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            updated_at REAL NOT NULL
        )
        """,
        """
        CREATE TABLE audit_entries (
            id TEXT PRIMARY KEY,
            chat_id INTEGER NOT NULL,
            created_at REAL NOT NULL,
            payload TEXT NOT NULL
        )
        """,
        """
        CREATE INDEX audit_entries_chat_created_idx
        ON audit_entries(chat_id, created_at, id)
        """,
        """
        CREATE TABLE magnet_cache (
            cache_key TEXT PRIMARY KEY,
            cached_at REAL NOT NULL,
            payload TEXT NOT NULL
        )
        """,
        """
        CREATE INDEX magnet_cache_cached_at_idx
        ON magnet_cache(cached_at)
        """,
        """
        CREATE TABLE legacy_imports (
            source TEXT PRIMARY KEY,
            imported_at REAL NOT NULL
        )
        """,
    ),
    2: (
        """
        CREATE TABLE network_device_scans (
            ip TEXT NOT NULL,
            scan_id TEXT NOT NULL,
            scanned_at REAL NOT NULL,
            payload TEXT NOT NULL,
            PRIMARY KEY (ip, scan_id)
        )
        """,
        """
        CREATE INDEX network_device_scans_ip_time_idx
        ON network_device_scans(ip, scanned_at)
        """,
        """
        CREATE TABLE network_inventory_summary (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            payload TEXT NOT NULL,
            updated_at REAL NOT NULL
        )
        """,
    ),
}


def _open(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    connection.execute("PRAGMA journal_mode = WAL")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return connection


def migrate(path: Path) -> int:
    """Apply pending schema migrations and return the resulting version."""
    connection = _open(path)
    try:
        current = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if current > SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema {current} is newer than supported {SCHEMA_VERSION}"
            )

        for target in range(current + 1, SCHEMA_VERSION + 1):
            statements = _MIGRATIONS.get(target)
            if not statements:
                raise RuntimeError(f"Missing database migration {target}")
            try:
                connection.execute("BEGIN IMMEDIATE")
                for statement in statements:
                    connection.execute(statement)
                connection.execute(f"PRAGMA user_version = {target}")
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return SCHEMA_VERSION
    finally:
        connection.close()


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    """Open a migrated SQLite connection with transaction handling."""
    migrate(path)
    connection = _open(path)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def schema_version(path: Path) -> int:
    """Return the current on-disk schema version without migrating it."""
    if not path.exists():
        return 0
    connection = sqlite3.connect(path)
    try:
        return int(connection.execute("PRAGMA user_version").fetchone()[0])
    finally:
        connection.close()
