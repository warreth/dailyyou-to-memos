"""Parser tests against an in-memory-schema SQLite DB (real schema mirrored)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.parser import _parse_timestamp, parse_backup


def _images_dir(db_path: Path) -> Path:
    return db_path.parent / "Images"


class TestTimestamps:
    def test_iso_local_with_microseconds(self):
        dt = _parse_timestamp("2025-01-02T17:06:00.266902")
        assert dt == datetime(2025, 1, 2, 17, 6, 0, 266902, tzinfo=timezone.utc)

    def test_iso_z_suffix(self):
        dt = _parse_timestamp("2025-01-03T00:00:00.000Z")
        assert dt.tzinfo is not None
        assert dt.year == 2025 and dt.month == 1 and dt.day == 3

    def test_epoch_milliseconds(self):
        dt = _parse_timestamp(1735832760266)
        assert dt.year == 2025

    def test_epoch_seconds(self):
        dt = _parse_timestamp(1735832760)
        assert dt.year == 2025

    def test_garbage_raises(self):
        with pytest.raises(ValueError):
            _parse_timestamp("not-a-date")


class TestParseBackup:
    def test_basic_entries_and_images(self, make_db):
        db = make_db(
            rows=[(2, "Hello world", "2025-01-02T17:06:00.266902")],
            images=[(1, "pic.jpg", 0)],
        )
        entries, warnings = parse_backup(db, _images_dir(db))
        assert len(entries) == 1
        assert entries[0].text == "Hello world"
        assert entries[0].mood == 2
        assert entries[0].images[0].filename == "pic.jpg"
        assert warnings == []

    def test_missing_image_warns_not_raises(self, make_db):
        db = make_db(
            rows=[(None, "No photo entry", "2025-01-05T00:00:00.000Z")],
            images=[(1, "ghost.jpg", 0)],  # never written to disk
        )
        # remove the physical file to simulate a broken link
        (_images_dir(db) / "ghost.jpg").unlink()
        entries, warnings = parse_backup(db, _images_dir(db))
        assert len(entries) == 1
        assert entries[0].images == []
        assert any("ghost.jpg" in w for w in warnings)

    def test_null_mood_is_none(self, make_db):
        db = make_db(rows=[(None, "text", "2025-01-01T00:00:00")])
        entries, _ = parse_backup(db, _images_dir(db))
        assert entries[0].mood is None
        assert entries[0].mood_emoji is None

    def test_negative_mood_maps(self, make_db):
        db = make_db(rows=[(-2, "bad day", "2025-01-01T00:00:00")])
        entries, _ = parse_backup(db, _images_dir(db))
        assert entries[0].mood == -2
        assert entries[0].mood_emoji == "\U0001F62D"

    def test_no_image_table(self, tmp_path, make_db):
        db = make_db(rows=[(1, "x", "2025-01-01T00:00:00")])
        entries, warnings = parse_backup(db, _images_dir(db))
        assert entries[0].images == []

    def test_ordering_follows_entry_id(self, make_db):
        db = make_db(
            rows=[
                (1, "first", "2025-01-01T00:00:00"),
                (1, "second", "2025-01-02T00:00:00"),
                (1, "third", "2025-01-03T00:00:00"),
            ]
        )
        entries, _ = parse_backup(db, _images_dir(db))
        assert [e.text for e in entries] == ["first", "second", "third"]

    def test_read_only_mode(self, make_db):
        """Parser must open the DB read-only: writing must fail."""
        import sqlite3

        db = make_db(rows=[(1, "x", "2025-01-01T00:00:00")])
        parse_backup(db, _images_dir(db))
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO entries (text) VALUES ('hack')")
        conn.close()
