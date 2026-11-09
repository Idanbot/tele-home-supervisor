"""Bounded, persistent records of unauthorized bot interactions."""

from pathlib import Path

from .models.database import connect

RETENTION_SECONDS = 90 * 86400
MAX_IDENTITIES = 1000
NOTICE_INTERVAL_SECONDS = 300


def record_attempt(
    path: Path, chat_id: int, user_id: int, name: str, action: str, now: float
) -> tuple[bool, int]:
    """Aggregate attempts and reserve at most one alert per identity per interval."""
    with connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "DELETE FROM unauthorized_attempts WHERE last_seen < ?",
            (now - RETENTION_SECONDS,),
        )
        db.execute(
            """INSERT INTO unauthorized_attempts
            (chat_id, user_id, user_name, action, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, user_id) DO UPDATE SET
            user_name=excluded.user_name, action=excluded.action,
            last_seen=excluded.last_seen, attempts=attempts+1""",
            (chat_id, user_id, name[:200], action[:120], now, now),
        )
        row = db.execute(
            "SELECT * FROM unauthorized_attempts WHERE chat_id=? AND user_id=?",
            (chat_id, user_id),
        ).fetchone()
        notify = (
            row["notified_at"] == 0
            or now - row["notified_at"] >= NOTICE_INTERVAL_SECONDS
        )
        pending = row["attempts"] - row["notified_attempts"]
        if notify:
            db.execute(
                """UPDATE unauthorized_attempts SET notified_at=?, notified_attempts=attempts
                WHERE chat_id=? AND user_id=?""",
                (now, chat_id, user_id),
            )
        db.execute(
            """DELETE FROM unauthorized_attempts WHERE rowid IN
            (SELECT rowid FROM unauthorized_attempts ORDER BY last_seen DESC, rowid DESC
            LIMIT -1 OFFSET ?)""",
            (MAX_IDENTITIES,),
        )
        return notify, pending


def recent_attempts(path: Path, now: float) -> list[dict]:
    with connect(path) as db:
        db.execute(
            "DELETE FROM unauthorized_attempts WHERE last_seen < ?",
            (now - RETENTION_SECONDS,),
        )
        return [
            dict(row)
            for row in db.execute(
                "SELECT * FROM unauthorized_attempts ORDER BY last_seen DESC LIMIT 10"
            )
        ]
