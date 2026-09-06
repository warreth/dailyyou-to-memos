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


@contextmanager
def extract_backup(zip_path: Path) -> Iterator[ExtractedBackup]:
    """Yield an ExtractedBackup inside a self-cleaning TemporaryDirectory.

    Raises FileNotFoundError if the zip has no daily_you.db or Images/ dir.
    """
    with tempfile.TemporaryDirectory(prefix="dailyyou_") as tmp:
        root = Path(tmp)
        _safe_extract(zip_path, root)

        candidates = list(root.rglob("daily_you.db"))
        if not candidates:
            raise FileNotFoundError(
                f"No daily_you.db found inside {zip_path.name}"
            )
        db_path = candidates[0]

        images_dirs = [d for d in root.rglob("Images") if d.is_dir()]
        if not images_dirs:
            raise FileNotFoundError(
                f"No Images/ directory found inside {zip_path.name}"
            )
        images_dir = images_dirs[0]

        yield ExtractedBackup(db_path=db_path, images_dir=images_dir)
