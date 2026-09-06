"""Tests for the UI tag-sync logic (no streamlit runtime needed)."""

from __future__ import annotations

from datetime import datetime, timezone

from src.app import sync_custom_tags
from src.config import Entry


def _entry(eid: int, text: str, tags: list[str] | None = None) -> Entry:
    return Entry(
        id=eid,
        text=text,
        mood=1,
        created_at=datetime(2025, 1, 2, 17, 6, tzinfo=timezone.utc),
        custom_tags=tags or [],
    )


class TestSyncCustomTags:
    def test_edited_tags_applied_by_id(self):
        entries = [_entry(1, "one"), _entry(2, "two")]
        edited = [
            {"id": 1, "custom_tags": "trip, beach"},
            {"id": 2, "custom_tags": ""},
        ]
        sync_custom_tags(entries, edited)
        assert entries[0].custom_tags == ["trip", "beach"]
        assert entries[1].custom_tags == []

    def test_noop_when_no_edits(self):
        entries = [_entry(1, "one", ["keep"])]
        edited = [{"id": 1, "custom_tags": "keep"}]
        sync_custom_tags(entries, edited)
        assert entries[0].custom_tags == ["keep"]

    def test_missing_id_in_edits_keeps_original(self):
        entries = [_entry(1, "one", ["orig"])]
        sync_custom_tags(entries, [])
        assert entries[0].custom_tags == ["orig"]

    def test_id_matching_survives_reordering(self):
        """st.data_editor rows may arrive in a different order than entries."""
        entries = [_entry(1, "one"), _entry(2, "two")]
        edited = [
            {"id": 2, "custom_tags": "second"},
            {"id": 1, "custom_tags": "first"},
        ]
        sync_custom_tags(entries, edited)
        assert entries[0].custom_tags == ["first"]
        assert entries[1].custom_tags == ["second"]

    def test_strip_and_dedupe_whitespace(self):
        entries = [_entry(1, "one")]
        edited = [{"id": 1, "custom_tags": "  a ,  , b  "}]
        sync_custom_tags(entries, edited)
        assert entries[0].custom_tags == ["a", "b"]
