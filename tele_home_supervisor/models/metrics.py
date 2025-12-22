"""Command metrics dataclass."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CommandMetrics:
    count: int = 0
    success: int = 0
    error: int = 0
    rate_limited: int = 0
    total_latency_s: float = 0.0
    max_latency_s: float = 0.0
    latencies_s: list[float] = field(default_factory=list)
    last_error: str | None = None
    last_run_ts: float | None = None
