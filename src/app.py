"""Streamlit GUI for the Daily You -> Memos migration."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import Entry, MemosApiSettings, MigrationOptions  # noqa: E402
from src.extractor import extract_backup, find_backups  # noqa: E402
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
            "text": e.text[:80],
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
    # Sync edited custom tags back onto Entry objects.
    for row in edited.itertuples():
        entry = entries[row.Index]
        new_tags = [t.strip() for t in (row.custom_tags or "").split(",") if t.strip()]
        entry.custom_tags = new_tags
    return entries


def render_preview(entry: Entry, options: MigrationOptions) -> str:
    return entry.render_content(options)


def run_migration(
    entries: list[Entry],
    api: MemosApiSettings,
    options: MigrationOptions,
) -> None:
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
                client.create_memo(
                    content=entry.render_content(options),
                    create_time=entry.created_at.isoformat(),
                    attachments=attachments,
                )
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


def main() -> None:
    st.title("Daily You → Memos Migration")
    api, options = sidebar_settings()
    parse_panel()
    entries = tags_panel(options)

    if entries:
        st.subheader("Preview (first entry)")
        st.code(render_preview(entries[0], options))

        if st.button("Run Import", type="primary", disabled=not api.token):
            if not api.token:
                st.error("Token required")
                return
            run_migration(entries, api, options)


if __name__ == "__main__":
    main()
