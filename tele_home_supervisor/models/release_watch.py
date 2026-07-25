"""Persisted one-shot release watches."""

from __future__ import annotations

from dataclasses import dataclass

WATCH_KINDS = {"movie", "episode", "game"}
VIDEO_QUALITIES = ("480p", "720p", "1080p", "1440p", "2160p")


@dataclass
class ReleaseWatch:
    id: str
    chat_id: int
    kind: str
    query: str
    min_quality: str | None
    enabled: bool
    created_at: float
    last_checked_at: float = 0.0
    triggered_at: float = 0.0
    matched_name: str | None = None

    @classmethod
    def from_dict(cls, raw: object) -> ReleaseWatch | None:
        if not isinstance(raw, dict):
            return None
        try:
            kind = str(raw["kind"]).lower()
            query = str(raw["query"]).strip()
            min_quality = raw.get("min_quality")
            if min_quality is not None:
                min_quality = str(min_quality).lower()
            if (
                kind not in WATCH_KINDS
                or not query
                or (kind != "game" and min_quality not in VIDEO_QUALITIES)
            ):
                return None
            return cls(
                id=str(raw["id"]),
                chat_id=int(raw["chat_id"]),
                kind=kind,
                query=query,
                min_quality=min_quality if kind != "game" else None,
                enabled=bool(raw.get("enabled", True)),
                created_at=float(raw.get("created_at", 0.0)),
                last_checked_at=float(raw.get("last_checked_at", 0.0)),
                triggered_at=float(raw.get("triggered_at", 0.0)),
                matched_name=(
                    str(raw["matched_name"]) if raw.get("matched_name") else None
                ),
            )
        except KeyError, TypeError, ValueError:
            return None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "chat_id": self.chat_id,
            "kind": self.kind,
            "query": self.query,
            "min_quality": self.min_quality,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "last_checked_at": self.last_checked_at,
            "triggered_at": self.triggered_at,
            "matched_name": self.matched_name,
        }
