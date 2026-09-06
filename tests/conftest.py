"""Shared fixtures: an in-memory SQLite DB mirroring the real Daily You schema."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

import pytest

SCHEMA = """
CREATE TABLE entries (
  id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
  text TEXT NOT NULL,
  mood INTEGER,
  time_create DATETIME NOT NULL DEFAULT (DATETIME('now'))
);
CREATE TABLE entry_images (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER NOT NULL,
    img_path TEXT NOT NULL,
    img_rank INTEGER NOT NULL,
    time_create DATETIME NOT NULL DEFAULT (DATETIME('now')),
    FOREIGN KEY (entry_id) REFERENCES entries (id)
);
"""


@pytest.fixture
def make_db(tmp_path: Path):
    """Factory: (rows, images) -> Path to sqlite file plus Images/ dir with real files."""

    def _make(
        rows: Sequence[tuple[Optional[int], str, str]],
        images: Iterable[tuple[int, str, int]] = (),
    ) -> Path:
        db_path = tmp_path / "daily_you.db"
        images_dir = tmp_path / "Images"
        images_dir.mkdir(exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.executescript(SCHEMA)
        for mood, text, ts in rows:
            conn.execute(
                "INSERT INTO entries (text, mood, time_create) VALUES (?, ?, ?)",
                (text, mood, ts),
            )
        for entry_id, filename, rank in images:
            (images_dir / filename).write_bytes(b"fake-jpeg-bytes")
            conn.execute(
                "INSERT INTO entry_images (entry_id, img_path, img_rank) VALUES (?, ?, ?)",
                (entry_id, filename, rank),
            )
        conn.commit()
        conn.close()
        return db_path

    return _make
