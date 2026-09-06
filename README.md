# dailyyou-to-memos

A small tool to migrate journal entries from a "Daily You" backup into a
self-hosted Memos instance. Built with Streamlit, so everything runs from
a simple web page in your browser.

It imports everything: the original text, the mood, the exact historical
date, and all linked images. You can add a global tag such as #journal,
mood based tags, or custom tags per entry before starting the import.

## How it works

Daily You exports a zip file containing an SQLite database (daily_you.db)
and an Images folder. This tool unpacks that zip into a temporary folder,
reads the database, and shows a preview of all entries in the browser.
When you start the import it sends each entry to your Memos instance via
its REST API, uploading the images first and then creating the memo with
its original date.

Mood values are mapped to an emoji and a tag, for example mood 2 becomes
a smiling emoji and #mood/happy. The final memo looks like this:

    Mood: <emoji>
    <original journal text>
    #journal #mood/happy #custom_tag

## Installation

You need Python 3.12 or newer.

    pip install -r requirements.txt

Put your Daily You backup zip in a folder called private/ in the project
root. The folder is ignored by git, so your personal data never ends up
in a repository.

## Usage

Start the app:

    streamlit run src/app.py

Then:

1. In the sidebar, enter your Memos instance URL and an access token
   (created in Memos under Settings, Access Tokens).
2. Pick the backup zip from the dropdown and click Parse backup.
3. Review the entries in the table. Add custom tags to individual entries
   in the last column if you want.
4. Click Run Import. Progress is shown per entry.

The import records every memo and attachment it creates in
private/.migration_ledger.json.

## Rollback

If something goes wrong, the Rollback section at the bottom of the page
removes exactly what the import created: the memos and attachments listed
in the ledger, and nothing else. It never searches or lists your Memos
content, so it cannot touch anything that was already on the instance
before the import. Type ROLLBACK to enable the delete button.

## Features

- Scans the private/ folder for backup zips, no upload widget needed
- Imports all text, moods, dates, and images
- Historical dates are preserved via the API createTime field
- Global tags, mood tags, and per-entry custom tags from the UI
- Rate limit friendly: request delay, retry with backoff on 429 and 5xx
- Full text inspection per entry before importing
- Safe rollback of only what this tool created

## Development

Run the tests:

    python -m pytest tests/

Run the GitHub Actions workflow locally with act:

    act -j test

## License

See [LICENSE](LICENSE)
