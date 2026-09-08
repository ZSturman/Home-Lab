from __future__ import annotations

from typing import Any

import httpx
import pytest
import pytest_asyncio

from app.api import app, get_resources_notion_client, lifespan
from app.models import ResourceRecord


class FakeResourcesNotionClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.created: list[dict[str, Any]] = []
        self.fail = fail
        self._next_id = 900

    async def create_resource_page(self, *, resource_type: str, remote_url: str, label: str, project_notion_page_id: str) -> dict[str, Any]:
        if self.fail:
            raise RuntimeError("simulated Notion outage")
        self._next_id += 1
        page_id = f"fake-resource-page-{self._next_id}"
        self.created.append({"resource_type": resource_type, "remote_url": remote_url, "label": label, "project_notion_page_id": project_notion_page_id})
        return {"id": page_id}


@pytest_asyncio.fixture
async def fake_resources_notion():
    fake = FakeResourcesNotionClient()
    app.dependency_overrides[get_resources_notion_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_resources_notion_client, None)


@pytest_asyncio.fixture
async def client(fake_resources_notion):
    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            yield ac


def _request(**overrides: Any) -> dict[str, Any]:
    body = {
        "project_notion_page_id": "project-page-1", "resource_type": "repo",
        "remote_url": "https://github.com/example/repo.git", "label": "Example repo",
        "idempotency_key": "repo-resource:github.com/example/repo",
    }
    body.update(overrides)
    return body


@pytest.mark.asyncio
async def test_create_resource_creates_notion_page(client, session, fake_resources_notion) -> None:
    response = await client.post("/api/v1/resources", json=_request())
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "created"
    assert body["notion_page_id"] == "fake-resource-page-901"
    assert fake_resources_notion.created == [{"resource_type": "repo", "remote_url": "https://github.com/example/repo.git", "label": "Example repo", "project_notion_page_id": "project-page-1"}]


@pytest.mark.asyncio
async def test_retry_with_same_idempotency_key_never_creates_a_second_page(client, session, fake_resources_notion) -> None:
    first = await client.post("/api/v1/resources", json=_request())
    second = await client.post("/api/v1/resources", json=_request())
    assert first.json()["id"] == second.json()["id"]
    assert len(fake_resources_notion.created) == 1


@pytest.mark.asyncio
async def test_different_idempotency_key_same_remote_url_is_deduplicated(client, session, fake_resources_notion) -> None:
    first = await client.post("/api/v1/resources", json=_request(idempotency_key="key-a"))
    second = await client.post("/api/v1/resources", json=_request(idempotency_key="key-b", remote_url="https://github.com/Example/Repo"))  # different casing/host form
    assert first.json()["id"] == second.json()["id"]
    assert len(fake_resources_notion.created) == 1


@pytest.mark.asyncio
async def test_notion_failure_is_durable_and_retryable_in_place(client, session, fake_resources_notion) -> None:
    fake_resources_notion.fail = True
    first = await client.post("/api/v1/resources", json=_request())
    assert first.status_code == 202
    assert first.json()["status"] == "error"
    resource_id = first.json()["id"]

    fake_resources_notion.fail = False
    retried = await client.post("/api/v1/resources", json=_request())
    assert retried.json()["id"] == resource_id  # same row, not a new one
    assert retried.json()["status"] == "created"
    assert len(fake_resources_notion.created) == 1  # only the successful attempt actually wrote to Notion


@pytest.mark.asyncio
async def test_get_and_list_resources(client, session, fake_resources_notion) -> None:
    created = await client.post("/api/v1/resources", json=_request())
    resource_id = created.json()["id"]
    fetched = await client.get(f"/api/v1/resources/{resource_id}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == resource_id
    missing = await client.get("/api/v1/resources/does-not-exist")
    assert missing.status_code == 404
    listed = await client.get("/api/v1/resources")
    assert [item["id"] for item in listed.json()] == [resource_id]
