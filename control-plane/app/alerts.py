from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AlertRecord


def led_state(alerts: list[AlertRecord]) -> dict[str, dict[str, int | str]]:
    """Translate one canonical attention set into the kiosk LED frame."""
    frame = {
        color: {"mode": "off", "intervalMs": 500}
        for color in ("red", "blue", "green", "yellow")
    }
    kinds = {alert.kind for alert in alerts}
    severities = {alert.severity for alert in alerts}
    if "error" in severities:
        frame["red"] = {"mode": "solid", "intervalMs": 500}
    elif "public-active" in kinds:
        frame["blue"] = {"mode": "solid", "intervalMs": 500}
        frame["yellow"] = {"mode": "solid", "intervalMs": 500}
    elif "public" in kinds:
        frame["blue"] = {"mode": "solid", "intervalMs": 500}
    elif "running" in kinds:
        # Pin 43 is digital-only; this deliberately remains a calm pulse.
        frame["yellow"] = {"mode": "blink", "intervalMs": 1200}
    elif "success" in kinds:
        frame["green"] = {"mode": "solid", "intervalMs": 500}
    return frame


async def active_alerts(session: AsyncSession) -> list[AlertRecord]:
    result = await session.execute(
        select(AlertRecord)
        .where(AlertRecord.status == "active")
        .order_by(AlertRecord.created_at.desc())
    )
    return list(result.scalars())


async def create_alert(
    session: AsyncSession,
    *,
    kind: str,
    severity: str,
    title: str,
    detail: str = "",
    source_type: str = "platform",
    source_id: str | None = None,
    dismissible: bool = False,
    data: dict | None = None,
) -> AlertRecord:
    alert = AlertRecord(
        id=str(uuid4()),
        kind=kind,
        severity=severity,
        title=title,
        detail=detail,
        source_type=source_type,
        source_id=source_id,
        dismissible=dismissible,
        data=data or {},
    )
    session.add(alert)
    return alert


def alert_payload(alert: AlertRecord) -> dict:
    return {
        "id": alert.id,
        "kind": alert.kind,
        "severity": alert.severity,
        "status": alert.status,
        "title": alert.title,
        "detail": alert.detail,
        "source_type": alert.source_type,
        "source_id": alert.source_id,
        "dismissible": alert.dismissible,
        "data": alert.data,
        "created_at": alert.created_at.isoformat(),
        "updated_at": alert.updated_at.isoformat(),
    }
