"""Audit log entry dataclass."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AuditEntry:
    id: str
    chat_id: int
    user_id: int | None
    user_name: str
    action: str
    target: str | None
    status: str
    duration_ms: int
    created_at: float
