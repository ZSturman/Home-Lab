from __future__ import annotations

from typing import Any

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.api import app, get_notion_client, lifespan
from app.models import CommandRecord, NodeRecord, ProjectRecord, ReconciliationItemRecord


class FakeNotionClient:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.updated: list[tuple[str, str]] = []
        self._next_id = 100

    async def query_all_projects(self) -> list[dict[str, Any]]:
        return []

    async def create_project_page(self, *, name: str, local_directory: str | None) -> dict[str, Any]:
        self._next_id += 1
        page_id = f"fake-page-{self._next_id}"
        self.created.append({"name": name, "local_directory": local_directory})
        return {"id": page_id}

    async def update_project_local_directory(self, page_id: str, local_directory: str) -> dict[str, Any]:
        self.updated.append((page_id, local_directory))
        return {"id": page_id}


@pytest_asyncio.fixture
async def fake_notion():
    fake = FakeNotionClient()
    app.dependency_overrides[get_notion_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_notion_client, None)


@pytest_asyncio.fixture
async def client(fake_notion):
    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            yield ac


@pytest.mark.asyncio
async def test_create_project_creates_notion_page_and_directory_job(client, session, fake_notion) -> None:
    response = await client.post("/api/v1/projects", json={
        "name": "Drawing AI", "description": "", "template": "empty",
        "idempotency_key": "phone-key-1", "source": "ios-app",
    })
    assert response.status_code == 202
    body = response.json()
    assert body["name"] == "Drawing AI"
    assert body["notion_page_id"] == "fake-page-101"
    assert body["sync_state"] == "PENDING_WORKSPACE_CREATION"
    assert len(fake_notion.created) == 1

    jobs = list((await session.execute(
        select(CommandRecord).where(CommandRecord.command_type == "project.create_directory")
    )).scalars())
    assert len(jobs) == 1
    assert jobs[0].payload["name"] == "Drawing AI"
    assert jobs[0].node_id == "macbook"


@pytest.mark.asyncio
async def test_duplicate_create_project_request_is_idempotent(client, session, fake_notion) -> None:
    payload = {
        "name": "Duplicate Test", "description": "", "template": "empty",
        "idempotency_key": "same-key-retry", "source": "ios-app",
    }
    first = await client.post("/api/v1/projects", json=payload)
    second = await client.post("/api/v1/projects", json=payload)

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    assert len(fake_notion.created) == 1  # only one Notion page created

    projects = list((await session.execute(select(ProjectRecord))).scalars())
    jobs = list((await session.execute(select(CommandRecord))).scalars())
    assert len(projects) == 1
    assert len(jobs) == 1


@pytest.mark.asyncio
async def test_create_project_rejects_unsafe_name(client, fake_notion) -> None:
    response = await client.post("/api/v1/projects", json={
        "name": "../escape", "description": "", "template": "empty",
        "idempotency_key": "unsafe-1", "source": "ios-app",
    })
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_pending_jobs_endpoint_is_the_macs_poll_target(client, session, fake_notion) -> None:
    await client.post("/api/v1/projects", json={
        "name": "Poll Target", "description": "", "template": "empty",
        "idempotency_key": "poll-key", "source": "ios-app",
    })

    response = await client.get("/api/v1/projects/jobs/pending", params={"node_id": "macbook"})
    assert response.status_code == 200
    jobs = response.json()
    assert len(jobs) == 1
    assert jobs[0]["command_type"] == "project.create_directory"

    other_node = await client.get("/api/v1/projects/jobs/pending", params={"node_id": "some-other-node"})
    assert other_node.json() == []


@pytest.mark.asyncio
async def test_reconciliation_ignore_resolves_item(client, session, fake_notion) -> None:
    session.add(ProjectRecord(
        id="proj-ignore", name="Old Idea", notion_page_id="page-ignore",
        notion_state="present", workspace_state="absent", sync_state="NOTION_ONLY", created_by="reconciliation",
    ))
    session.add(ReconciliationItemRecord(
        id="item-ignore", kind="notion_only", project_id="proj-ignore",
        notion_page_id="page-ignore", notion_name="Old Idea", status="open",
    ))
    await session.commit()

    response = await client.post("/api/v1/reconciliation/item-ignore/resolve", json={"action": "ignore"})
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"

    open_items = await client.get("/api/v1/reconciliation")
    assert open_items.json() == []


@pytest.mark.asyncio
async def test_reconciliation_create_folder_queues_job(client, session, fake_notion) -> None:
    session.add(ProjectRecord(
        id="proj-folder", name="ESP32 Sensors", notion_page_id="page-folder",
        notion_state="present", workspace_state="absent", sync_state="NOTION_ONLY", created_by="reconciliation",
    ))
    session.add(ReconciliationItemRecord(
        id="item-folder", kind="notion_only", project_id="proj-folder",
        notion_page_id="page-folder", notion_name="ESP32 Sensors", status="open",
    ))
    await session.commit()

    response = await client.post("/api/v1/reconciliation/item-folder/resolve", json={"action": "create_folder"})
    assert response.status_code == 200
    assert response.json()["resolution"] == "created_folder"

    jobs = list((await session.execute(select(CommandRecord))).scalars())
    assert len(jobs) == 1
    assert jobs[0].command_type == "project.create_directory"
    assert jobs[0].payload["project_id"] == "proj-folder"


@pytest.mark.asyncio
async def test_reconciliation_link_existing_merges_without_duplicate(client, session, fake_notion) -> None:
    session.add(ProjectRecord(
        id="proj-notion-only", name="Pencil Experiments", notion_page_id="page-link",
        notion_state="present", workspace_state="absent", sync_state="NOTION_ONLY", created_by="reconciliation",
    ))
    session.add(ProjectRecord(
        id="proj-workspace-only", name="pencil-experiments-folder", workspace_project_id="ws-link",
        workspace_path="Projects/pencil-experiments-folder", workspace_device="macbook",
        notion_state="absent", workspace_state="present", sync_state="WORKSPACE_ONLY", created_by="reconciliation",
    ))
    session.add(ReconciliationItemRecord(
        id="item-link", kind="workspace_only", project_id="proj-workspace-only",
        workspace_project_id="ws-link", workspace_name="pencil-experiments-folder", status="open",
    ))
    await session.commit()

    response = await client.post(
        "/api/v1/reconciliation/item-link/resolve",
        json={"action": "link_existing", "notion_page_id": "page-link"},
    )
    assert response.status_code == 200
    assert response.json()["resolution"] == "linked_existing"

    projects = list((await session.execute(select(ProjectRecord))).scalars())
    assert len(projects) == 2  # never deleted, but only one is now "live"
    linked = await session.get(ProjectRecord, "proj-notion-only")
    detached = await session.get(ProjectRecord, "proj-workspace-only")
    assert linked.workspace_project_id == "ws-link"
    assert detached.workspace_project_id is None
    assert fake_notion.updated == [("page-link", "Projects/pencil-experiments-folder")]
