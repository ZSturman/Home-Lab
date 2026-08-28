from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.settings import Settings


class RuntimeIdentityTests(unittest.TestCase):
    def test_host_identity_is_configurable(self) -> None:
        settings = Settings(
            platform_node_id="macbook",
            platform_node_name="Zachary's MacBook Pro",
            platform_hardware_profile="standard",
        )

        self.assertEqual(settings.platform_node_id, "macbook")
        self.assertEqual(settings.platform_node_name, "Zachary's MacBook Pro")
        self.assertEqual(settings.platform_hardware_profile, "standard")

    def test_rejects_unsafe_node_id(self) -> None:
        with self.assertRaises(ValueError):
            Settings(platform_node_id="Pi Control Plane")

    def test_documented_environment_variable_names_are_used(self) -> None:
        with patch.dict(os.environ, {
            "HOMEPLATFORM_NODE_ID": "macbook",
            "HOMEPLATFORM_NODE_NAME": "Zachary's MacBook Pro",
            "HOMEPLATFORM_HARDWARE_PROFILE": "standard",
        }, clear=True):
            settings = Settings(_env_file=None)

        self.assertEqual(settings.platform_node_id, "macbook")
        self.assertEqual(settings.platform_node_name, "Zachary's MacBook Pro")
        self.assertEqual(settings.platform_hardware_profile, "standard")
