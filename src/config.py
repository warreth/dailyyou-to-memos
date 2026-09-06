"""Dataclasses for configuration, migration state, and the final memo format."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Mood value -> (emoji, mood tag). Covers the real Daily You range -2..2,
# plus 0 and NULL ("no mood"). Values outside the map render no mood line.
_MOOD_TO_TAG: dict[Optional[int], tuple[str, str]] = {
    -2: ("\U0001F62D", "#mood/awful"),     # loudly crying
    -1: ("\U0001F615", "#mood/bad"),       # sad face
    0: ("\U0001F610", "#mood/neutral"),   # neutral face
    1: ("\U0001F642", "#mood/good"),       # slight smile
    2: ("\U0001F60A", "#mood/happy"),      # smiling eyes
    3: ("\U0001F60A", "#mood/great"),
    4: ("\U0001F60A", "#mood/great"),
    5: ("\U0001F60A", "#mood/happy"),
    # NULL mood: no line at all
}


def mood_to_emoji(mood: Optional[int]) -> str | None:
    mapped = _MOOD_TO_TAG.get(mood)
    return mapped[0] if mapped else None


def mood_to_tag(mood: Optional[int]) -> str | None:
    mapped = _MOOD_TO_TAG.get(mood)
    return mapped[1] if mapped else None


@dataclass(frozen=True)
class MemosApiSettings:
    base_url: str  # e.g. https://memos.example.com (no trailing /api/v1)
    token: str
    visibility: str = "PRIVATE"
    request_delay: float = 0.5
    max_retries: int = 3
    timeout: float = 30.0

    @property
    def api_v1(self) -> str:
        return self.base_url.rstrip("/") + "/api/v1"


@dataclass(frozen=True)
class MigrationOptions:
    global_tags: tuple[str, ...] = ()
    add_mood_tags: bool = True


@dataclass(frozen=True)
class ExtractedBackup:
    db_path: Path
    images_dir: Path


@dataclass
class JournalImage:
    """A local image file linked to an entry, resolved and existence-checked."""

    path: Path
    rank: int = 0

    @property
    def filename(self) -> str:
        return self.path.name


@dataclass
class Entry:
    id: int
    text: str
    mood: Optional[int]
    created_at: datetime
    images: list[JournalImage] = field(default_factory=list)
    custom_tags: list[str] = field(default_factory=list)

    @property
    def mood_emoji(self) -> Optional[str]:
        return mood_to_emoji(self.mood)

    def render_content(self, options: MigrationOptions) -> str:
        """Final memo format:
        Mood: <emoji>
        <original text>
        <tags line>
        """
        lines: list[str] = []
        if self.mood_emoji:
            lines.append(f"Mood: {self.mood_emoji}")
        lines.append(self.text.rstrip())

        tags: list[str] = list(options.global_tags)
        if options.add_mood_tags:
            mood_tag = mood_to_tag(self.mood)
            if mood_tag:
                tags.append(mood_tag)
        tags.extend(self.custom_tags)

        if tags:
            lines.append(" ".join(self._normalize_tag(t) for t in tags))
        return "\n".join(lines).strip() + "\n"

    @staticmethod
    def _normalize_tag(raw: str) -> str:
        tag = raw.strip().lstrip("#").replace(" ", "-")
        return f"#{tag}"

    @property
    def tags_preview(self) -> str:
        """Preview of tags incl. global + mood, without custom (UI shows custom separately)."""
        return " ".join(self.custom_tags) if self.custom_tags else ""


def ensure_utc(dt: datetime) -> datetime:
    """Attach UTC to naive datetimes so ISO strings sort and compare predictably."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
