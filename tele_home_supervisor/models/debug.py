"""Debug cache dataclasses and helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DebugEntry:
    timestamp: float
    message: str
    details: str | None = None


class DebugRecorder:
    def __init__(self, state) -> None:
        self._state = state

    def record(self, command: str, message: str, details: str | None = None) -> None:
        self._state.add_debug(command, message, details)

    def capture(self, command: str, message: str):
        def _sink(details: str | None = None) -> None:
            self._state.add_debug(command, message, details)

        return _sink
