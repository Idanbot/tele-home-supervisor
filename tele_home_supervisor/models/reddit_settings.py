"""Persisted Reddit briefing preferences."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

REDDIT_GROUPS: dict[str, tuple[str, ...]] = {
    "fun": ("funny", "memes", "videos"),
    "tech": ("programming", "technology"),
    "devops": ("devops", "cloudcomputing", "artificial"),
}
REDDIT_FETCH_SUBREDDITS: tuple[tuple[str, str], ...] = (
    ("AI Video", "aivideo"),
    ("Memes", "memes"),
    ("Dank Memes", "dankmemes"),
    ("Art", "art"),
    ("Accidental Renaissance", "accidentalrenaissance"),
    ("Popular", "popular"),
    ("News", "news"),
)
REDDIT_MODES = {"mixed", "top", "trending", "random"}
_SUBREDDIT_RE = re.compile(r"^[A-Za-z0-9_]{2,21}$")


def normalize_subreddit(value: str) -> str | None:
    """Return a canonical subreddit name, or None when invalid."""
    name = value.strip()
    if name.lower().startswith("r/"):
        name = name[2:]
    if not _SUBREDDIT_RE.fullmatch(name):
        return None
    return name.lower()


@dataclass
class RedditBriefingSettings:
    """Per-chat Reddit briefing configuration."""

    enabled_groups: set[str] = field(default_factory=lambda: set(REDDIT_GROUPS))
    custom_subreddits: set[str] = field(default_factory=set)
    post_count: int = 3
    mode: str = "mixed"

    @classmethod
    def from_dict(cls, raw: object) -> RedditBriefingSettings:
        if not isinstance(raw, dict):
            return cls()

        groups = raw.get("enabled_groups")
        enabled_groups = (
            {str(item) for item in groups if str(item) in REDDIT_GROUPS}
            if isinstance(groups, list)
            else set(REDDIT_GROUPS)
        )
        custom = raw.get("custom_subreddits")
        custom_subreddits = set()
        if isinstance(custom, list):
            custom_subreddits = {
                normalized
                for item in custom
                if (normalized := normalize_subreddit(str(item))) is not None
            }

        try:
            post_count = max(1, min(5, int(raw.get("post_count", 3))))
        except TypeError, ValueError:
            post_count = 3

        mode = str(raw.get("mode", "mixed")).lower()
        if mode not in REDDIT_MODES:
            mode = "mixed"

        return cls(enabled_groups, custom_subreddits, post_count, mode)

    def to_dict(self) -> dict[str, object]:
        return {
            "enabled_groups": sorted(self.enabled_groups),
            "custom_subreddits": sorted(self.custom_subreddits),
            "post_count": self.post_count,
            "mode": self.mode,
        }

    def subreddits(self) -> list[str]:
        names = set(self.custom_subreddits)
        for group in self.enabled_groups:
            names.update(REDDIT_GROUPS.get(group, ()))
        return sorted(names)
