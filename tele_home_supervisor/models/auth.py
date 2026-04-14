"""Authentication grant models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class AuthGrantRecord:
    """Persisted authentication window for a single user."""

    user_id: int
    granted_at: float
    expires_at: float
    username: str | None = None
    user_name: str | None = None

    def is_active(self, now: float) -> bool:
        return self.expires_at > now
