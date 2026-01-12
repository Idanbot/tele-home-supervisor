"""Alert rule/state dataclasses."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AlertRule:
    id: str
    chat_id: int
    metric: str
    operator: str
    threshold: object
    duration_s: int
    enabled: bool = True


@dataclass
class AlertState:
    last_triggered_at: float | None = None
    last_cleared_at: float | None = None
    last_value: str | None = None
    active_since: float | None = None
