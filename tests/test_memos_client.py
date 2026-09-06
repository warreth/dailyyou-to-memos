"""MemosClient tests with the responses library mocking the API."""
# ponytail: emoji via \U escapes keeps source ASCII-safe.

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import responses

from src.config import Entry, JournalImage, MemosApiSettings, MigrationOptions
from src.memos_client import MemosApiError, MemosClient

SETTINGS = MemosApiSettings(
    base_url="https://memos.example.com", token="secret-token", request_delay=0.0
)
BASE = "https://memos.example.com/api/v1"
JPEG = b"\xff\xd8jpegdata"


@responses.activate
def test_upload_attachment_sends_base64(tmp_path: Path):
    img = tmp_path / "photo.jpg"
    img.write_bytes(JPEG)
    responses.post(f"{BASE}/attachments", json={"name": "attachments/123"})

    with MemosClient(SETTINGS) as client:
        att = client.upload_attachment(img)

    assert att == {"name": "attachments/123"}
    req = responses.calls[0].request
    assert req.headers["Authorization"] == "Bearer secret-token"
    body = json.loads(req.body)
    assert body["filename"] == "photo.jpg"
    assert body["type"] == "image/jpeg"
    assert base64.b64decode(body["content"]) == JPEG


@responses.activate
def test_create_memo_payload_includes_history_and_attachments():
    responses.post(f"{BASE}/memos", json={"id": 1})

    with MemosClient(SETTINGS) as client:
        client.create_memo(
            content="Mood: \U0001F60A\nhello\n#journal",
            create_time="2025-01-02T17:06:00.266902+00:00",
            attachments=[{"name": "attachments/123"}],
        )

    body = json.loads(responses.calls[0].request.body)
    assert body["content"] == "Mood: \U0001F60A\nhello\n#journal"
    assert body["visibility"] == "PRIVATE"
    assert body["createTime"] == "2025-01-02T17:06:00.266902+00:00"
    assert body["attachments"] == [{"name": "attachments/123"}]


@responses.activate
def test_retry_on_429_then_success():
    responses.post(f"{BASE}/memos", json={"error": "rate limited"}, status=429)
    responses.post(f"{BASE}/memos", json={"id": 7})

    with MemosClient(SETTINGS) as client:
        result = client.create_memo(content="x", create_time="2025-01-01T00:00:00+00:00")

    assert result == {"id": 7}
    assert len(responses.calls) == 2


@responses.activate
def test_non_retryable_error_raises():
    responses.post(f"{BASE}/memos", json={"error": "bad token"}, status=401)

    with MemosClient(SETTINGS) as client:
        with pytest.raises(MemosApiError, match="401"):
            client.create_memo(content="x", create_time="2025-01-01T00:00:00+00:00")


@responses.activate
def test_exhausted_retries_raise():
    for _ in range(3):
        responses.post(f"{BASE}/memos", json={}, status=503)

    settings = MemosApiSettings(base_url="https://memos.example.com", token="t", request_delay=0.0, max_retries=3)
    with MemosClient(settings) as client:
        with pytest.raises(MemosApiError):
            client.create_memo(content="x", create_time="2025-01-01T00:00:00+00:00")


@responses.activate
def test_base_url_trailing_slash_normalized():
    settings = MemosApiSettings(base_url="https://memos.example.com/", token="t", request_delay=0.0)
    responses.post(f"{BASE}/memos", json={"id": 1})
    with MemosClient(settings) as client:
        client.create_memo(content="x", create_time="2025-01-01T00:00:00+00:00")
    assert responses.calls[0].request.url == f"{BASE}/memos"


def test_render_content_format():
    e = Entry(
        id=1,
        text="My day",
        mood=2,
        created_at=datetime(2025, 1, 2, 17, 6, tzinfo=timezone.utc),
        images=[JournalImage(path=Path("/tmp/a.jpg"))],
        custom_tags=["trip"],
    )
    opts = MigrationOptions(global_tags=("#journal",), add_mood_tags=True)
    out = e.render_content(opts)
    expected = "Mood: \U0001F60A\nMy day\n#journal #mood/happy #trip\n"
    assert out == expected
