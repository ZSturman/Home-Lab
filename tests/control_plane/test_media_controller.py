from __future__ import annotations

import unittest

from app.media_controller import stream_health_payload


class StreamHealthPayloadTests(unittest.TestCase):
    def test_healthy_when_brio_has_a_producer(self) -> None:
        payload = stream_health_payload({"brio": {"producers": [{"url": "redacted"}]}})

        self.assertEqual(payload["health"], "healthy")
        self.assertEqual(payload["producer_count"], 1)
        self.assertEqual(payload["capabilities"]["access"], "tailnet-only")

    def test_degraded_when_brio_is_missing(self) -> None:
        payload = stream_health_payload({})

        self.assertEqual(payload["health"], "degraded")
        self.assertIn("unavailable", payload["detail"])

    def test_degraded_when_brio_has_no_producer(self) -> None:
        payload = stream_health_payload({"brio": {"producers": []}})

        self.assertEqual(payload["health"], "degraded")
        self.assertIn("no producer", payload["detail"])
