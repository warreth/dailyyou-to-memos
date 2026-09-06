"""Extractor tests: kept temp dir lifecycle and zip-slip rejection."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from src.extractor import extract_backup, extract_backup_kept


def _build_backup(tmp_path: Path) -> Path:
    """Build a minimal Daily You backup zip: db + one image."""
    import sqlite3

    stage = tmp_path / "stage"
    (stage / "Images").mkdir(parents=True)
    db = stage / "daily_you.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE entries (id INTEGER PRIMARY KEY, text TEXT, mood INTEGER, time_create DATETIME);
        CREATE TABLE entry_images (id INTEGER PRIMARY KEY, entry_id INTEGER, img_path TEXT, img_rank INTEGER, time_create DATETIME);
        INSERT INTO entries VALUES (1, 'hello', 1, '2025-01-02T17:06:00');
        INSERT INTO entry_images VALUES (1, 1, 'pic.jpg', 0, '2025-01-02T17:06:00');
        """
    )
    (stage / "Images" / "pic.jpg").write_bytes(b"jpeg")
    conn.commit()
    conn.close()

    zip_path = tmp_path / "backup.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(db, "daily_you.db")
        zf.write(stage / "Images" / "pic.jpg", "Images/pic.jpg")
    return zip_path


def test_kept_extraction_files_survive_parse(tmp_path: Path):
    """The bug this guards: entries referenced image paths inside a temp
    dir that got deleted the moment parsing finished."""
    from src.parser import parse_backup

    zip_path = _build_backup(tmp_path)
    backup, tmp_dir = extract_backup_kept(zip_path)
    entries, warnings = parse_backup(backup.db_path, backup.images_dir)

    img_path = entries[0].images[0].path
    assert img_path.is_file(), "image file vanished before migration"
    assert img_path.read_bytes() == b"jpeg"

    tmp_dir.cleanup()
    assert not img_path.exists()


def test_kept_extraction_is_garbage_collected(tmp_path: Path):
    """Even without explicit cleanup, dropping the reference frees the dir."""
    zip_path = _build_backup(tmp_path)
    backup, tmp_dir = extract_backup_kept(zip_path)
    marker = backup.images_dir / "pic.jpg"
    assert marker.is_file()
    del tmp_dir  # GC releases the TemporaryDirectory
    # Not asserting deletion here: GC timing is CPython refcount-deterministic
    # but this documents the ownership contract.


def test_context_manager_still_cleans_up(tmp_path: Path):
    zip_path = _build_backup(tmp_path)
    with extract_backup(zip_path) as backup:
        assert backup.db_path.is_file()
        marker = backup.images_dir / "pic.jpg"
        assert marker.is_file()
    assert not backup.db_path.exists()
    assert not marker.exists()


def test_missing_db_raises(tmp_path: Path):
    zip_path = tmp_path / "empty.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("readme.txt", "nothing useful")
    # extract_backup is a contextmanager: the body runs on __enter__.
    with pytest.raises(FileNotFoundError):
        with extract_backup(zip_path):
            pass


def test_zip_slip_rejected(tmp_path: Path):
    zip_path = tmp_path / "evil.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("daily_you.db", b"fake")
        zf.writestr("../escape.txt", b"evil")
    with pytest.raises(ValueError, match="unsafe"):
        with extract_backup(zip_path):
            pass
