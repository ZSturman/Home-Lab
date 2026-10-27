"""Read-only Home Page v1 projection. No raw alert detail or provider secrets."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def summary(alerts: Iterable, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    items = []
    for alert in alerts:
        if alert.status != "active" or alert.kind == "success":
            continue
        priority = "critical" if alert.severity in {"critical", "error"} else "prompt" if alert.kind == "running" else "pending"
        items.append({
            "id": str(alert.id), "revision": _iso(alert.updated_at),
            "priority": priority, "title": alert.title[:200],
            "createdAt": _iso(min(alert.created_at.replace(tzinfo=timezone.utc) if alert.created_at.tzinfo is None else alert.created_at, now)),
            "expiresAt": _iso(now + timedelta(minutes=11)),
            "originID": f"home-lab/{alert.id}",
        })
    items.sort(key=lambda item: ({"critical": 0, "pending": 1, "prompt": 2}[item["priority"]], item["id"]))
    return {
        "schemaVersion": 1, "sourceID": "home-lab", "generatedAt": _iso(now),
        "expiresAt": _iso(now + timedelta(minutes=11)),
        "summary": f"{len(items)} active platform alerts" if items else "No active platform alerts",
        "state": "attention" if items else "normal", "items": items[:100],
    }
