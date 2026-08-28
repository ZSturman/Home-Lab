from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import signal
from datetime import datetime

import paho.mqtt.client as mqtt
from sqlalchemy import select

from .configuration import load_configuration
from .db import SessionLocal
from .models import CommandRecord, DesiredStateRevision, EventRecord, NodeRecord, ServiceProviderRecord
from .mqtt import MqttPublisher
from .schemas import CommandResultPayload, Envelope, NodePresence
from .settings import get_settings
from .topics import BASE_TOPIC, desired_state

LOG = logging.getLogger(__name__)

COMMAND_STATUS_RANK = {
    "queued": 0,
    "accepted": 1,
    "running": 2,
    "completed": 3,
    "failed": 3,
    "unsupported": 3,
    "expired": 3,
}


class StateProjector:
    async def record_event(self, envelope: Envelope, kind: str) -> None:
        async with SessionLocal() as session:
            if await session.get(EventRecord, str(envelope.event_id)):
                return
            session.add(EventRecord(
                id=str(envelope.event_id),
                kind=kind,
                producer=envelope.producer,
                correlation_id=str(envelope.correlation_id) if envelope.correlation_id else None,
                occurred_at=envelope.occurred_at,
                payload=envelope.payload,
            ))
            await session.commit()

    async def project(self, topic: str, raw_payload: bytes) -> None:
        try:
            envelope = Envelope.model_validate_json(raw_payload)
        except Exception as exc:
            LOG.warning("Rejected invalid MQTT payload on %s: %s", topic, exc)
            return

        parts = topic.split("/")
        if parts[:2] != ["homeplatform", "v1"]:
            return
        await self.record_event(envelope, "/".join(parts[2:]))
        async with SessionLocal() as session:
            if len(parts) == 5 and parts[2] == "nodes":
                node_id, state_kind = parts[3], parts[4]
                node = await session.get(NodeRecord, node_id) or NodeRecord(id=node_id)
                if state_kind == "presence":
                    presence = NodePresence.model_validate(envelope.payload)
                    node.status = presence.status
                    node.health = presence.health
                    node.actual_state = {**node.actual_state, "hostname": presence.hostname, "os": presence.os}
                    node.last_seen_at = envelope.occurred_at
                elif state_kind == "actual-state":
                    # Presence and actual-state are separate retained MQTT
                    # messages. Preserve the hostname/OS projection from
                    # presence when the Node reports its local state next.
                    node.actual_state = {**node.actual_state, **envelope.payload}
                    node.last_seen_at = envelope.occurred_at
                elif state_kind == "capabilities":
                    node.capabilities = envelope.payload
                    node.last_seen_at = envelope.occurred_at
                else:
                    await session.commit()
                    return
                session.add(node)
            elif len(parts) == 6 and parts[2] == "services" and parts[5] == "health":
                node_id, service_id = parts[3], parts[4]
                node = await session.get(NodeRecord, node_id) or NodeRecord(id=node_id)
                session.add(node)
                provider_id = f"{node_id}:{service_id}"
                provider = await session.get(ServiceProviderRecord, provider_id) or ServiceProviderRecord(
                    id=provider_id, node_id=node_id, service_id=service_id,
                )
                provider.health = str(envelope.payload.get("health", "unknown"))
                provider.capabilities = envelope.payload.get("capabilities", {})
                provider.details = envelope.payload
                provider.last_seen_at = envelope.occurred_at
                session.add(provider)
            elif len(parts) == 5 and parts[2] == "commands" and parts[4] == "result":
                result = CommandResultPayload.model_validate(envelope.payload)
                # Serialize updates to this Command row. Without this lock a
                # quick QoS sequence (accepted → running → completed) can be
                # committed out of order by separate projector tasks.
                command = await session.scalar(
                    select(CommandRecord)
                    .where(CommandRecord.id == str(result.command_id))
                    .with_for_update()
                )
                if command:
                    # QoS delivery is ordered per client, but projections run
                    # asynchronously. Never permit an earlier progress update
                    # to overwrite a terminal Command result.
                    if COMMAND_STATUS_RANK.get(result.status, -1) >= COMMAND_STATUS_RANK.get(command.status, -1):
                        command.status = result.status
                        command.result = {"detail": result.detail, **result.result}
            await session.commit()


class MqttCore:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.project_lock: asyncio.Lock | None = None
        self.projector = StateProjector()
        self.publisher = MqttPublisher(self.settings, "core")
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"{self.settings.mqtt_client_id}-projector",
            protocol=mqtt.MQTTv5,
        )
        self.client.username_pw_set(self.settings.mqtt_username, self.settings.mqtt_password_value)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

    def on_connect(self, client: mqtt.Client, _userdata: object, _flags: object, reason: object, _properties: object) -> None:
        LOG.info("Connected to MQTT projector: %s", reason)
        for topic in (
            f"{BASE_TOPIC}/nodes/+/presence",
            f"{BASE_TOPIC}/nodes/+/actual-state",
            f"{BASE_TOPIC}/nodes/+/capabilities",
            f"{BASE_TOPIC}/services/+/+/health",
            f"{BASE_TOPIC}/commands/+/result",
            f"{BASE_TOPIC}/devices/#",
            f"{BASE_TOPIC}/events/#",
        ):
            client.subscribe(topic, qos=1)

    def on_message(self, _client: mqtt.Client, _userdata: object, message: mqtt.MQTTMessage) -> None:
        if self.loop:
            asyncio.run_coroutine_threadsafe(self.project_serialized(message.topic, message.payload), self.loop)

    async def project_serialized(self, topic: str, payload: bytes) -> None:
        if self.project_lock is None:
            await self.projector.project(topic, payload)
            return
        async with self.project_lock:
            await self.projector.project(topic, payload)

    async def publish_desired_state(self) -> None:
        config = load_configuration(self.settings.config_directory)
        payload = config.desired_state()
        checksum = config.checksum()
        async with SessionLocal() as session:
            for node_config in config.nodes:
                node = await session.get(NodeRecord, node_config.id)
                if not node:
                    session.add(NodeRecord(id=node_config.id, display_name=node_config.name))
                elif not node.display_name:
                    node.display_name = node_config.name
            latest = await session.scalar(
                select(DesiredStateRevision)
                .where(DesiredStateRevision.scope == "global")
                .order_by(DesiredStateRevision.revision.desc())
                .limit(1)
            )
            if latest and latest.checksum == checksum:
                revision = latest.revision
            else:
                revision = (latest.revision if latest else 0) + 1
                if latest:
                    latest.active = False
                session.add(DesiredStateRevision(
                    scope="global", revision=revision, checksum=checksum, payload=payload,
                ))
            await session.commit()
        self.publisher.publish_event(
            desired_state("global"),
            {"revision": revision, "checksum": checksum, "state": payload},
            retain=True,
        )

    async def run(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.project_lock = asyncio.Lock()
        self.publisher.start()
        self.client.connect_async(self.settings.mqtt_host, self.settings.mqtt_port, keepalive=30)
        self.client.loop_start()
        await self.publish_desired_state()
        stopped = asyncio.Event()
        for sig in (signal.SIGTERM, signal.SIGINT):
            self.loop.add_signal_handler(sig, stopped.set)
        await stopped.wait()
        self.client.loop_stop()
        self.client.disconnect()
        self.publisher.stop()


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    await MqttCore().run()


if __name__ == "__main__":
    asyncio.run(main())
