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
    icon: str = "puzzlepiece.extension.fill"
    node_id: str | None = None
    health_check: Literal["none", "node-refresh-health"] = "none"


class RouteProvider(BaseModel):
    service: str
    node: str
    priority: int


class RouteConfig(BaseModel):
    capability: str
    strategy: Literal["single-provider", "priority-failover"]
    providers: list[RouteProvider] = Field(min_length=1)


class ArgumentOption(BaseModel):
    value: str
    title: str


class AutomationArgumentConfig(BaseModel):
    """A deliberately small, safe argument vocabulary exposed to clients."""

    id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    title: str
    kind: Literal["boolean", "choice", "string"]
    description: str = ""
    default: bool | str | None = None
    required: bool = False
    options: list[ArgumentOption] = Field(default_factory=list)
    maximum_length: int = Field(default=256, ge=1, le=4096)

    def validate_value(self, value: Any) -> bool:
        if self.kind == "boolean":
            return isinstance(value, bool)
        if self.kind == "choice":
            return isinstance(value, str) and value in {option.value for option in self.options}
        return isinstance(value, str) and len(value) <= self.maximum_length


class AutomationPresetConfig(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    title: str
    arguments: dict[str, bool | str] = Field(default_factory=dict)


class AutomationScheduleConfig(BaseModel):
    owner: str
    description: str
    next_run_at: str | None = None


class AutomationConfig(BaseModel):
    id: str
    name: str
    description: str = ""
    icon: str = "bolt.fill"
    node_id: str | None = None
    runner: Literal["control-plane", "node-command", "local-process"] = "control-plane"
    significant: bool = False
    enabled: bool = True
    actions: list[Literal["run", "stop", "pause", "resume"]] = Field(default_factory=lambda: ["run"])
    arguments: list[AutomationArgumentConfig] = Field(default_factory=list)
    presets: list[AutomationPresetConfig] = Field(default_factory=list)
    schedule: AutomationScheduleConfig | None = None

    def validate_arguments(self, arguments: dict[str, Any]) -> dict[str, bool | str]:
        definitions = {definition.id: definition for definition in self.arguments}
        unexpected = set(arguments) - set(definitions)
        if unexpected:
            raise ValueError(f"Unsupported automation arguments: {', '.join(sorted(unexpected))}")
        validated: dict[str, bool | str] = {}
        for identifier, definition in definitions.items():
            value = arguments.get(identifier, definition.default)
            if value is None:
                if definition.required:
                    raise ValueError(f"Missing required automation argument: {identifier}")
                continue
            if not definition.validate_value(value):
                raise ValueError(f"Invalid value for automation argument: {identifier}")
            validated[identifier] = value
        return validated


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

    def automation(self, automation_id: str) -> AutomationConfig | None:
        return next((automation for automation in self.automations if automation.id == automation_id), None)


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
