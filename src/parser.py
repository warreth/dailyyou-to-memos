"""Parse the Daily You SQLite database into Entry objects.

Robust to schema variation: table and column names are resolved dynamically
from PRAGMA table_info against synonym candidate lists.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

from .config import Entry, JournalImage, ensure_utc

# Column synonyms for schema flexibility (spec: entries|entry, entry_images|images)
TEXT_COLS = ("text", "content", "body")
MOOD_COLS = ("mood", "rating", "mood_value")
TIME_COLS = ("time_create", "created_at", "create_time", "date", "timestamp")
ID_COLS = ("id", "entry_id")
IMG_PATH_COLS = ("img_path", "path", "filename", "image_path")
IMG_RANK_COLS = ("img_rank", "rank", "sort_order")
IMG_ENTRY_ID_COLS = ("entry_id", "id_entry", "entry")

ENTRY_TABLES = ("entries", "entry", "daily_entries", "journal_entries")
IMAGE_TABLES = ("entry_images", "images", "entry_image", "image")


def _column_names(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def _resolve_column(table_cols: Sequence[str], synonyms: Sequence[str], table: str) -> Optional[str]:
    for syn in synonyms:
        if syn in table_cols:
            return syn
    raise sqlite3.DatabaseError(
        f"Cannot find any of {list(synonyms)} in table '{table}'. Columns: {list(table_cols)}"
    )


def _find_table(conn: sqlite3.Connection, candidates: Sequence[str]) -> Optional[str]:
    tables = {
        row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    for name in candidates:
        if name in tables:
            return name
    return None


def _parse_timestamp(raw: Any) -> datetime:
    """Handle ISO-8601 (local and Z-suffixed UTC), epoch-ms, and epoch-s."""
    if isinstance(raw, (int, float)):
        ts = float(raw)
        # Epoch milliseconds vs seconds heuristic: > 10^12 means milliseconds
        if ts > 1e12:
            ts /= 1000.0
        return ensure_utc(datetime.fromtimestamp(ts, tz=timezone.utc))
    if isinstance(raw, str):
        s = raw.strip()
        iso = s.replace("Z", "+00:00") if s.endswith("Z") else s
        try:
            return ensure_utc(datetime.fromisoformat(iso))
        except ValueError:
            pass
        # Fall through to epoch-as-string
        try:
            return _parse_timestamp(float(s))
        except ValueError:
            pass
    raise ValueError(f"Unparseable timestamp: {raw!r}")


def parse_backup(db_path: Path, images_dir: Path) -> tuple[list[Entry], list[str]]:
    """Read entries and linked images. Returns (entries, warnings).

    Missing image files produce warnings, not errors - the entry still migrates.
    """
    warnings: list[str] = []
    # Read-only URI connection: never write to the only copy of the data.
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        entry_table = _find_table(conn, ENTRY_TABLES)
        if not entry_table:
            raise sqlite3.DatabaseError(
                f"No entry table found. Tables: {_table_names(conn)}"
            )
        entry_cols = _column_names(conn, entry_table)
        col_id = _resolve_column(entry_cols, ID_COLS, entry_table)
        col_text = _resolve_column(entry_cols, TEXT_COLS, entry_table)
        col_mood = next((c for c in MOOD_COLS if c in entry_cols), None)
        col_time = _resolve_column(entry_cols, TIME_COLS, entry_table)

        rows = conn.execute(
            f"SELECT {col_id}, {col_text}, {col_mood or 'NULL'}, {col_time} "
            f"FROM {entry_table}"
        ).fetchall()
        raw_entries: dict[int, dict[str, Any]] = {}
        order: list[int] = []
        for row in rows:
            eid = int(row[0])
            order.append(eid)
            raw_entries[eid] = {"text": str(row[1] or ""), "mood": row[2], "raw_time": row[3]}

        images_by_entry = _load_images(conn, images_dir, warnings)

        entries: list[Entry] = []
        for eid in order:
            raw = raw_entries[eid]
            try:
                created = _parse_timestamp(raw["raw_time"])
            except ValueError as exc:
                warnings.append(f"Entry {eid}: {exc}; using fallback epoch 0")
                created = datetime.fromtimestamp(0, tz=timezone.utc)
            entries.append(
                Entry(
                    id=eid,
                    text=raw["text"],
                    mood=_coerce_mood(raw["mood"]),
                    created_at=created,
                    images=images_by_entry.get(eid, []),
                )
            )
        return entries, warnings
    finally:
        conn.close()


def _coerce_mood(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _load_images(
    conn: sqlite3.Connection, images_dir: Path, warnings: list[str]
) -> dict[int, list[JournalImage]]:
    image_table = _find_table(conn, IMAGE_TABLES)
    if not image_table:
        return {}
    cols = _column_names(conn, image_table)
    col_entry_id = _resolve_column(cols, IMG_ENTRY_ID_COLS, image_table)
    col_path = _resolve_column(cols, IMG_PATH_COLS, image_table)
    col_rank = next((c for c in IMG_RANK_COLS if c in cols), None)

    sql = (
        f"SELECT {col_entry_id}, {col_path}"
        + (f", {col_rank}" if col_rank else "")
        + f" FROM {image_table}"
        + (f" ORDER BY {col_rank}" if col_rank else "")
    )
    by_entry: dict[int, list[JournalImage]] = {}
    for row in conn.execute(sql):
        entry_id = int(row[0])
        filename = str(row[1] or "")
        if not filename:
            continue
        # img_path is a bare filename in the real schema; resolve inside images_dir
        # with a containment check (defense against crafted paths).
        candidate = (images_dir / filename).resolve()
        if not candidate.is_relative_to(images_dir.resolve()):
            warnings.append(f"Entry {entry_id}: skipped unsafe image path {filename!r}")
            continue
        if not candidate.is_file():
            warnings.append(f"Entry {entry_id}: image file missing: {filename}")
            continue
        rank = int(row[2]) if col_rank and row[2] is not None else len(by_entry.get(entry_id, []))
        by_entry.setdefault(entry_id, []).append(JournalImage(path=candidate, rank=rank))
    return by_entry


def _table_names(conn: sqlite3.Connection) -> list[str]:
    return [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
