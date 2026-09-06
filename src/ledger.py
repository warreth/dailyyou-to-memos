"""Crash-safe record of everything this tool created on a Memos instance.

The rollback feature deletes ONLY what the ledger lists. Nothing discovered
by search or listing is ever deleted, so a rollback cannot touch anything
this tool did not create.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, List

LEDGER_FILENAME = ".migration_ledger.json"


@dataclass
class CreatedMemo:
    name: str  # e.g. "memos/123"
    attachment_names: List[str] = field(default_factory=list)


@dataclass
class MigrationLedger:
    base_url: str
    memos: List[CreatedMemo] = field(default_factory=list)

    def add(self, name: str, attachment_names: List[str]) -> None:
        self.memos.append(CreatedMemo(name, attachment_names))

    def is_empty(self) -> bool:
        return not self.memos

    def counts(self) -> tuple[int, int]:
        return len(self.memos), sum(len(m.attachment_names) for m in self.memos)


def ledger_path(private_dir: Path) -> Path:
    return private_dir / LEDGER_FILENAME


def load_ledger(private_dir: Path) -> MigrationLedger | None:
    """Return None when no ledger exists (nothing was ever migrated here)."""
    path = ledger_path(private_dir)
    if not path.is_file():
        return None
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return MigrationLedger(
        base_url=data["base_url"],
        memos=[CreatedMemo(**m) for m in data.get("memos", [])],
    )


def save_ledger(private_dir: Path, ledger: MigrationLedger) -> None:
    """Overwrite atomically: tmp file then replace, so a crash cannot truncate."""
    private_dir.mkdir(exist_ok=True)
    path = ledger_path(private_dir)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(ledger), indent=2), encoding="utf-8")
    tmp.replace(path)


def clear_ledger(private_dir: Path) -> None:
    path = ledger_path(private_dir)
    path.unlink(missing_ok=True)
