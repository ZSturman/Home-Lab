"""Health reporting for private media services owned by the Platform."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from typing import Any

import httpx

from .mqtt import MqttPublisher
from .settings import get_settings
from .topics import service_health


LOG = logging.getLogger("homeplatform-media-controller")
SERVICE_ID = "brio-webcam"
STREAM_NAME = "brio"


def stream_health_payload(streams: Any) -> dict[str, Any]:
    """Build a non-sensitive health projection from go2rtc's stream list."""
    if not isinstance(streams, dict):
        return {"health": "degraded", "detail": "go2rtc returned an invalid stream list"}

    stream = streams.get(STREAM_NAME)
    if not isinstance(stream, dict):
        return {"health": "degraded", "detail": f"go2rtc stream {STREAM_NAME!r} is unavailable"}

    producers = stream.get("producers")
    if not isinstance(producers, list) or not producers:
        return {"health": "degraded", "detail": f"go2rtc stream {STREAM_NAME!r} has no producer"}

    return {
        "health": "healthy",
        "capabilities": {
            "private-media-stream": True,
            "protocols": ["snapshot", "rtsp", "webrtc"],
            "access": "tailnet-only",
        },
        "stream": STREAM_NAME,
        "producer_count": len(producers),
    }


class MediaController:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.node_id = self.settings.platform_node_id
        self.streams_url = os.environ.get("MEDIA_STREAMS_URL", "http://go2rtc:1984/api/streams")
        self.interval_seconds = float(os.environ.get("MEDIA_HEALTH_INTERVAL_SECONDS", "30"))
        self.publisher = MqttPublisher(self.settings, "media-controller")
        self.stopped = asyncio.Event()

    async def check(self, client: httpx.AsyncClient) -> dict[str, Any]:
        try:
            response = await client.get(self.streams_url)
            response.raise_for_status()
            return stream_health_payload(response.json())
        except (httpx.HTTPError, ValueError) as exc:
            LOG.warning("go2rtc health check failed: %s", exc)
            return {"health": "offline", "detail": f"go2rtc health check failed: {exc}"}

    async def run(self) -> None:
        self.publisher.start()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self.stopped.set)

        try:
            async with httpx.AsyncClient(timeout=5) as client:
                while not self.stopped.is_set():
                    payload = await self.check(client)
                    self.publisher.publish_event(
                        service_health(self.node_id, SERVICE_ID), payload, retain=True,
                    )
                    try:
                        await asyncio.wait_for(self.stopped.wait(), timeout=self.interval_seconds)
                    except TimeoutError:
                        pass
        finally:
            self.publisher.stop()


async def main() -> None:
    logging.basicConfig(
        level=os.environ.get("MEDIA_CONTROLLER_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    await MediaController().run()


if __name__ == "__main__":
    asyncio.run(main())
