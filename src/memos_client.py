"""HTTP client for the Memos API v1 with retry and rate-limit protection."""

from __future__ import annotations

import base64
import mimetypes
import time
from pathlib import Path
from typing import Any, Optional

import requests

from .config import MemosApiSettings

RETRY_STATUS = {429, 500, 502, 503, 504}


class MemosApiError(RuntimeError):
    """Raised when the Memos API returns a non-retryable failure."""


class MemosClient:
    def __init__(self, settings: MemosApiSettings) -> None:
        self.settings = settings
        self._session = requests.Session()
        self._session.headers.update(
            {"Authorization": f"Bearer {settings.token}"}
        )

    def _request(
        self, method: str, url: str, **kwargs: Any
    ) -> requests.Response:
        last_error: Optional[requests.RequestException] = None
        for attempt in range(self.settings.max_retries):
            try:
                resp = self._session.request(method, url, timeout=self.settings.timeout, **kwargs)
                if resp.status_code in RETRY_STATUS and attempt < self.settings.max_retries - 1:
                    time.sleep(self.settings.request_delay * (2 ** attempt))
                    continue
                return resp
            except requests.RequestException as exc:
                last_error = exc
                if attempt < self.settings.max_retries - 1:
                    time.sleep(self.settings.request_delay * (2 ** attempt))
        raise MemosApiError(f"Request to {url} failed after retries: {last_error}")

    def _post_json(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = self.settings.api_v1 + endpoint
        resp = self._request("POST", url, json=payload)
        if not resp.ok:
            raise MemosApiError(
                f"POST {url} -> {resp.status_code}: {resp.text[:300]}"
            )
        return resp.json()

    def upload_attachment(self, image_path: Path) -> dict[str, Any]:
        """POST /attachments with base64 content. Returns attachment object for create_memo."""
        data = image_path.read_bytes()
        mime = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
        payload = {
            "filename": image_path.name,
            "type": mime,
            "content": base64.b64encode(data).decode("ascii"),
        }
        return self._post_json("/attachments", payload)

    def create_memo(
        self,
        content: str,
        create_time: str,
        attachments: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """POST /memos with historical createTime and attachment objects."""
        payload: dict[str, Any] = {
            "content": content,
            "visibility": self.settings.visibility,
            "createTime": create_time,
        }
        if attachments:
            payload["attachments"] = attachments
        return self._post_json("/memos", payload)

    def delete_memo(self, name: str) -> None:
        """DELETE /api/v1/memos/{id}. 404 counts as done (already deleted)."""
        self._delete(name)

    def delete_attachment(self, name: str) -> None:
        """DELETE /api/v1/attachments/{id}. 404 counts as done."""
        self._delete(name)

    def _delete(self, resource_name: str) -> None:
        # resource_name is "memos/123" or "attachments/456"; the route is
        # DELETE /api/v1/{name=...} so it maps directly onto the path suffix.
        url = f"{self.settings.api_v1}/{resource_name}"
        resp = self._request("DELETE", url)
        if resp.status_code == 404:
            return  # already gone: the rollback goal is met
        if not resp.ok:
            raise MemosApiError(f"DELETE {url} -> {resp.status_code}: {resp.text[:300]}")

    def close(self) -> None:
        self._session.close()

    # Rate-limit protection: sleep after each public call.
    def __enter__(self) -> "MemosClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        time.sleep(self.settings.request_delay)
        self.close()
