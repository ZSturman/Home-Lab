from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .alerts import active_alerts, alert_payload, led_state
from .db import get_session
from .home_assistant import HomeAssistantClient, HomeAssistantError
from .models import (
    AlertRecord,
    AutomationRun,
    AutomationStage,
    CommandRecord,
    NodeRecord,
    ProjectRecord,
    ReconciliationItemRecord,
    ResourceRecord,
    ServiceProviderRecord,
)
from .mqtt import MqttPublisher
from .configuration import load_configuration
from .notion_client import NotionClient, ResourcesNotionClient
from .reconciliation import compute_sync_state, run_reconciliation
from .registry import ProviderAvailability, resolve_route
from .schemas import CommandRequest, CreateAutomationRun, CreateProjectRequest, CreateResourceRequest, LightActionRequest, ResolveReconciliationRequest
from .settings import get_settings
from .topics import ALERTS_CURRENT, PROJECT_JOBS_AVAILABLE, command_request
from .workspace_contract import fetch_storage_contract, fetch_workspace_status
from .tailnet import fetch_tailnet_status


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_timestamp(value: datetime) -> str:
    """SQLite reloads UTC DateTime columns without tzinfo; retain the wire contract."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def node_payload(record: NodeRecord) -> dict:
    return {
        "id": record.id,
        "name": record.display_name or record.id,
        "status": record.status,
        "health": record.health,
        "actual_state": record.actual_state,
        "capabilities": record.capabilities,
        "last_seen_at": utc_timestamp(record.last_seen_at) if record.last_seen_at else None,
    }


def provider_payload(record: ServiceProviderRecord) -> dict:
    return {
        "id": record.id,
        "node_id": record.node_id,
        "service_id": record.service_id,
        "health": record.health,
        "capabilities": record.capabilities,
        "details": record.details,
        "last_seen_at": utc_timestamp(record.last_seen_at) if record.last_seen_at else None,
    }


def command_payload(record: CommandRecord) -> dict:
    return {
        "id": record.id,
        "node_id": record.node_id,
        "command_type": record.command_type,
        "status": record.status,
        "payload": record.payload,
        "result": record.result,
        "expires_at": utc_timestamp(record.expires_at),
        "created_at": utc_timestamp(record.created_at),
    }


def run_payload(record: AutomationRun, stages: list[AutomationStage] | None = None) -> dict:
    return {
        "id": record.id,
        "automation_id": record.automation_id,
        "trigger": record.trigger,
        "status": record.status,
        "current_stage": record.current_stage,
        "started_at": utc_timestamp(record.started_at) if record.started_at else None,
        "completed_at": utc_timestamp(record.completed_at) if record.completed_at else None,
        "stages": [
            {"name": stage.name, "position": stage.position, "status": stage.status, "detail": stage.detail}
            for stage in (stages or [])
        ],
    }


async def snapshot(session: AsyncSession) -> dict:
    settings = get_settings()
    nodes = list((await session.execute(select(NodeRecord).order_by(NodeRecord.id))).scalars())
    providers = list((await session.execute(select(ServiceProviderRecord).order_by(ServiceProviderRecord.id))).scalars())
    alerts = await active_alerts(session)
    runs = list((await session.execute(
        select(AutomationRun).order_by(AutomationRun.created_at.desc()).limit(10)
    )).scalars())
    run_payloads = []
    for run in runs:
        stages = list((await session.execute(
            select(AutomationStage)
            .where(AutomationStage.run_id == run.id)
            .order_by(AutomationStage.position)
        )).scalars())
        run_payloads.append(run_payload(run, stages))
    return {
        "runtime": {
            "node_id": settings.platform_node_id,
            "node_name": settings.platform_node_name,
            "hardware_profile": settings.platform_hardware_profile,
        },
        "nodes": [node_payload(item) for item in nodes],
        "providers": [provider_payload(item) for item in providers],
        "alerts": [alert_payload(item) for item in alerts],
        "led": led_state(alerts),
        "runs": run_payloads,
    }


def registry_payload() -> dict:
    """Publish client-safe configuration, never machine paths or credentials."""
    config = load_configuration(get_settings().config_directory)
    return {
        "version": 1,
        "nodes": [node.model_dump(mode="json") for node in config.nodes],
        "devices": [device.model_dump(mode="json") for device in config.devices],
        "automations": [automation.model_dump(mode="json") for automation in config.automations],
        "services": [service.model_dump(mode="json") for service in config.services],
        # Only stable identity/type are client-safe here. Base URLs and secret
        # references stay inside the Control Plane configuration boundary.
        "integrations": [
            {"id": str(item.get("id", "")), "type": str(item.get("type", ""))}
            for item in config.integrations
        ],
    }


_ATTENTION_RANK = {"critical": 0, "error": 1, "warning": 2, "info": 3, "success": 4}


def _attention_item(*, kind: str, severity: str, title: str, detail: str, source: str, target: str) -> dict:
    """One client-safe, explainable item in the deterministic Now queue."""
    return {
        "kind": kind,
        "severity": severity if severity in _ATTENTION_RANK else "info",
        "title": title,
        "detail": detail,
        "source": source,
        "target": target,
    }


async def platform_overview(session: AsyncSession) -> dict:
    """Shared real-data read model for every Home Platform view.

    This is deliberately a composition of the existing durable state and the
    one approved Workspace Sync boundary. It creates no records and performs
    no host scraping, so an unavailable sibling service degrades only its
    own section rather than the entire dashboard.
    """
    state = await snapshot(session)
    projects = list((await session.execute(
        select(ProjectRecord).order_by(ProjectRecord.updated_at.desc()).limit(100)
    )).scalars())
    resources = list((await session.execute(
        select(ResourceRecord).order_by(ResourceRecord.updated_at.desc()).limit(100)
    )).scalars())
    workspace = await fetch_workspace_status()

    attention = [
        _attention_item(
            kind="alert", severity=item["severity"], title=item["title"],
            detail=item["detail"] or item["kind"], source=item["source_type"], target="attention",
        )
        for item in state["alerts"]
    ]
    for provider in state["providers"]:
        health = str(provider.get("health", "unknown")).lower()
        if health in {"offline", "failed", "error", "degraded"}:
            severity = "error" if health in {"offline", "failed", "error"} else "warning"
            attention.append(_attention_item(
                kind="service", severity=severity,
                title=f"{provider['service_id']} needs attention",
                detail=f"Reported health: {health} on {provider['node_id']}.",
                source="service-provider", target="system",
            ))
    for run in state["runs"]:
        if run["status"] in {"failed", "cancelled"}:
            attention.append(_attention_item(
                kind="automation", severity="error", title=f"Automation {run['automation_id']} {run['status']}",
                detail=run.get("current_stage") or "Review the run stages for details.",
                source="automation", target="automations",
            ))
    backup = workspace.get("backup") or {}
    backup_state = str(backup.get("state", "unknown")).lower()
    if backup_state in {"failed", "error", "interrupted"}:
        attention.append(_attention_item(
            kind="backup", severity="error", title="Backup needs attention",
            detail=str(backup.get("error") or backup.get("warning") or f"Backup state: {backup_state}."),
            source="workspace-sync", target="files",
        ))
    elif backup_state == "unknown":
        attention.append(_attention_item(
            kind="backup", severity="warning", title="Backup status is unavailable",
            detail=str(backup.get("warning") or "Workspace Sync has not reported a backup status."),
            source="workspace-sync", target="files",
        ))

    attention.sort(key=lambda item: (_ATTENTION_RANK[item["severity"]], item["title"].lower()))
    return {
        "generated_at": utc_now().isoformat(),
        "system": state,
        "attention": attention,
        "projects": [project_payload(project) for project in projects],
        "resources": [resource_payload(resource) for resource in resources],
        "workspace": workspace,
        "registry": registry_payload(),
    }


async def publish_attention(app: FastAPI, session: AsyncSession) -> None:
    alerts = await active_alerts(session)
    app.state.publisher.publish_event(
        ALERTS_CURRENT,
        {
            "alerts": [{"id": item.id, "kind": item.kind, "severity": item.severity, "title": item.title} for item in alerts],
            "led": led_state(alerts),
        },
        retain=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    publisher = MqttPublisher(get_settings(), "api")
    publisher.start()
    app.state.publisher = publisher
    yield
    publisher.stop()


app = FastAPI(title="Home Platform Control Plane", version="1.0.0", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "healthy"}


@app.get("/api/v1/home-page")
async def get_home_page(session: AsyncSession = Depends(get_session)) -> dict:
    # Same tailnet/loopback access boundary as the existing read-only endpoints.
    from .homepage import summary
    return summary(await active_alerts(session))


@app.get("/api/v1/system/snapshot")
async def get_snapshot(session: AsyncSession = Depends(get_session)) -> dict:
    return await snapshot(session)


@app.get("/api/v1/platform/overview")
async def get_platform_overview(session: AsyncSession = Depends(get_session)) -> dict:
    """The single read model used by responsive Home Platform views."""
    return await platform_overview(session)


@app.get("/api/v1/registry")
async def get_registry() -> dict:
    return registry_payload()


@app.get("/api/v1/nodes")
async def get_nodes(session: AsyncSession = Depends(get_session)) -> list[dict]:
    records = list((await session.execute(select(NodeRecord).order_by(NodeRecord.id))).scalars())
    return [node_payload(record) for record in records]


@app.get("/api/v1/services/providers")
async def get_providers(session: AsyncSession = Depends(get_session)) -> list[dict]:
    records = list((await session.execute(select(ServiceProviderRecord).order_by(ServiceProviderRecord.id))).scalars())
    return [provider_payload(record) for record in records]


@app.post("/api/v1/services/{service_id}/health-check", status_code=202)
async def request_service_health_check(service_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    config = load_configuration(get_settings().config_directory)
    service = next((item for item in config.services if item.id == service_id), None)
    if not service:
        raise HTTPException(status_code=404, detail="Service not found in the Home Platform registry")
    if service.health_check != "node-refresh-health" or not service.node_id:
        raise HTTPException(status_code=409, detail="This service does not expose a safe health-check action")
    command = CommandRecord(
        id=str(uuid4()),
        node_id=service.node_id,
        command_type="node.refresh-health",
        payload={"service_id": service.id},
        status="queued",
        expires_at=utc_now() + timedelta(seconds=60),
    )
    session.add(command)
    await session.commit()
    app.state.publisher.publish_event(
        command_request(command.node_id),
        {
            "command_id": command.id,
            "command_type": command.command_type,
            "payload": command.payload,
            "expires_at": utc_timestamp(command.expires_at),
        },
        correlation_id=command.id,
    )
    return command_payload(command)


@app.get("/api/v1/routes")
async def get_routes(session: AsyncSession = Depends(get_session)) -> list[dict]:
    records = list((await session.execute(select(ServiceProviderRecord))).scalars())
    available = [ProviderAvailability(item.node_id, item.service_id, item.health) for item in records]
    config = load_configuration(get_settings().config_directory)
    return [
        {
            "capability": route.capability,
            "strategy": route.strategy,
            "active_provider": (
                {"node_id": selected.node_id, "service_id": selected.service_id}
                if (selected := resolve_route(route, available)) else None
            ),
        }
        for route in config.routes
    ]


@app.get("/api/v1/alerts")
async def get_alerts(session: AsyncSession = Depends(get_session)) -> list[dict]:
    return [alert_payload(record) for record in await active_alerts(session)]


@app.post("/api/v1/alerts/{alert_id}/dismiss")
async def dismiss_alert(alert_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    alert = await session.get(AlertRecord, alert_id)
    if not alert or alert.status != "active":
        raise HTTPException(status_code=404, detail="Active alert not found")
    if not alert.dismissible:
        raise HTTPException(status_code=409, detail="This alert is resolved by fixing its source")
    alert.status, alert.dismissed_at = "dismissed", utc_now()
    await session.commit()
    await publish_attention(app, session)
    return alert_payload(alert)


@app.post("/api/v1/commands", status_code=202)
async def create_command(request: CommandRequest, session: AsyncSession = Depends(get_session)) -> dict:
    command_id = str(request.command_id or uuid4())
    existing = await session.get(CommandRecord, command_id)
    if existing:
        if existing.node_id != request.node_id or existing.command_type != request.command_type or existing.payload != request.payload:
            raise HTTPException(status_code=409, detail="Command ID was already used for a different request")
        return command_payload(existing)
    command = CommandRecord(
        id=command_id,
        node_id=request.node_id,
        command_type=request.command_type,
        payload=request.payload,
        status="queued",
        expires_at=utc_now() + timedelta(seconds=request.expires_in_seconds),
    )
    session.add(command)
    await session.commit()
    app.state.publisher.publish_event(
        command_request(command.node_id),
        {
            "command_id": command.id,
            "command_type": command.command_type,
            "payload": command.payload,
            "expires_at": utc_timestamp(command.expires_at),
        },
        correlation_id=command.id,
    )
    return command_payload(command)


@app.get("/api/v1/commands/{command_id}")
async def get_command(command_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    command = await session.get(CommandRecord, command_id)
    if not command:
        raise HTTPException(status_code=404, detail="Command not found")
    return command_payload(command)


@app.post("/api/v1/automations/{automation_id}/runs", status_code=202)
async def create_automation_run(
    automation_id: str,
    request: CreateAutomationRun,
    session: AsyncSession = Depends(get_session),
) -> dict:
    config = load_configuration(get_settings().config_directory)
    automation = config.automation(automation_id)
    if not automation:
        raise HTTPException(status_code=404, detail="Automation not found in the Home Platform registry")
    if not automation.enabled:
        raise HTTPException(status_code=409, detail="Automation is disabled by the Home Platform registry")
    if "run" not in automation.actions:
        raise HTTPException(status_code=409, detail="Automation does not support Run")
    if automation.runner != "control-plane":
        raise HTTPException(status_code=501, detail="This automation must be started by its owning node")
    try:
        arguments = automation.validate_arguments(request.arguments)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    run_id = str(request.run_id or uuid4())
    existing = await session.get(AutomationRun, run_id)
    if existing:
        if existing.automation_id != automation_id:
            raise HTTPException(status_code=409, detail="Run ID was already used for a different automation")
        return run_payload(existing)
    run = AutomationRun(
        id=run_id,
        automation_id=automation_id,
        trigger=request.trigger,
        result={"source": request.source, "arguments": arguments},
    )
    session.add(run)
    await session.commit()
    return run_payload(run)


@app.get("/api/v1/automations/runs")
async def list_runs(session: AsyncSession = Depends(get_session)) -> list[dict]:
    records = list((await session.execute(
        select(AutomationRun).order_by(AutomationRun.created_at.desc()).limit(50)
    )).scalars())
    result = []
    for record in records:
        stages = list((await session.execute(
            select(AutomationStage).where(AutomationStage.run_id == record.id).order_by(AutomationStage.position)
        )).scalars())
        result.append(run_payload(record, stages))
    return result


@app.post("/api/v1/automations/runs/{run_id}/stop")
async def stop_automation_run(run_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    run = await session.get(AutomationRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Automation run not found")
    automation = load_configuration(get_settings().config_directory).automation(run.automation_id)
    if not automation or "stop" not in automation.actions:
        raise HTTPException(status_code=409, detail="This automation does not support graceful Stop")
    if run.status in {"completed", "failed", "stopped"}:
        return run_payload(run)
    run.status = "cancelled"
    run.completed_at = run.completed_at or utc_now()
    stages = list((await session.execute(
        select(AutomationStage).where(AutomationStage.run_id == run_id)
    )).scalars())
    for stage in stages:
        if stage.status in {"queued", "running"}:
            stage.status, stage.completed_at = "cancelled", run.completed_at
    alerts = list((await session.execute(select(AlertRecord).where(
        AlertRecord.source_type == "automation", AlertRecord.source_id == run_id,
        AlertRecord.kind == "running", AlertRecord.status == "active",
    ))).scalars())
    for alert in alerts:
        alert.status = "resolved"
    await session.commit()
    await publish_attention(app, session)
    return run_payload(run)


@app.post("/api/v1/devices/{device_id}/light-action")
async def light_action(
    device_id: str,
    request: LightActionRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    try:
        result = await HomeAssistantClient(get_settings()).perform_light_action(device_id, request.action, request.step)
    except HomeAssistantError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "completed", "result": result}


def project_payload(record: ProjectRecord) -> dict:
    return {
        "id": record.id,
        "name": record.name,
        "notion_page_id": record.notion_page_id,
        "workspace_project_id": record.workspace_project_id,
        "workspace_path": record.workspace_path,
        "workspace_device": record.workspace_device,
        "template": record.template,
        "notion_state": record.notion_state,
        "workspace_state": record.workspace_state,
        "sync_state": record.sync_state,
        "created_by": record.created_by,
        "last_error": record.last_error,
        "created_at": utc_timestamp(record.created_at),
        "updated_at": utc_timestamp(record.updated_at),
    }


def reconciliation_item_payload(record: ReconciliationItemRecord) -> dict:
    return {
        "id": record.id,
        "kind": record.kind,
        "project_id": record.project_id,
        "notion_page_id": record.notion_page_id,
        "notion_name": record.notion_name,
        "workspace_project_id": record.workspace_project_id,
        "workspace_path": record.workspace_path,
        "workspace_name": record.workspace_name,
        "status": record.status,
        "resolution": record.resolution,
        "created_at": utc_timestamp(record.created_at),
        "updated_at": utc_timestamp(record.updated_at),
        "resolved_at": utc_timestamp(record.resolved_at) if record.resolved_at else None,
    }


def get_notion_client() -> NotionClient:
    settings = get_settings()
    return NotionClient(settings.notion_token_value, database_id=settings.notion_projects_database_id)


def get_resources_notion_client() -> ResourcesNotionClient:
    settings = get_settings()
    return ResourcesNotionClient(settings.notion_token_value, database_id=settings.notion_resources_database_id)


def normalize_remote_url(url: str) -> str:
    """Loose equality for comparing Git remotes: case, trailing slash/.git,
    and SSH-vs-HTTPS form shouldn't count as a different repository. Mirrors
    Project Core's ``normalize_git_url`` (project_core/core.py) -- kept as a
    small duplicated pure function rather than a cross-repo import, since
    Project Core is a client of this API, not a dependency of it."""
    value = url.strip().lower().removesuffix(".git").rstrip("/")
    if value.startswith("git@"):
        value = value.removeprefix("git@").replace(":", "/", 1)
    for prefix in ("https://", "http://", "ssh://git@", "ssh://"):
        if value.startswith(prefix):
            value = value[len(prefix):]
            break
    return value


def resource_payload(record: ResourceRecord) -> dict:
    return {
        "id": record.id,
        "resource_type": record.resource_type,
        "label": record.label,
        "remote_url": record.remote_url,
        "project_notion_page_id": record.project_notion_page_id,
        "notion_page_id": record.notion_page_id,
        "status": record.status,
        "created_by": record.created_by,
        "last_error": record.last_error,
        "created_at": utc_timestamp(record.created_at),
        "updated_at": utc_timestamp(record.updated_at),
    }


def _sanitize_project_name(name: str) -> str:
    value = name.strip()
    if not value or value in {".", ".."} or "/" in value or "\\" in value or "\x00" in value:
        raise HTTPException(status_code=422, detail="Project name must be a single, safe path segment")
    return value


def _queue_project_command(session: AsyncSession, *, project_id: str, command_type: str, payload: dict) -> CommandRecord:
    command = CommandRecord(
        id=str(uuid4()),
        node_id=get_settings().workspace_node_id,
        command_type=command_type,
        payload={"project_id": project_id, **payload},
        status="queued",
        expires_at=utc_now() + timedelta(days=3),
    )
    session.add(command)
    return command


def _publish_project_command(command: CommandRecord) -> None:
    app.state.publisher.publish_event(
        command_request(command.node_id),
        {
            "command_id": command.id,
            "command_type": command.command_type,
            "payload": command.payload,
            "expires_at": utc_timestamp(command.expires_at),
        },
        correlation_id=command.id,
    )
    # Retained wake ping: an already-connected Mac agent polls immediately
    # instead of waiting for its next cycle. Never the only delivery path --
    # the Mac also polls GET /api/v1/projects/jobs/pending unconditionally.
    app.state.publisher.publish_event(PROJECT_JOBS_AVAILABLE, {"node_id": command.node_id}, retain=True)


@app.post("/api/v1/projects", status_code=202)
async def create_project(
    request: CreateProjectRequest,
    session: AsyncSession = Depends(get_session),
    notion: NotionClient = Depends(get_notion_client),
) -> dict:
    existing = await session.scalar(
        select(ProjectRecord).where(ProjectRecord.idempotency_key == request.idempotency_key)
    )
    if existing:
        return project_payload(existing)

    safe_name = _sanitize_project_name(request.name)
    project = ProjectRecord(
        id=str(uuid4()),
        name=safe_name,
        template=request.template,
        notion_state="pending",
        workspace_state="absent",
        sync_state="PENDING_WORKSPACE_CREATION",
        created_by=request.source,
        idempotency_key=request.idempotency_key,
    )
    session.add(project)
    await session.flush()

    try:
        page = await notion.create_project_page(name=safe_name, local_directory=None)
        project.notion_page_id = str(page.get("id") or "") or None
        project.notion_state = "present" if project.notion_page_id else "error"
        if not project.notion_page_id:
            project.last_error = "Notion did not return a page id"
    except Exception as exc:  # Notion outage/rate limit must not block folder creation.
        project.notion_state = "error"
        project.last_error = f"Notion page creation failed: {exc}"

    command = _queue_project_command(
        session, project_id=project.id, command_type="project.create_directory",
        payload={"name": safe_name, "template": request.template},
    )
    project.sync_state = compute_sync_state(
        notion_state=project.notion_state, workspace_state="absent",
        has_active_job=True, has_failed_job=False, reconciliation_status=None,
    )
    await session.commit()
    _publish_project_command(command)
    return project_payload(project)


@app.post("/api/v1/resources", status_code=202)
async def create_resource(
    request: CreateResourceRequest,
    session: AsyncSession = Depends(get_session),
    notion: ResourcesNotionClient = Depends(get_resources_notion_client),
) -> dict:
    """Project Core's repo-onboarding external-mutation contract: a durable,
    idempotent request that results in exactly one Notion Resource page,
    never a duplicate one. Idempotent two ways, matching how ``/projects``
    already behaves for its own idempotency_key: a retried request with the
    same ``idempotency_key`` returns the original record untouched, and a
    request for a remote URL Project Hub already has a Resource for
    (regardless of idempotency_key -- e.g. two different pending actions
    that happened to name the same remote) returns that existing record
    instead of creating a second page."""
    existing = await session.scalar(select(ResourceRecord).where(ResourceRecord.idempotency_key == request.idempotency_key))
    if existing and existing.status != "error":
        return resource_payload(existing)  # already created (or in flight) -- a retry must not create a second page
    if existing is None:
        normalized = normalize_remote_url(request.remote_url)
        existing_by_url = await session.scalar(select(ResourceRecord).where(ResourceRecord.normalized_remote_url == normalized))
        if existing_by_url:
            return resource_payload(existing_by_url)
        resource = ResourceRecord(
            id=str(uuid4()),
            resource_type=request.resource_type,
            label=request.label,
            remote_url=request.remote_url,
            normalized_remote_url=normalized,
            project_notion_page_id=request.project_notion_page_id,
            status="pending",
            created_by=request.source,
            idempotency_key=request.idempotency_key,
        )
        session.add(resource)
        await session.flush()
    else:
        resource = existing  # a prior attempt with this exact key failed -- retry in place, never a second row

    try:
        page = await notion.create_resource_page(
            resource_type=request.resource_type, remote_url=request.remote_url,
            label=request.label, project_notion_page_id=request.project_notion_page_id,
        )
        resource.notion_page_id = str(page.get("id") or "") or None
        resource.status = "created" if resource.notion_page_id else "error"
        if not resource.notion_page_id:
            resource.last_error = "Notion did not return a page id"
    except Exception as exc:  # A Notion outage must produce a durable, retryable failure, not a 500.
        resource.status = "error"
        resource.last_error = f"Notion page creation failed: {exc}"
    await session.commit()
    return resource_payload(resource)


@app.get("/api/v1/resources/{resource_id}")
async def get_resource(resource_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    resource = await session.get(ResourceRecord, resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
    return resource_payload(resource)


@app.get("/api/v1/resources")
async def list_resources(session: AsyncSession = Depends(get_session)) -> list[dict]:
    records = list((await session.execute(select(ResourceRecord).order_by(ResourceRecord.created_at))).scalars())
    return [resource_payload(record) for record in records]


@app.get("/api/v1/storage/status")
async def get_storage_status() -> dict:
    """Summarized storage state for HomeLab Control, sourced entirely from
    Workspace Sync & Backup Utility's own contract -- this project never
    inspects disks/mounts/UUIDs itself. Never raises: an unreachable
    Workspace Sync Utility degrades to mode "unknown", it does not 503."""
    return await fetch_workspace_status()


@app.get("/api/v1/tailnet/status")
async def get_tailnet_status(session: AsyncSession = Depends(get_session)) -> dict:
    """Live, sanitized tailnet connectivity. This is intentionally separate
    from NodeRecord/MQTT health: a reachable device may not run an agent."""
    records = list((await session.execute(select(NodeRecord))).scalars())
    agents = [
        {"id": record.id, "name": record.display_name or record.id, "status": record.status,
         "health": record.health, "last_seen_at": utc_timestamp(record.last_seen_at) if record.last_seen_at else None}
        for record in records
    ]
    payload = await fetch_tailnet_status(agents=agents)
    # This endpoint being served is direct, current evidence that the local
    # control-plane API is healthy. It is intentionally separate from MQTT
    # agent records and tailnet peer connectivity.
    payload["local_platform_service"] = {"state": "healthy", "observed_at": utc_now().isoformat()}
    return payload


@app.get("/api/v1/projects")
async def list_projects(session: AsyncSession = Depends(get_session)) -> list[dict]:
    records = list((await session.execute(select(ProjectRecord).order_by(ProjectRecord.name))).scalars())
    return [project_payload(record) for record in records]


@app.get("/api/v1/projects/jobs")
async def list_project_jobs(session: AsyncSession = Depends(get_session)) -> list[dict]:
    records = list((await session.execute(
        select(CommandRecord).where(CommandRecord.command_type.like("project.%")).order_by(CommandRecord.created_at.desc()).limit(50)
    )).scalars())
    return [command_payload(record) for record in records]


@app.get("/api/v1/projects/jobs/pending")
async def list_pending_project_jobs(node_id: str, session: AsyncSession = Depends(get_session)) -> list[dict]:
    """Belt-and-suspenders poll target for the Mac agent: returns every
    not-yet-terminal project.* command for this node, independent of
    whether its MQTT request was ever received."""
    records = list((await session.execute(
        select(CommandRecord)
        .where(CommandRecord.node_id == node_id)
        .where(CommandRecord.command_type.like("project.%"))
        .where(CommandRecord.status.in_(["queued", "accepted", "running"]))
        .where(CommandRecord.expires_at > utc_now())
        .order_by(CommandRecord.created_at)
    )).scalars())
    return [command_payload(record) for record in records]


@app.get("/api/v1/projects/{project_id}")
async def get_project(project_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    project = await session.get(ProjectRecord, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    jobs = list((await session.execute(
        select(CommandRecord).where(CommandRecord.command_type.like("project.%")).order_by(CommandRecord.created_at.desc())
    )).scalars())
    matching_jobs = [command_payload(job) for job in jobs if str(job.payload.get("project_id")) == project_id]
    return {**project_payload(project), "jobs": matching_jobs}


@app.post("/api/v1/reconciliation/run")
async def trigger_reconciliation(
    session: AsyncSession = Depends(get_session),
    notion: NotionClient = Depends(get_notion_client),
) -> dict:
    summary = await run_reconciliation(session, notion)
    return {
        "notion_pages_seen": summary.notion_pages_seen,
        "workspace_entries_seen": summary.workspace_entries_seen,
        "projects_created": summary.projects_created,
        "projects_updated": summary.projects_updated,
        "reconciliation_items_opened": summary.reconciliation_items_opened,
        "errors": summary.errors,
    }


@app.get("/api/v1/reconciliation")
async def list_reconciliation_items(session: AsyncSession = Depends(get_session)) -> list[dict]:
    records = list((await session.execute(
        select(ReconciliationItemRecord).where(ReconciliationItemRecord.status == "open").order_by(ReconciliationItemRecord.created_at)
    )).scalars())
    return [reconciliation_item_payload(record) for record in records]


@app.post("/api/v1/reconciliation/{item_id}/resolve")
async def resolve_reconciliation_item(
    item_id: str,
    request: ResolveReconciliationRequest,
    session: AsyncSession = Depends(get_session),
    notion: NotionClient = Depends(get_notion_client),
) -> dict:
    item = await session.get(ReconciliationItemRecord, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Reconciliation item not found")
    if item.status != "open":
        return reconciliation_item_payload(item)

    if request.action == "ignore":
        item.status, item.resolution, item.resolved_at = "ignored", "ignored", utc_now()
        if item.project_id:
            project = await session.get(ProjectRecord, item.project_id)
            if project:
                project.sync_state = "IGNORED"
        await session.commit()
        return reconciliation_item_payload(item)

    if not item.project_id:
        raise HTTPException(status_code=409, detail="This item has no associated project row")
    project = await session.get(ProjectRecord, item.project_id)
    if not project:
        raise HTTPException(status_code=409, detail="Associated project row is missing")

    if request.action == "create_folder":
        if item.kind != "notion_only":
            raise HTTPException(status_code=409, detail="create_folder only applies to a Notion-only item")
        command = _queue_project_command(
            session, project_id=project.id, command_type="project.create_directory",
            payload={"name": project.name, "template": project.template},
        )
        item.status, item.resolution, item.resolved_at = "resolved", "created_folder", utc_now()
        await session.commit()
        _publish_project_command(command)
        return reconciliation_item_payload(item)

    if request.action == "create_notion":
        if item.kind != "workspace_only":
            raise HTTPException(status_code=409, detail="create_notion only applies to a workspace-only item")
        try:
            page = await notion.create_project_page(name=project.name, local_directory=project.workspace_path)
            project.notion_page_id = str(page.get("id") or "") or None
            project.notion_state = "present" if project.notion_page_id else "error"
        except Exception as exc:
            project.notion_state = "error"
            project.last_error = f"Notion page creation failed: {exc}"
            await session.commit()
            raise HTTPException(status_code=502, detail=f"Notion page creation failed: {exc}") from exc
        item.status, item.resolution, item.resolved_at = "resolved", "created_notion", utc_now()
        await session.commit()
        return reconciliation_item_payload(item)

    if request.action == "link_existing":
        if item.kind != "workspace_only" or not request.notion_page_id:
            raise HTTPException(status_code=422, detail="link_existing requires a workspace-only item and a notion_page_id")
        target = await session.scalar(select(ProjectRecord).where(ProjectRecord.notion_page_id == request.notion_page_id))
        if not target or target.id == project.id:
            raise HTTPException(status_code=404, detail="Target Notion project not found")
        # Merge: the workspace-only row's folder becomes the target's folder;
        # the workspace-only row is retired (never deleted -- just detached).
        # workspace_project_id is unique, so the old holder must be cleared
        # and flushed before the target can take it, or the two UPDATEs can
        # collide transiently within the same flush.
        moved_workspace_project_id = project.workspace_project_id
        moved_workspace_path = project.workspace_path
        moved_workspace_device = project.workspace_device
        project.workspace_project_id = None
        project.workspace_state = "absent"
        project.sync_state = "IGNORED"
        await session.flush()
        target.workspace_project_id = moved_workspace_project_id
        target.workspace_path = moved_workspace_path
        target.workspace_device = moved_workspace_device
        target.workspace_state = "present"
        try:
            await notion.update_project_local_directory(request.notion_page_id, target.workspace_path or "")
        except Exception as exc:
            target.last_error = f"Failed to write Local Directory back to Notion: {exc}"
        item.status, item.resolution, item.resolved_at = "resolved", "linked_existing", utc_now()
        await session.commit()
        return reconciliation_item_payload(item)

    raise HTTPException(status_code=422, detail="Unsupported action")


@app.websocket("/api/v1/live")
async def live_updates(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            # A fresh dependency-free session keeps the stream alive across API requests.
            from .db import SessionLocal
            async with SessionLocal() as session:
                await websocket.send_json({"type": "system.snapshot", "data": await snapshot(session)})
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        return
