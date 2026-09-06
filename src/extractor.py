"""Scan private/ for Daily You backups and extract them safely to a temp dir."""

from __future__ import annotations

import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, List

from .config import ExtractedBackup

BACKUP_GLOB = "*.zip"


def find_backups(private_dir: Path) -> List[Path]:
    """Return zip backups in private_dir, newest first. Empty list if dir missing."""
    if not private_dir.is_dir():
        return []
    zips = [p for p in private_dir.glob(BACKUP_GLOB) if p.is_file()]
    return sorted(zips, key=lambda p: p.stat().st_mtime, reverse=True)


def _safe_extract(zip_path: Path, target: Path) -> None:
    """Extract members while rejecting zip-slip paths outside target."""
    target_resolved = target.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            dest = (target / member).resolve()
            if not dest.is_relative_to(target_resolved):
                raise ValueError(
                    f"Blocked unsafe zip member path: {member!r}"
                )
        zf.extractall(target)


def _locate_backup(root: Path, zip_name: str) -> ExtractedBackup:
    """Find db and Images/ inside an already-extracted root dir."""
    candidates = list(root.rglob("daily_you.db"))
    if not candidates:
        raise FileNotFoundError(f"No daily_you.db found inside {zip_name}")
    images_dirs = [d for d in root.rglob("Images") if d.is_dir()]
    if not images_dirs:
        raise FileNotFoundError(f"No Images/ directory found inside {zip_name}")
    return ExtractedBackup(db_path=candidates[0], images_dir=images_dirs[0])


def extract_backup_kept(zip_path: Path) -> tuple[ExtractedBackup, tempfile.TemporaryDirectory]:
    """Extract into a temp dir that STAYS ALIVE until the caller cleans it up.

    Use this when parsed entries keep referencing image files after the
    function returns (e.g. stored in streamlit session_state). The caller
    owns the returned TemporaryDirectory and must call .cleanup() when done;
    it is also released automatically when garbage collected.
    """
    tmp = tempfile.TemporaryDirectory(prefix="dailyyou_")
    root = Path(tmp.name)
    _safe_extract(zip_path, root)
    return _locate_backup(root, zip_path.name), tmp


@contextmanager
def extract_backup(zip_path: Path) -> Iterator[ExtractedBackup]:
    """Yield an ExtractedBackup inside a self-cleaning TemporaryDirectory.

    Only for short-lived use: everything is deleted when the block exits.
    """
    with tempfile.TemporaryDirectory(prefix="dailyyou_") as tmp:
        root = Path(tmp)
        _safe_extract(zip_path, root)
        yield _locate_backup(root, zip_path.name)
