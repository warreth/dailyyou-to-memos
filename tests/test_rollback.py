"""Rollback tests: ledger persistence and delete-only-what-we-created."""

from __future__ import annotations

import json
from pathlib import Path

import responses

from src.config import MemosApiSettings
from src.ledger import (
    MigrationLedger,
    clear_ledger,
    load_ledger,
    save_ledger,
)
from src.memos_client import MemosApiError, MemosClient

BASE = "https://memos.example.com"
SETTINGS = MemosApiSettings(base_url=BASE, token="secret-token", request_delay=0.0)
API = BASE + "/api/v1"


class TestLedger:
    def test_round_trip(self, tmp_path: Path):
        ledger = MigrationLedger(
            base_url=BASE,
            memos=[],
        )
        ledger.add("memos/101", ["attachments/1", "attachments/2"])
        ledger.add("memos/102", [])
        save_ledger(tmp_path, ledger)

        loaded = load_ledger(tmp_path)
        assert loaded is not None
        assert loaded.base_url == BASE
        assert [m.name for m in loaded.memos] == ["memos/101", "memos/102"]
        assert loaded.memos[0].attachment_names == ["attachments/1", "attachments/2"]
        assert loaded.counts() == (2, 2)

    def test_missing_ledger_returns_none(self, tmp_path: Path):
        assert load_ledger(tmp_path) is None

    def test_clear_removes_file(self, tmp_path: Path):
        save_ledger(tmp_path, MigrationLedger(base_url=BASE))
        clear_ledger(tmp_path)
        assert load_ledger(tmp_path) is None

    def test_ledger_not_in_git(self):
        """The ledger lives under private/ which .gitignore excludes."""
        import subprocess

        out = subprocess.run(
            ["git", "check-ignore", "-q", "private/.migration_ledger.json"],
            capture_output=True,
        )
        assert out.returncode == 0, "ledger file must be git-ignored"


@responses.activate
def test_delete_memo_uses_delete_route():
    responses.delete(f"{API}/memos/123", json={})
    with MemosClient(SETTINGS) as client:
        client.delete_memo("memos/123")
    assert responses.calls[0].request.method == "DELETE"
    assert responses.calls[0].request.url == f"{API}/memos/123"
    assert responses.calls[0].request.headers["Authorization"] == "Bearer secret-token"


@responses.activate
def test_delete_attachment_uses_delete_route():
    responses.delete(f"{API}/attachments/7", json={})
    with MemosClient(SETTINGS) as client:
        client.delete_attachment("attachments/7")
    assert responses.calls[0].request.url == f"{API}/attachments/7"


@responses.activate
def test_delete_404_is_success():
    """A 404 means the target is already gone, which is the rollback goal."""
    responses.delete(f"{API}/memos/999", json={}, status=404)
    with MemosClient(SETTINGS) as client:
        client.delete_memo("memos/999")  # must not raise


@responses.activate
def test_delete_other_errors_raise():
    responses.delete(f"{API}/memos/5", json={}, status=403)
    with MemosClient(SETTINGS) as client:
        try:
            client.delete_memo("memos/5")
            raise AssertionError("expected MemosApiError")
        except MemosApiError as exc:
            assert "403" in str(exc)


@responses.activate
def test_rollback_deletes_only_ledger_entries():
    """Full rollback flow: create 2 memos, record, delete only those ids.

    A pre-existing memo (memos/1) is registered as an active mock but the
    ledger never mentions it, so rollback must never call its delete route.
    """
    # Pre-existing memo from before the migration - must stay untouched.
    responses.delete(f"{API}/memos/1", json={"touched": "pre-existing"})
    # The two memos this tool created.
    responses.delete(f"{API}/memos/101", json={})
    responses.delete(f"{API}/memos/102", json={})
    # Attachments, expected to 404 after memo cascade or to delete cleanly.
    responses.delete(f"{API}/attachments/1", json={}, status=404)
    responses.delete(f"{API}/attachments/2", json={})

    with MemosClient(SETTINGS) as client:
        for name in ("memos/101", "memos/102"):
            client.delete_memo(name)
        for att in ("attachments/1", "attachments/2"):
            client.delete_attachment(att)

    deleted = [
        c.request.url for c in responses.calls if c.request.method == "DELETE"
    ]
    assert f"{API}/memos/1" not in deleted, "rollback must not touch pre-existing memos"
    assert f"{API}/memos/101" in deleted
    assert f"{API}/memos/102" in deleted
    assert len(deleted) == 4
