"""Bidirectional Project Hub reconciliation engine.

Compares three views of the world -- the Hub's own `projects` table, the
live Notion Projects data source, and the most recent workspace-folder scan
reported by the Mac node -- and produces/updates `projects` rows plus
actionable `reconciliation_items`. Never deletes a Notion page, a directory,
a `projects` row, or a `reconciliation_items` row; a side that disappears is
recorded as absent, not removed.

Idempotent by construction: matching is always keyed by a stable id
(`notion_page_id`, `workspace_project_id`), and a reconciliation item is
created at most once per (kind, key) regardless of status, so re-running
this never produces duplicate items, duplicate `projects` rows, or duplicate
Notion/workspace writes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import CommandRecord, NodeRecord, ProjectRecord, ReconciliationItemRecord
from .notion_client import NotionClient, page_local_directory, page_title

LOG = logging.getLogger(__name__)

ACTIVE_COMMAND_STATUSES = {"queued", "accepted", "running"}
TERMINAL_PROJECT_COMMAND_STATUSES = {"failed", "unsupported", "expired"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def compute_sync_state(
    *,
    notion_state: str,
    workspace_state: str,
    has_active_job: bool,
    has_failed_job: bool,
    reconciliation_status: str | None,
    name_mismatch: bool = False,
) -> str:
    """Pure projection used both by reconciliation and by project mutation
    endpoints, so the same ten states are always derived the same way."""

    if reconciliation_status == "ignored":
        return "IGNORED"
    if notion_state == "present" and workspace_state == "present":
        if name_mismatch:
            return "NAME_MISMATCH"
        return "SYNCED"
    if has_failed_job:
        return "ERROR"
    if notion_state == "present" and workspace_state == "absent":
        return "PENDING_WORKSPACE_CREATION" if has_active_job else "NOTION_ONLY"
    if notion_state == "absent" and workspace_state == "present":
        return "PENDING_NOTION_CREATION" if has_active_job else "WORKSPACE_ONLY"
    if notion_state == "absent" and workspace_state == "absent":
        return "ERROR"
    return "ERROR"


@dataclass
class ReconciliationSummary:
    notion_pages_seen: int = 0
    workspace_entries_seen: int = 0
    projects_created: int = 0
    projects_updated: int = 0
    reconciliation_items_opened: int = 0
    errors: list[str] = field(default_factory=list)


async def _active_project_command_state(session: AsyncSession) -> tuple[set[str], set[str]]:
    """Returns (project_ids_with_active_job, project_ids_with_failed_job)
    for every project.* command, computed once per run to avoid a
    database-specific JSON query for each project row."""

    records = list((await session.execute(
        select(CommandRecord).where(CommandRecord.command_type.like("project.%"))
    )).scalars())
    active: set[str] = set()
    failed: set[str] = set()
    for record in records:
        project_id = str(record.payload.get("project_id") or "")
        if not project_id:
            continue
        if record.status in ACTIVE_COMMAND_STATUSES:
            active.add(project_id)
        elif record.status in TERMINAL_PROJECT_COMMAND_STATUSES:
            failed.add(project_id)
    return active, failed


async def _open_reconciliation_item(
    session: AsyncSession,
    *,
    kind: str,
    project_id: str | None,
    notion_page_id: str | None,
    notion_name: str | None,
    workspace_project_id: str | None,
    workspace_path: str | None,
    workspace_name: str | None,
) -> bool:
    """Creates a reconciliation item unless one already exists for this
    (kind, key) -- regardless of its current status. Returns True if a new
    item was created."""

    query = select(ReconciliationItemRecord).where(ReconciliationItemRecord.kind == kind)
    if kind == "notion_only":
        query = query.where(ReconciliationItemRecord.notion_page_id == notion_page_id)
    else:
        query = query.where(ReconciliationItemRecord.workspace_project_id == workspace_project_id)
    existing = await session.scalar(query)
    if existing:
        return False
    session.add(ReconciliationItemRecord(
        id=str(uuid4()),
        kind=kind,
        project_id=project_id,
        notion_page_id=notion_page_id,
        notion_name=notion_name,
        workspace_project_id=workspace_project_id,
        workspace_path=workspace_path,
        workspace_name=workspace_name,
        status="open",
    ))
    return True


async def run_reconciliation(session: AsyncSession, notion: NotionClient) -> ReconciliationSummary:
    summary = ReconciliationSummary()

    by_notion_page: dict[str, ProjectRecord] = {}
    by_workspace_project: dict[str, ProjectRecord] = {}
    for record in (await session.execute(select(ProjectRecord))).scalars():
        if record.notion_page_id:
            by_notion_page[record.notion_page_id] = record
        if record.workspace_project_id:
            by_workspace_project[record.workspace_project_id] = record

    # --- Notion side -------------------------------------------------
    try:
        pages = await notion.query_all_projects()
    except Exception as exc:  # Notion outage/rate-limit: never fail the whole pass.
        LOG.warning("Notion query failed during reconciliation: %s", exc)
        summary.errors.append(f"notion_query_failed: {exc}")
        pages = []

    for page in pages:
        page_id = str(page.get("id") or "")
        if not page_id:
            continue
        summary.notion_pages_seen += 1
        archived = bool(page.get("archived") or page.get("in_trash"))
        name = page_title(page) or "(untitled)"
        local_directory = page_local_directory(page)
        existing = by_notion_page.get(page_id)

        if archived:
            if existing and existing.notion_state != "absent":
                existing.notion_state = "absent"
                existing.updated_at = utc_now()
                summary.projects_updated += 1
            continue

        if existing:
            changed = False
            if existing.name != name:
                existing.name = name
                changed = True
            if existing.notion_state != "present":
                existing.notion_state = "present"
                changed = True
            if not existing.workspace_path and local_directory and existing.workspace_state == "absent":
                existing.workspace_path = local_directory
                changed = True
            if changed:
                existing.updated_at = utc_now()
                summary.projects_updated += 1
            continue

        # No projects row references this page yet. If a workspace-only row
        # already recorded this exact path (e.g. Notion's Local Directory
        # was set by hand to an existing folder), link instead of duplicate.
        linked = None
        if local_directory:
            for candidate in by_workspace_project.values():
                if candidate.notion_page_id is None and candidate.workspace_path == local_directory:
                    linked = candidate
                    break
        if linked:
            linked.notion_page_id = page_id
            linked.notion_state = "present"
            linked.updated_at = utc_now()
            by_notion_page[page_id] = linked
            summary.projects_updated += 1
            continue

        created = ProjectRecord(
            id=str(uuid4()),
            name=name,
            notion_page_id=page_id,
            workspace_path=local_directory,
            template="empty",
            notion_state="present",
            workspace_state="absent",
            created_by="reconciliation",
        )
        session.add(created)
        by_notion_page[page_id] = created
        summary.projects_created += 1

    # --- Workspace side ------------------------------------------------
    nodes = list((await session.execute(select(NodeRecord))).scalars())
    for node in nodes:
        entries = node.actual_state.get("workspace_projects")
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            workspace_project_id = str(entry.get("workspace_project_id") or "")
            if not workspace_project_id:
                continue
            summary.workspace_entries_seen += 1
            status = str(entry.get("status") or "active")
            path = str(entry.get("path") or "")
            name = str(entry.get("name") or "")
            existing = by_workspace_project.get(workspace_project_id)

            if status == "deleted":
                if existing and existing.workspace_state != "absent":
                    existing.workspace_state = "absent"
                    existing.updated_at = utc_now()
                    summary.projects_updated += 1
                continue

            if existing:
                changed = False
                if existing.workspace_path != path:
                    existing.workspace_path, changed = path, True
                if existing.workspace_device != node.id:
                    existing.workspace_device, changed = node.id, True
                if existing.workspace_state != "present":
                    existing.workspace_state, changed = "present", True
                if not existing.notion_page_id and existing.name != name and name:
                    existing.name, changed = name, True
                if changed:
                    existing.updated_at = utc_now()
                    summary.projects_updated += 1
                continue

            # Not tracked yet. If an existing Notion-only row already points
            # at this exact path, link rather than duplicate.
            linked = None
            for candidate in by_notion_page.values():
                if candidate.workspace_project_id is None and candidate.workspace_path == path:
                    linked = candidate
                    break
            if linked:
                linked.workspace_project_id = workspace_project_id
                linked.workspace_device = node.id
                linked.workspace_state = "present"
                linked.updated_at = utc_now()
                by_workspace_project[workspace_project_id] = linked
                summary.projects_updated += 1
                continue

            created = ProjectRecord(
                id=str(uuid4()),
                name=name or workspace_project_id,
                workspace_project_id=workspace_project_id,
                workspace_path=path,
                workspace_device=node.id,
                template="empty",
                notion_state="absent",
                workspace_state="present",
                created_by="reconciliation",
            )
            session.add(created)
            by_workspace_project[workspace_project_id] = created
            summary.projects_created += 1

    await session.flush()

    # --- Recompute sync_state + open reconciliation items ---------------
    active_jobs, failed_jobs = await _active_project_command_state(session)
    all_projects = list({record.id: record for record in {**by_notion_page, **by_workspace_project}.values()}.values())
    for record in all_projects:
        existing_item = await session.scalar(
            select(ReconciliationItemRecord).where(ReconciliationItemRecord.project_id == record.id)
        )
        reconciliation_status = existing_item.status if existing_item else None
        name_mismatch = False  # Name-mismatch detection is display-side today; reserved for a future property compare.
        record.sync_state = compute_sync_state(
            notion_state=record.notion_state,
            workspace_state=record.workspace_state,
            has_active_job=record.id in active_jobs,
            has_failed_job=record.id in failed_jobs,
            reconciliation_status=reconciliation_status,
            name_mismatch=name_mismatch,
        )

        if record.notion_state == "present" and record.workspace_state == "absent" and record.id not in active_jobs:
            if await _open_reconciliation_item(
                session, kind="notion_only", project_id=record.id,
                notion_page_id=record.notion_page_id, notion_name=record.name,
                workspace_project_id=None, workspace_path=None, workspace_name=None,
            ):
                summary.reconciliation_items_opened += 1
        elif record.notion_state == "absent" and record.workspace_state == "present" and record.id not in active_jobs:
            if await _open_reconciliation_item(
                session, kind="workspace_only", project_id=record.id,
                notion_page_id=None, notion_name=None,
                workspace_project_id=record.workspace_project_id, workspace_path=record.workspace_path,
                workspace_name=record.name,
            ):
                summary.reconciliation_items_opened += 1

    await session.commit()
    return summary
