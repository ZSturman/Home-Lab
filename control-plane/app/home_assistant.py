from __future__ import annotations

from typing import Any

import httpx

from .configuration import load_configuration
from .settings import Settings


class HomeAssistantError(RuntimeError):
    pass


class HomeAssistantClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def headers(self) -> dict[str, str]:
        if not self.settings.home_assistant_token_value:
            raise HomeAssistantError("Home Assistant token is not configured")
        return {"Authorization": f"Bearer {self.settings.home_assistant_token_value}"}

    def entity_id_for_device(self, device_id: str) -> str:
        config = load_configuration(self.settings.config_directory)
        for device in config.devices:
            if device.id == device_id and device.integration == "home-assistant" and device.entity_id:
                return device.entity_id
        raise HomeAssistantError(f"No Home Assistant entity is configured for {device_id}")

    async def call_light_service(self, entity_id: str, service: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        body = {"entity_id": entity_id, **(data or {})}
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{self.settings.home_assistant_url.rstrip('/')}/api/services/light/{service}",
                headers=self.headers,
                json=body,
            )
        if response.is_error:
            raise HomeAssistantError(f"Home Assistant returned {response.status_code}: {response.text[:240]}")
        return {"entity_id": entity_id, "service": service, "response": response.json()}

    async def light_state(self, entity_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{self.settings.home_assistant_url.rstrip('/')}/api/states/{entity_id}",
                headers=self.headers,
            )
        if response.is_error:
            raise HomeAssistantError(f"Home Assistant state read returned {response.status_code}: {response.text[:240]}")
        return response.json()

    async def perform_light_action(self, device_id: str, action: str, step: int | None) -> dict[str, Any]:
        entity_id = self.entity_id_for_device(device_id)
        if action == "toggle":
            return await self.call_light_service(entity_id, "toggle")
        if action == "brightness":
            return await self.call_light_service(entity_id, "turn_on", {"brightness_step_pct": step or 0})
        if action == "color_temperature":
            state = await self.light_state(entity_id)
            attributes = state.get("attributes", {})
            minimum = int(attributes.get("min_color_temp_kelvin", 2200))
            maximum = int(attributes.get("max_color_temp_kelvin", 6500))
            current = attributes.get("color_temp_kelvin")
            if current is None and attributes.get("color_temp"):
                current = round(1_000_000 / attributes["color_temp"])
            current = int(current or round((minimum + maximum) / 2))
            target = max(minimum, min(maximum, current + (step or 0)))
            # Positive Kelvin is cooler. Joystick right maps to a positive step.
            return await self.call_light_service(entity_id, "turn_on", {"color_temp_kelvin": target})
        raise HomeAssistantError(f"Unsupported light action {action}")
