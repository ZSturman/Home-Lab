from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import paho.mqtt.client as mqtt

from .schemas import Envelope
from .settings import Settings

LOG = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def envelope(producer: str, payload: dict[str, Any], correlation_id: str | None = None) -> dict[str, Any]:
    return Envelope(
        producer=producer,
        occurred_at=utc_now(),
        correlation_id=correlation_id,
        payload=payload,
    ).model_dump(mode="json")


class MqttPublisher:
    def __init__(self, settings: Settings, client_id_suffix: str = "publisher") -> None:
        self.settings = settings
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"{settings.mqtt_client_id}-{client_id_suffix}",
            protocol=mqtt.MQTTv5,
        )
        self.client.username_pw_set(settings.mqtt_username, settings.mqtt_password_value)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.started = False
        self.connected = False
        self.pending: list[tuple[str, str, bool, int]] = []
        self.lock = threading.Lock()

    def _on_connect(self, _client: mqtt.Client, _userdata: object, _flags: object, reason: object, _properties: object) -> None:
        if getattr(reason, "is_failure", False):
            LOG.error("MQTT publisher connection failed: %s", reason)
            return
        with self.lock:
            self.connected = True
            pending, self.pending = self.pending, []
        for topic, encoded, retain, qos in pending:
            self._publish_encoded(topic, encoded, retain, qos)

    def _on_disconnect(self, _client: mqtt.Client, _userdata: object, _flags: object, _reason: object, _properties: object) -> None:
        with self.lock:
            self.connected = False

    def start(self) -> None:
        if self.started:
            return
        self.client.connect_async(self.settings.mqtt_host, self.settings.mqtt_port, keepalive=30)
        self.client.loop_start()
        self.started = True

    def stop(self) -> None:
        if self.started:
            self.client.loop_stop()
            self.client.disconnect()
            self.started = False
            self.connected = False

    def _publish_encoded(self, topic: str, encoded: str, retain: bool, qos: int) -> None:
        result = self.client.publish(topic, encoded, qos=qos, retain=retain)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            LOG.warning("MQTT publish queued with code %s for %s", result.rc, topic)
            with self.lock:
                self.pending.append((topic, encoded, retain, qos))

    def publish(self, topic: str, payload: dict[str, Any], *, retain: bool = False, qos: int = 1) -> None:
        encoded = json.dumps(payload, separators=(",", ":"))
        with self.lock:
            if not self.started or not self.connected:
                self.pending.append((topic, encoded, retain, qos))
                return
        self._publish_encoded(topic, encoded, retain, qos)

    def publish_event(
        self,
        topic: str,
        payload: dict[str, Any],
        *,
        retain: bool = False,
        qos: int = 1,
        correlation_id: str | None = None,
    ) -> None:
        self.publish(
            topic,
            envelope(self.settings.service_name, payload, correlation_id),
            retain=retain,
            qos=qos,
        )
