from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .alerts import active_alerts, alert_payload, led_state
from .db import get_session
from .home_assistant import HomeAssistantClient, HomeAssistantError
from .models import AlertRecord, AutomationRun, AutomationStage, CommandRecord, NodeRecord, ServiceProviderRecord
from .mqtt import MqttPublisher
from .configuration import load_configuration
from .registry import ProviderAvailability, resolve_route
from .schemas import CommandRequest, CreateAutomationRun, LightActionRequest
from .settings import get_settings
from .topics import ALERTS_CURRENT, command_request


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def node_payload(record: NodeRecord) -> dict:
    return {
        "id": record.id,
        "name": record.display_name or record.id,
        "status": record.status,
        "health": record.health,
        "actual_state": record.actual_state,
        "capabilities": record.capabilities,
        "last_seen_at": record.last_seen_at.isoformat() if record.last_seen_at else None,
    }


def provider_payload(record: ServiceProviderRecord) -> dict:
    return {
        "id": record.id,
        "node_id": record.node_id,
        "service_id": record.service_id,
        "health": record.health,
        "capabilities": record.capabilities,
        "details": record.details,
        "last_seen_at": record.last_seen_at.isoformat() if record.last_seen_at else None,
    }


def command_payload(record: CommandRecord) -> dict:
    return {
        "id": record.id,
        "node_id": record.node_id,
        "command_type": record.command_type,
        "status": record.status,
        "payload": record.payload,
        "result": record.result,
        "expires_at": record.expires_at.isoformat(),
        "created_at": record.created_at.isoformat(),
    }


def run_payload(record: AutomationRun, stages: list[AutomationStage] | None = None) -> dict:
    return {
        "id": record.id,
        "automation_id": record.automation_id,
        "trigger": record.trigger,
        "status": record.status,
        "current_stage": record.current_stage,
        "started_at": record.started_at.isoformat() if record.started_at else None,
        "completed_at": record.completed_at.isoformat() if record.completed_at else None,
        "stages": [
            {"name": stage.name, "position": stage.position, "status": stage.status, "detail": stage.detail}
            for stage in (stages or [])
        ],
    }


async def snapshot(session: AsyncSession) -> dict:
    settings = get_settings()
    nodes = list((await session.execute(select(NodeRecord).order_by(NodeRecord.id))).scalars())
    providers = list((await session.execute(select(ServiceProviderRecord).order_by(ServiceProviderRecord.id))).scalars())
    alerts = await active_alerts(session)
    runs = list((await session.execute(
        select(AutomationRun).order_by(AutomationRun.created_at.desc()).limit(10)
    )).scalars())
    run_payloads = []
    for run in runs:
        stages = list((await session.execute(
            select(AutomationStage)
            .where(AutomationStage.run_id == run.id)
            .order_by(AutomationStage.position)
        )).scalars())
        run_payloads.append(run_payload(run, stages))
    return {
        "runtime": {
            "node_id": settings.platform_node_id,
            "node_name": settings.platform_node_name,
            "hardware_profile": settings.platform_hardware_profile,
        },
        "nodes": [node_payload(item) for item in nodes],
        "providers": [provider_payload(item) for item in providers],
        "alerts": [alert_payload(item) for item in alerts],
        "led": led_state(alerts),
        "runs": run_payloads,
    }


async def publish_attention(app: FastAPI, session: AsyncSession) -> None:
    alerts = await active_alerts(session)
    app.state.publisher.publish_event(
        ALERTS_CURRENT,
        {
            "alerts": [{"id": item.id, "kind": item.kind, "severity": item.severity, "title": item.title} for item in alerts],
            "led": led_state(alerts),
        },
        retain=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    publisher = MqttPublisher(get_settings(), "api")
    publisher.start()
    app.state.publisher = publisher
    yield
    publisher.stop()


app = FastAPI(title="Home Platform Control Plane", version="1.0.0", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "healthy"}


@app.get("/api/v1/system/snapshot")
async def get_snapshot(session: AsyncSession = Depends(get_session)) -> dict:
    return await snapshot(session)


@app.get("/api/v1/nodes")
async def get_nodes(session: AsyncSession = Depends(get_session)) -> list[dict]:
    records = list((await session.execute(select(NodeRecord).order_by(NodeRecord.id))).scalars())
    return [node_payload(record) for record in records]


@app.get("/api/v1/services/providers")
async def get_providers(session: AsyncSession = Depends(get_session)) -> list[dict]:
    records = list((await session.execute(select(ServiceProviderRecord).order_by(ServiceProviderRecord.id))).scalars())
    return [provider_payload(record) for record in records]


@app.get("/api/v1/routes")
async def get_routes(session: AsyncSession = Depends(get_session)) -> list[dict]:
    records = list((await session.execute(select(ServiceProviderRecord))).scalars())
    available = [ProviderAvailability(item.node_id, item.service_id, item.health) for item in records]
    config = load_configuration(get_settings().config_directory)
    return [
        {
            "capability": route.capability,
            "strategy": route.strategy,
            "active_provider": (
                {"node_id": selected.node_id, "service_id": selected.service_id}
                if (selected := resolve_route(route, available)) else None
            ),
        }
        for route in config.routes
    ]


@app.get("/api/v1/alerts")
async def get_alerts(session: AsyncSession = Depends(get_session)) -> list[dict]:
    return [alert_payload(record) for record in await active_alerts(session)]


@app.post("/api/v1/alerts/{alert_id}/dismiss")
async def dismiss_alert(alert_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    alert = await session.get(AlertRecord, alert_id)
    if not alert or alert.status != "active":
        raise HTTPException(status_code=404, detail="Active alert not found")
    if not alert.dismissible:
        raise HTTPException(status_code=409, detail="This alert is resolved by fixing its source")
    alert.status, alert.dismissed_at = "dismissed", utc_now()
    await session.commit()
    await publish_attention(app, session)
    return alert_payload(alert)


@app.post("/api/v1/commands", status_code=202)
async def create_command(request: CommandRequest, session: AsyncSession = Depends(get_session)) -> dict:
    command = CommandRecord(
        id=str(uuid4()),
        node_id=request.node_id,
        command_type=request.command_type,
        payload=request.payload,
        status="queued",
        expires_at=utc_now() + timedelta(seconds=request.expires_in_seconds),
    )
    session.add(command)
    await session.commit()
    app.state.publisher.publish_event(
        command_request(command.node_id),
        {
            "command_id": command.id,
            "command_type": command.command_type,
            "payload": command.payload,
            "expires_at": command.expires_at.isoformat(),
        },
        correlation_id=command.id,
    )
    return command_payload(command)


@app.get("/api/v1/commands/{command_id}")
async def get_command(command_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    command = await session.get(CommandRecord, command_id)
    if not command:
        raise HTTPException(status_code=404, detail="Command not found")
    return command_payload(command)


@app.post("/api/v1/automations/safe-test/runs", status_code=202)
async def create_safe_test_run(
    request: CreateAutomationRun,
    session: AsyncSession = Depends(get_session),
) -> dict:
    run = AutomationRun(id=str(uuid4()), automation_id="safe-test", trigger=request.trigger)
    session.add(run)
    await session.commit()
    return run_payload(run)


@app.get("/api/v1/automations/runs")
async def list_runs(session: AsyncSession = Depends(get_session)) -> list[dict]:
    records = list((await session.execute(
        select(AutomationRun).order_by(AutomationRun.created_at.desc()).limit(50)
    )).scalars())
    result = []
    for record in records:
        stages = list((await session.execute(
            select(AutomationStage).where(AutomationStage.run_id == record.id).order_by(AutomationStage.position)
        )).scalars())
        result.append(run_payload(record, stages))
    return result


@app.post("/api/v1/devices/{device_id}/light-action")
async def light_action(
    device_id: str,
    request: LightActionRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    try:
        result = await HomeAssistantClient(get_settings()).perform_light_action(device_id, request.action, request.step)
    except HomeAssistantError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "completed", "result": result}


@app.websocket("/api/v1/live")
async def live_updates(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            # A fresh dependency-free session keeps the stream alive across API requests.
            from .db import SessionLocal
            async with SessionLocal() as session:
                await websocket.send_json({"type": "system.snapshot", "data": await snapshot(session)})
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        return
