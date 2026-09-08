from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "control-plane"))

from app.alerts import led_state
from app.configuration import load_configuration
from app.core import COMMAND_STATUS_RANK
from app.registry import ProviderAvailability, resolve_route
from app.schemas import Envelope


ROOT = Path(__file__).resolve().parents[2]


class ConfigurationTests(unittest.TestCase):
    def test_configuration_loads_and_preserves_route_priority(self) -> None:
        configuration = load_configuration(ROOT / "config")
        self.assertEqual(configuration.devices[0].entity_id, "light.living_room_living_room")
        self.assertEqual(configuration.routes[0].providers[0].node, "macbook")
        self.assertEqual(len(configuration.checksum()), 64)

    def test_automation_registry_exposes_safe_metadata_and_validates_arguments(self) -> None:
        automation = load_configuration(ROOT / "config").automation("safe-test")
        self.assertIsNotNone(automation)
        self.assertEqual(automation.runner if automation else None, "control-plane")
        self.assertIn("stop", automation.actions if automation else [])
        self.assertEqual(automation.validate_arguments({}) if automation else None, {})

    def test_automation_registry_rejects_unknown_arguments(self) -> None:
        automation = load_configuration(ROOT / "config").automation("safe-test")
        with self.assertRaises(ValueError):
            automation.validate_arguments({"unsafe-shell": "rm -rf"})  # type: ignore[union-attr]

    def test_priority_failover_requires_health(self) -> None:
        route = load_configuration(ROOT / "config").routes[0]
        self.assertIsNone(resolve_route(route, [ProviderAvailability("macbook", "lmstudio", "offline")]))
        selected = resolve_route(route, [ProviderAvailability("macbook", "lmstudio", "healthy")])
        self.assertEqual(selected.node_id if selected else None, "macbook")


class AlertTests(unittest.TestCase):
    def test_led_priority_is_deterministic(self) -> None:
        class Alert:
            def __init__(self, kind: str, severity: str) -> None:
                self.kind, self.severity = kind, severity

        self.assertEqual(led_state([])["green"]["mode"], "off")
        self.assertEqual(led_state([Alert("running", "info")])["yellow"]["mode"], "blink")
        public = led_state([Alert("public-active", "info")])
        self.assertEqual((public["blue"]["mode"], public["yellow"]["mode"]), ("solid", "solid"))
        self.assertEqual(led_state([Alert("public", "error")])["red"]["mode"], "solid")


class SchemaTests(unittest.TestCase):
    def test_envelope_requires_versioned_payload(self) -> None:
        envelope = Envelope.model_validate({
            "schema_version": 1,
            "event_id": "18d38b0d-ae85-49c4-a23f-1b6c9a5d94b4",
            "producer": "test",
            "occurred_at": "2026-08-26T17:00:00Z",
            "payload": {"status": "online"},
        })
        self.assertEqual(envelope.schema_version, 1)

    def test_terminal_command_result_cannot_regress_to_progress(self) -> None:
        self.assertGreater(COMMAND_STATUS_RANK["completed"], COMMAND_STATUS_RANK["running"])
        self.assertEqual(COMMAND_STATUS_RANK["failed"], COMMAND_STATUS_RANK["completed"])


if __name__ == "__main__":
    unittest.main()
