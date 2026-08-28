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
