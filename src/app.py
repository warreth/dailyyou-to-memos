"""Streamlit GUI for the Daily You -> Memos migration."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import Entry, MemosApiSettings, MigrationOptions  # noqa: E402
from src.extractor import extract_backup, find_backups  # noqa: E402
from src.ledger import (  # noqa: E402
    MigrationLedger,
    clear_ledger,
    load_ledger,
    save_ledger,
)
from src.memos_client import MemosApiError, MemosClient  # noqa: E402
from src.parser import parse_backup  # noqa: E402

PRIVATE_DIR = Path(__file__).resolve().parent.parent / "private"
STATE_ENTRIES = "entries"
STATE_WARNINGS = "parse_warnings"
STATE_TAGS_KEY = "tags_editor"
STATE_BACKUP_NAME = "backup_name"


st.set_page_config(page_title="Daily You -> Memos", page_icon="\U0001F4D6", layout="wide")


def sidebar_settings() -> tuple[MemosApiSettings, MigrationOptions]:
    with st.sidebar:
        st.header("Memos API")
        base_url = st.text_input("Instance URL", value="https://memos.example.com")
        token = st.text_input("Access Token", type="password")
        delay = st.number_input("Delay between requests (s)", 0.1, 10.0, 0.5, 0.1)

        st.header("Tags")
        global_tags_raw = st.text_input(
            "Global tag(s), comma-separated",
            value="#journal",
            help="Applied to every migrated entry",
        )
        global_tags = tuple(
            t.strip() for t in global_tags_raw.split(",") if t.strip()
        )
        mood_tags = st.checkbox("Add mood-based tags", value=True)
        return (
            MemosApiSettings(base_url=base_url, token=token, request_delay=float(delay)),
            MigrationOptions(global_tags=global_tags, add_mood_tags=mood_tags),
        )


def parse_panel() -> None:
    backups = find_backups(PRIVATE_DIR)
    if not backups:
        st.warning(
            "No .zip backups found in the private/ directory. "
            "Place your Daily You export there and refresh."
        )
        return
    names = [b.name for b in backups]
    default = names[0] if st.session_state.get(STATE_BACKUP_NAME) not in names else st.session_state[STATE_BACKUP_NAME]
    selected = st.selectbox("Backup file", names, index=names.index(default))
    st.session_state[STATE_BACKUP_NAME] = selected
    zip_path = backups[names.index(selected)]

    if st.button("Parse backup", type="primary"):
        with st.spinner(f"Extracting {selected}..."):
            try:
                with extract_backup(zip_path) as backup:
                    entries, warnings = parse_backup(backup.db_path, backup.images_dir)
            except (FileNotFoundError, ValueError) as exc:
                st.error(f"Extraction/parse failed: {exc}")
                return
        st.session_state[STATE_ENTRIES] = entries
        st.session_state[STATE_WARNINGS] = warnings
        st.session_state.pop(STATE_TAGS_KEY, None)
        if warnings:
            with st.expander(f"{len(warnings)} parse warnings", expanded=False):
                for w in warnings[:50]:
                    st.write(w)


def tags_panel(options: MigrationOptions) -> list[Entry]:
    entries: list[Entry] = st.session_state.get(STATE_ENTRIES) or []
    if not entries:
        return []
    rows = [
        {
            "id": e.id,
            "date": e.created_at.strftime("%Y-%m-%d %H:%M"),
            "mood": e.mood_emoji or "",
            "images": len(e.images),
            "text": e.text[:200],
            "custom_tags": ", ".join(e.custom_tags),
        }
        for e in entries
    ]
    st.subheader(f"Entries ({len(entries)})")
    edited = st.data_editor(
        rows,
        num_rows="fixed",
        use_container_width=True,
        key=STATE_TAGS_KEY,
        column_config={
            "text": st.column_config.TextColumn("Text preview", width="medium"),
            "custom_tags": st.column_config.TextColumn(
                "Custom tags (comma-separated)", width="medium"
            ),
        },
        height=420,
    )
    # st.data_editor returns the same shape it received: a list of dicts.
    sync_custom_tags(entries, edited)
    return entries


def sync_custom_tags(entries: list[Entry], edited_rows: list[dict]) -> None:
    """Apply data_editor edits back onto Entry objects, matched by entry id.

    Id-matching (not list position) keeps edits correct even if the user
    reorders or sorts the table in the editor.
    """
    edited_by_id = {
        int(row["id"]): (row.get("custom_tags") or "") for row in edited_rows
    }
    for entry in entries:
        if entry.id not in edited_by_id:
            continue  # row absent from editor output: nothing was edited
        raw = edited_by_id[entry.id]
        entry.custom_tags = [t.strip() for t in raw.split(",") if t.strip()]


def full_text_panel(entries: list[Entry]) -> None:
    """Inspect the complete parsed text of any entry.

    The table column is a 200-char preview by design; this panel proves
    the full text is parsed and what will actually be migrated.
    """
    with st.expander("Inspect full entry text", expanded=False):
        labels = [
            f"#{e.id} {e.created_at.strftime('%Y-%m-%d')} ({len(e.text)} chars, {len(e.images)} imgs)"
            for e in entries
        ]
        chosen = st.selectbox("Entry", labels)
        entry = entries[labels.index(chosen)]
        st.markdown(entry.text)
        st.caption(f"Full length: {len(entry.text)} characters")


def render_preview(entry: Entry, options: MigrationOptions) -> str:
    return entry.render_content(options)


def run_migration(
    entries: list[Entry],
    api: MemosApiSettings,
    options: MigrationOptions,
) -> None:
    # Fresh ledger per run: rollback targets exactly this run's creations.
    ledger = MigrationLedger(base_url=api.base_url.rstrip("/"))
    with MemosClient(api) as client:
        progress = st.progress(0.0, text="Starting migration...")
        status = st.empty()
        ok, failed = 0, []
        for i, entry in enumerate(entries):
            label = f"[{i + 1}/{len(entries)}] entry {entry.id}"
            try:
                attachments = []
                for img in entry.images:
                    att = client.upload_attachment(img.path)
                    attachments.append(att)
                memo = client.create_memo(
                    content=entry.render_content(options),
                    create_time=entry.created_at.isoformat(),
                    attachments=attachments,
                )
                # Record immediately so a crash mid-run still leaves a
                # complete rollback record of everything already created.
                ledger.add(
                    name=memo["name"],
                    attachment_names=[a["name"] for a in attachments],
                )
                save_ledger(PRIVATE_DIR, ledger)
                ok += 1
                status.write(f"{label} migrated")
            except MemosApiError as exc:
                failed.append((entry.id, str(exc)))
                status.write(f"{label} FAILED: {exc}")
            progress.progress((i + 1) / len(entries))
        if failed:
            st.error(f"Migration finished with {len(failed)} failures")
            with st.expander("Failed entries"):
                for eid, msg in failed:
                    st.write(f"Entry {eid}: {msg}")
        else:
            st.success(f"Migration complete: {ok}/{len(entries)} entries")


def rollback_panel(api: MemosApiSettings) -> None:
    """Delete exactly what the ledger records. Nothing else, ever.

    Safety rails:
    - No search or listing is used; only ledger identifiers are deleted.
    - The configured instance must match the instance the ledger recorded.
    - A typed confirmation phrase is required before the button activates.
    - 404s during deletion count as success (already deleted).
    """
    st.subheader("Rollback")
    ledger = load_ledger(PRIVATE_DIR)

    if ledger is None:
        st.info("No migration ledger found. Nothing to roll back.")
        return
    if ledger.is_empty():
        st.info("Ledger is empty. Nothing to roll back.")
        return

    memo_count, att_count = ledger.counts()
    if ledger.base_url.rstrip("/") != api.base_url.rstrip("/"):
        st.error(
            f"This ledger was recorded against a different instance "
            f"({ledger.base_url}). Rollback refused to protect that instance."
        )
        return

    st.warning(
        f"The ledger records {memo_count} memo(s) and {att_count} "
        f"attachment(s) created by the last migration run on "
        f"{ledger.base_url}. Deleting these removes them permanently."
    )
    with st.expander("Ledger contents", expanded=False):
        st.json(
            [
                {"memo": m.name, "attachments": m.attachment_names}
                for m in ledger.memos
            ]
        )

    confirm = st.text_input(
        "Type ROLLBACK to enable the delete button",
        key="rollback_confirm",
    )
    if st.button(
        "Delete migrated journals from Memos",
        type="primary",
        disabled=(confirm != "ROLLBACK" or not api.token),
    ):
        with MemosClient(api) as client:
            progress = st.progress(0.0, text="Rolling back...")
            status = st.empty()
            failures = []
            total = memo_count + att_count
            done = 0

            def bump(msg: str) -> None:
                nonlocal done
                done += 1
                progress.progress(done / total)
                status.write(msg)

            # Delete memos first: the server cascades their owned
            # attachments, so the explicit attachment deletes below
            # usually hit 404, which is the desired end state.
            for memo in ledger.memos:
                try:
                    client.delete_memo(memo.name)
                    bump(f"Deleted {memo.name}")
                except MemosApiError as exc:
                    failures.append((memo.name, str(exc)))
                # Defensive sweep: if the server did not cascade, remove
                # the attachment records explicitly (404 = already gone).
                for att in memo.attachment_names:
                    try:
                        client.delete_attachment(att)
                        bump(f"Deleted {att}")
                    except MemosApiError as exc:
                        failures.append((att, str(exc)))

            if failures:
                st.error(f"Rollback finished with {len(failures)} failures")
                with st.expander("Failures"):
                    for name, msg in failures:
                        st.write(f"{name}: {msg}")
            else:
                st.success(
                    f"Rollback complete: {memo_count} memo(s) and "
                    f"{att_count} attachment record(s) removed"
                )
                clear_ledger(PRIVATE_DIR)


def main() -> None:
    st.title("Daily You → Memos Migration")
    api, options = sidebar_settings()
    parse_panel()
    entries = tags_panel(options)

    st.divider()

    if entries:
        full_text_panel(entries)
        st.subheader("Preview (first entry)")
        st.code(render_preview(entries[0], options))

        if st.button("Run Import", type="primary", disabled=not api.token):
            if not api.token:
                st.error("Token required")
                return
            run_migration(entries, api, options)

    rollback_panel(api)


if __name__ == "__main__":
    main()
