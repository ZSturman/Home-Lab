from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError


class NodeConfig(BaseModel):
    id: str
    name: str
    roles: list[str] = Field(min_length=1)


class DeviceConfig(BaseModel):
    id: str
    name: str
    type: str
    node_id: str
    integration: str | None = None
    entity_id: str | None = None


class ServiceConfig(BaseModel):
    id: str
    name: str
    capability: str


class RouteProvider(BaseModel):
    service: str
    node: str
    priority: int


class RouteConfig(BaseModel):
    capability: str
    strategy: Literal["single-provider", "priority-failover"]
    providers: list[RouteProvider] = Field(min_length=1)


class AutomationConfig(BaseModel):
    id: str
    name: str
    significant: bool = False
    enabled: bool = True


class VersionedList(BaseModel):
    version: Literal[1]


class PlatformConfiguration(BaseModel):
    nodes: list[NodeConfig]
    devices: list[DeviceConfig]
    services: list[ServiceConfig]
    routes: list[RouteConfig]
    automations: list[AutomationConfig]
    integrations: list[dict[str, Any]]

    def desired_state(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"integrations"})

    def checksum(self) -> str:
        encoded = json.dumps(self.desired_state(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode()).hexdigest()


def _read_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ValueError(f"{path.name} must be a version 1 mapping")
    return value


def _expand_environment(value: Any) -> Any:
    if isinstance(value, str):
        return os.path.expandvars(value)
    if isinstance(value, list):
        return [_expand_environment(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand_environment(item) for key, item in value.items()}
    return value


def load_configuration(directory: Path) -> PlatformConfiguration:
    files = {name: _expand_environment(_read_yaml(directory / f"{name}.yaml")) for name in (
        "nodes", "devices", "services", "routes", "automations", "integrations",
    )}
    try:
        return PlatformConfiguration(
            nodes=files["nodes"]["nodes"],
            devices=files["devices"]["devices"],
            services=files["services"]["services"],
            routes=files["routes"]["routes"],
            automations=files["automations"]["automations"],
            integrations=files["integrations"]["integrations"],
        )
    except (KeyError, ValidationError) as exc:
        raise ValueError(f"Invalid Home Platform configuration: {exc}") from exc
