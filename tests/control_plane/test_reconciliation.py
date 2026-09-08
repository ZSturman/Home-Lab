from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from app.models import CommandRecord, NodeRecord, ProjectRecord, ReconciliationItemRecord
from app.reconciliation import compute_sync_state, run_reconciliation


def _rich_text(value: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": {"content": value}, "plain_text": value}]


def _notion_page(page_id: str, name: str, *, local_directory: str | None = None, archived: bool = False) -> dict[str, Any]:
    properties: dict[str, Any] = {"title": {"type": "title", "title": _rich_text(name)}}
    if local_directory is not None:
        properties["Local Directory"] = {"type": "rich_text", "rich_text": _rich_text(local_directory)}
    return {"id": page_id, "archived": archived, "properties": properties}


class FakeNotionClient:
    def __init__(self, pages: list[dict[str, Any]] | None = None) -> None:
        self.pages = pages or []
        self.query_calls = 0

    async def query_all_projects(self) -> list[dict[str, Any]]:
        self.query_calls += 1
        return self.pages


# --- Pure state-machine tests --------------------------------------------

def test_synced_when_both_sides_present() -> None:
    assert compute_sync_state(
        notion_state="present", workspace_state="present", has_active_job=False,
        has_failed_job=False, reconciliation_status=None,
    ) == "SYNCED"


def test_pending_workspace_creation_while_job_active() -> None:
    assert compute_sync_state(
        notion_state="present", workspace_state="absent", has_active_job=True,
        has_failed_job=False, reconciliation_status=None,
    ) == "PENDING_WORKSPACE_CREATION"


def test_notion_only_without_active_job() -> None:
    assert compute_sync_state(
        notion_state="present", workspace_state="absent", has_active_job=False,
        has_failed_job=False, reconciliation_status=None,
    ) == "NOTION_ONLY"


def test_workspace_only_without_active_job() -> None:
    assert compute_sync_state(
        notion_state="absent", workspace_state="present", has_active_job=False,
        has_failed_job=False, reconciliation_status=None,
    ) == "WORKSPACE_ONLY"


def test_pending_notion_creation_while_job_active() -> None:
    assert compute_sync_state(
        notion_state="absent", workspace_state="present", has_active_job=True,
        has_failed_job=False, reconciliation_status=None,
    ) == "PENDING_NOTION_CREATION"


def test_error_when_job_failed() -> None:
    assert compute_sync_state(
        notion_state="present", workspace_state="absent", has_active_job=False,
        has_failed_job=True, reconciliation_status=None,
    ) == "ERROR"


def test_ignored_overrides_everything() -> None:
    assert compute_sync_state(
        notion_state="present", workspace_state="present", has_active_job=False,
        has_failed_job=False, reconciliation_status="ignored",
    ) == "IGNORED"


def test_name_mismatch_when_both_present_but_flagged() -> None:
    assert compute_sync_state(
        notion_state="present", workspace_state="present", has_active_job=False,
        has_failed_job=False, reconciliation_status=None, name_mismatch=True,
    ) == "NAME_MISMATCH"


# --- run_reconciliation integration tests (fake Notion, real SQLite) -----

@pytest.mark.asyncio
async def test_notion_only_project_is_detected(session) -> None:
    notion = FakeNotionClient([_notion_page("page-1", "ESP32 Sensors")])
    summary = await run_reconciliation(session, notion)

    assert summary.projects_created == 1
    assert summary.reconciliation_items_opened == 1

    project = await session.scalar(select(ProjectRecord).where(ProjectRecord.notion_page_id == "page-1"))
    assert project is not None
    assert project.sync_state == "NOTION_ONLY"

    item = await session.scalar(select(ReconciliationItemRecord).where(ReconciliationItemRecord.kind == "notion_only"))
    assert item is not None
    assert item.status == "open"
    assert item.notion_name == "ESP32 Sensors"


@pytest.mark.asyncio
async def test_workspace_only_project_is_detected(session) -> None:
    session.add(NodeRecord(
        id="macbook",
        actual_state={"workspace_projects": [
            {"workspace_project_id": "ws-1", "name": "Pencil Experiments", "path": "Projects/Pencil Experiments", "status": "active"},
        ]},
    ))
    await session.commit()

    notion = FakeNotionClient([])
    summary = await run_reconciliation(session, notion)

    assert summary.projects_created == 1
    assert summary.reconciliation_items_opened == 1

    project = await session.scalar(select(ProjectRecord).where(ProjectRecord.workspace_project_id == "ws-1"))
    assert project is not None
    assert project.sync_state == "WORKSPACE_ONLY"


@pytest.mark.asyncio
async def test_synced_project_produces_no_reconciliation_item(session) -> None:
    session.add(NodeRecord(
        id="macbook",
        actual_state={"workspace_projects": [
            {"workspace_project_id": "ws-2", "name": "Better Ideas", "path": "Projects/Better Ideas", "status": "active"},
        ]},
    ))
    await session.commit()

    notion = FakeNotionClient([_notion_page("page-2", "Better Ideas", local_directory="Projects/Better Ideas")])
    summary = await run_reconciliation(session, notion)

    assert summary.projects_created == 1  # linked, not duplicated
    assert summary.reconciliation_items_opened == 0

    project = await session.scalar(select(ProjectRecord))
    assert project.notion_page_id == "page-2"
    assert project.workspace_project_id == "ws-2"
    assert project.sync_state == "SYNCED"


@pytest.mark.asyncio
async def test_reconciliation_is_idempotent(session) -> None:
    notion = FakeNotionClient([_notion_page("page-3", "ESP32 Sensors")])
    await run_reconciliation(session, notion)
    second = await run_reconciliation(session, notion)

    assert second.projects_created == 0
    assert second.reconciliation_items_opened == 0

    projects = list((await session.execute(select(ProjectRecord))).scalars())
    items = list((await session.execute(select(ReconciliationItemRecord))).scalars())
    assert len(projects) == 1
    assert len(items) == 1


@pytest.mark.asyncio
async def test_running_many_times_stays_idempotent(session) -> None:
    notion = FakeNotionClient([_notion_page("page-4", "ESP32 Sensors")])
    for _ in range(5):
        await run_reconciliation(session, notion)

    projects = list((await session.execute(select(ProjectRecord))).scalars())
    items = list((await session.execute(select(ReconciliationItemRecord))).scalars())
    assert len(projects) == 1
    assert len(items) == 1


@pytest.mark.asyncio
async def test_notion_rename_updates_existing_row_not_a_new_one(session) -> None:
    notion = FakeNotionClient([_notion_page("page-5", "Old Name")])
    await run_reconciliation(session, notion)

    notion.pages = [_notion_page("page-5", "New Name")]
    await run_reconciliation(session, notion)

    projects = list((await session.execute(select(ProjectRecord))).scalars())
    assert len(projects) == 1
    assert projects[0].name == "New Name"


@pytest.mark.asyncio
async def test_disappeared_notion_page_is_flagged_not_deleted(session) -> None:
    notion = FakeNotionClient([_notion_page("page-6", "Vanishing Project")])
    await run_reconciliation(session, notion)

    notion.pages = [_notion_page("page-6", "Vanishing Project", archived=True)]
    await run_reconciliation(session, notion)

    projects = list((await session.execute(select(ProjectRecord))).scalars())
    assert len(projects) == 1  # never deleted
    assert projects[0].notion_state == "absent"


@pytest.mark.asyncio
async def test_active_job_suppresses_reconciliation_item(session) -> None:
    project = ProjectRecord(
        id="proj-active", name="In Flight", notion_page_id="page-7",
        notion_state="present", workspace_state="absent", sync_state="PENDING_WORKSPACE_CREATION",
        created_by="ios-app",
    )
    session.add(project)
    session.add(CommandRecord(
        id="cmd-1", node_id="macbook", command_type="project.create_directory",
        payload={"project_id": "proj-active", "name": "In Flight"}, status="queued",
        expires_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc) + __import__("datetime").timedelta(days=1),
    ))
    await session.commit()

    notion = FakeNotionClient([_notion_page("page-7", "In Flight")])
    summary = await run_reconciliation(session, notion)

    assert summary.reconciliation_items_opened == 0
    refreshed = await session.get(ProjectRecord, "proj-active")
    assert refreshed.sync_state == "PENDING_WORKSPACE_CREATION"


@pytest.mark.asyncio
async def test_notion_query_failure_does_not_crash_the_pass(session) -> None:
    class ExplodingNotionClient:
        async def query_all_projects(self):
            raise RuntimeError("Notion is rate limited")

    summary = await run_reconciliation(session, ExplodingNotionClient())
    assert summary.errors
    assert "notion_query_failed" in summary.errors[0]
