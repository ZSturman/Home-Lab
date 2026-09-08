"""Minimal async Notion client for the Projects data source.

Mirrors the pacing/retry conventions already established elsewhere in this
workspace (Better Projects' NotionRateLimiter, Project Automatic Task
Manager's NotionClient): ~0.35s between requests, bounded retries on
429/5xx, never a hard delete (archive only).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

NOTION_VERSION = "2026-03-11"
MAX_TEXT_CHUNK = 1900
MIN_REQUEST_INTERVAL_SECONDS = 0.35

# The live Projects database's title property, and the property that already
# holds a project's local filesystem path (confirmed against the live schema;
# see docs/notion-projects-integration.md). Kept as a short alias list so a
# manual rename in Notion degrades gracefully instead of breaking silently.
TITLE_PROPERTY_CANDIDATES = ("title", "Name", "Title")
LOCAL_DIRECTORY_PROPERTY_CANDIDATES = ("Local Directory", "Local Path", "Project Path", "Workspace Path")


class NotionError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class NotionClient:
    def __init__(self, token: str, *, database_id: str, timeout_seconds: float = 30.0) -> None:
        self._token = token
        self.database_id = database_id
        self._timeout = timeout_seconds
        self._next_request_at = 0.0
        self._lock = asyncio.Lock()
        self._data_source_id: str | None = None

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Notion-Version": NOTION_VERSION,
        }

    async def _request(self, method: str, path: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
        last_error: NotionError | None = None
        for attempt in range(4):
            async with self._lock:
                delay = self._next_request_at - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                self._next_request_at = time.monotonic() + MIN_REQUEST_INTERVAL_SECONDS
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.request(
                        method, f"https://api.notion.com/v1{path}", headers=self._headers(), json=json,
                    )
                if response.status_code >= 400:
                    detail = response.text[:500]
                    retryable = response.status_code in {429, 500, 502, 503, 504}
                    last_error = NotionError(f"Notion HTTP {response.status_code}: {detail}", retryable=retryable)
                    if not retryable:
                        raise last_error
                else:
                    return response.json()
            except httpx.HTTPError as exc:
                last_error = NotionError(f"Notion request failed: {exc}", retryable=True)
            await asyncio.sleep(min(4.0, 0.5 * (2**attempt)))
        raise last_error or NotionError("Notion request failed.")

    async def data_source_id(self) -> str:
        if self._data_source_id:
            return self._data_source_id
        try:
            await self._request("GET", f"/data_sources/{self.database_id}")
            self._data_source_id = self.database_id
            return self._data_source_id
        except NotionError:
            pass
        database = await self._request("GET", f"/databases/{self.database_id}")
        sources = database.get("data_sources") or []
        source_id = str((sources[0] if sources else {}).get("id") or "")
        if not source_id:
            raise NotionError("The Notion Projects database has no accessible data source.")
        self._data_source_id = source_id
        return source_id

    async def query_all_projects(self) -> list[dict[str, Any]]:
        source_id = await self.data_source_id()
        rows: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            payload: dict[str, Any] = {"page_size": 100}
            if cursor:
                payload["start_cursor"] = cursor
            response = await self._request("POST", f"/data_sources/{source_id}/query", json=payload)
            rows.extend(item for item in response.get("results", []) if isinstance(item, dict))
            cursor = str(response.get("next_cursor") or "") or None
            if not response.get("has_more") or not cursor:
                break
        return rows

    async def create_project_page(self, *, name: str, local_directory: str | None) -> dict[str, Any]:
        source_id = await self.data_source_id()
        properties: dict[str, Any] = {"title": {"title": _rich_text(name)}}
        if local_directory:
            properties["Local Directory"] = {"rich_text": _rich_text(local_directory)}
        return await self._request(
            "POST",
            "/pages",
            json={"parent": {"type": "data_source_id", "data_source_id": source_id}, "properties": properties},
        )

    async def update_project_local_directory(self, page_id: str, local_directory: str) -> dict[str, Any]:
        return await self._request(
            "PATCH", f"/pages/{page_id}", json={"properties": {"Local Directory": {"rich_text": _rich_text(local_directory)}}},
        )

    async def get_page(self, page_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/pages/{page_id}")


def _rich_text(value: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": {"content": value[i : i + MAX_TEXT_CHUNK]}} for i in range(0, len(value), MAX_TEXT_CHUNK)] or []


def _plain_text(parts: Any) -> str:
    if not isinstance(parts, list):
        return ""
    return "".join(str(item.get("plain_text") or item.get("text", {}).get("content") or "") for item in parts if isinstance(item, dict))


def page_title(page: dict[str, Any]) -> str:
    properties = page.get("properties") or {}
    for name in TITLE_PROPERTY_CANDIDATES:
        prop = properties.get(name)
        if isinstance(prop, dict) and prop.get("type") == "title":
            return _plain_text(prop.get("title"))
    return ""


def page_local_directory(page: dict[str, Any]) -> str | None:
    properties = page.get("properties") or {}
    for name in LOCAL_DIRECTORY_PROPERTY_CANDIDATES:
        prop = properties.get(name)
        if isinstance(prop, dict) and prop.get("type") == "rich_text":
            text = _plain_text(prop.get("rich_text"))
            if text:
                return text
    return None
