from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Envelope(BaseModel):
    schema_version: Literal[1] = 1
    event_id: UUID = Field(default_factory=uuid4)
    producer: str
    occurred_at: datetime
    correlation_id: UUID | None = None
    payload: dict[str, Any]


class NodePresence(BaseModel):
    status: Literal["online", "offline", "degraded"]
    hostname: str
    os: str = ""
    health: Literal["healthy", "degraded", "offline", "unknown"] = "unknown"


class CommandRequest(BaseModel):
    command_id: UUID | None = None
    node_id: str
    command_type: str = Field(pattern=r"^[a-z][a-z0-9._-]+$")
    payload: dict[str, Any] = Field(default_factory=dict)
    expires_in_seconds: int = Field(default=60, ge=5, le=3600)


class CommandResultPayload(BaseModel):
    command_id: UUID
    status: Literal["accepted", "running", "completed", "failed", "unsupported", "expired"]
    detail: str = ""
    result: dict[str, Any] = Field(default_factory=dict)


class LightActionRequest(BaseModel):
    action: Literal["toggle", "brightness", "color_temperature"]
    step: int | None = Field(default=None, ge=-1000, le=1000)


class CreateAutomationRun(BaseModel):
    trigger: Literal["manual", "scheduled", "test"] = "manual"
    run_id: UUID | None = None
    source: Literal["macos-app", "ios-app", "widget", "control-center", "dashboard", "scheduled", "other"] = "other"
    arguments: dict[str, Any] = Field(default_factory=dict)


PROJECT_TEMPLATES = Literal["empty", "swift-app", "python", "web-app", "experiment", "utility"]


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    template: PROJECT_TEMPLATES = "empty"
    idempotency_key: str = Field(min_length=1, max_length=120)
    source: Literal["ios-app", "macos-app", "dashboard", "reconciliation", "other"] = "other"


class CreateResourceRequest(BaseModel):
    """Project Core's repo-onboarding external-mutation request. ``resource_type``
    matches the live Resources database's own ``type`` select options
    (repo/visit/install/download) rather than inventing a parallel vocabulary."""

    project_notion_page_id: str = Field(min_length=1, max_length=80)
    resource_type: Literal["repo", "visit", "install", "download"] = "repo"
    remote_url: str = Field(min_length=1, max_length=500)
    label: str = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=1, max_length=160)
    source: Literal["project-core", "other"] = "project-core"


class ResolveReconciliationRequest(BaseModel):
    action: Literal["create_folder", "create_notion", "link_existing", "ignore"]
    # Required only for link_existing: the notion_page_id of the existing
    # Projects row to associate with this workspace-only directory.
    notion_page_id: str | None = None
