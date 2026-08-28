from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from .alerts import active_alerts, create_alert, led_state
from .db import SessionLocal
from .models import AutomationRun, AutomationStage
from .mqtt import MqttPublisher
from .settings import get_settings
from .topics import ALERTS_CURRENT, BASE_TOPIC

LOG = logging.getLogger(__name__)


def now() -> datetime:
    return datetime.now(timezone.utc)


async def publish_attention(publisher: MqttPublisher) -> None:
    async with SessionLocal() as session:
        alerts = await active_alerts(session)
        publisher.publish_event(
            ALERTS_CURRENT,
            {
                "alerts": [{"id": item.id, "kind": item.kind, "severity": item.severity, "title": item.title} for item in alerts],
                "led": led_state(alerts),
            },
            retain=True,
        )


async def emit_run_event(publisher: MqttPublisher, run: AutomationRun, stage: str, status: str) -> None:
    publisher.publish_event(
        f"{BASE_TOPIC}/events/automation",
        {"run_id": run.id, "automation_id": run.automation_id, "stage": stage, "status": status},
        correlation_id=run.id,
    )


async def execute_safe_test(run_id: str, publisher: MqttPublisher) -> None:
    stage_names = ["Prepare safe test", "Verify event flow", "Complete safe test"]
    async with SessionLocal() as session:
        run = await session.get(AutomationRun, run_id)
        if not run or run.status != "queued":
            return
        run.status, run.started_at = "running", now()
        for position, name in enumerate(stage_names, start=1):
            session.add(AutomationStage(run_id=run.id, name=name, position=position))
        await create_alert(
            session, kind="running", severity="info", title="Safe Test Automation running",
            source_type="automation", source_id=run.id,
        )
        await session.commit()
        await emit_run_event(publisher, run, stage_names[0], "running")
    await publish_attention(publisher)

    for position, name in enumerate(stage_names, start=1):
        async with SessionLocal() as session:
            run = await session.get(AutomationRun, run_id)
            stage = await session.scalar(select(AutomationStage).where(
                AutomationStage.run_id == run_id, AutomationStage.position == position,
            ))
            if not run or not stage:
                return
            run.current_stage = name
            stage.status, stage.started_at = "running", now()
            await session.commit()
            await emit_run_event(publisher, run, name, "running")
        await asyncio.sleep(1)
        async with SessionLocal() as session:
            run = await session.get(AutomationRun, run_id)
            stage = await session.scalar(select(AutomationStage).where(
                AutomationStage.run_id == run_id, AutomationStage.position == position,
            ))
            if not run or not stage:
                return
            stage.status, stage.completed_at = "completed", now()
            if position == len(stage_names):
                run.status, run.completed_at, run.current_stage = "completed", now(), name
            await session.commit()
            await emit_run_event(publisher, run, name, "completed")

    async with SessionLocal() as session:
        active = await active_alerts(session)
        for alert in active:
            if alert.source_type == "automation" and alert.source_id == run_id and alert.kind == "running":
                alert.status = "resolved"
        await create_alert(
            session, kind="success", severity="success", title="Safe Test Automation completed",
            detail="The test Run completed without invoking external systems.",
            source_type="automation", source_id=run_id, dismissible=True,
        )
        await session.commit()
    await publish_attention(publisher)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    publisher = MqttPublisher(get_settings(), "automation-controller")
    publisher.start()
    try:
        while True:
            async with SessionLocal() as session:
                run = await session.scalar(select(AutomationRun).where(
                    AutomationRun.automation_id == "safe-test", AutomationRun.status == "queued",
                ).order_by(AutomationRun.created_at).limit(1))
            if run:
                await execute_safe_test(run.id, publisher)
            await asyncio.sleep(0.5)
    finally:
        publisher.stop()


if __name__ == "__main__":
    asyncio.run(main())
