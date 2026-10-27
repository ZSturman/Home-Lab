from __future__ import annotations

import httpx
import pytest
import pytest_asyncio

from app.api import app, lifespan
from app.models import AlertRecord, AutomationRun, AutomationStage, NodeRecord, ServiceProviderRecord


@pytest_asyncio.fixture
async def client():
    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            yield ac


@pytest.mark.asyncio
async def test_platform_overview_builds_an_explainable_priority_queue(client, session, monkeypatch) -> None:
    from app import api

    async def workspace_status() -> dict:
        return {"storage": {"mode": "test"}, "backup": {"state": "failed", "error": "No successful backup in 26 hours."}}

    monkeypatch.setattr(api, "fetch_workspace_status", workspace_status)
    monkeypatch.setattr(api, "registry_payload", lambda: {
        "nodes": [], "devices": [], "services": [], "automations": [], "integrations": [],
    })
    session.add(NodeRecord(id="macbook", display_name="MacBook", status="online", health="healthy"))
    session.add(ServiceProviderRecord(id="macbook/lmstudio", node_id="macbook", service_id="lmstudio", health="offline"))
    session.add(AlertRecord(id="alert-1", kind="security", severity="critical", title="Camera motion", detail="Motion while away."))
    session.add(AutomationRun(id="run-1", automation_id="nightly", status="failed", current_stage="upload"))
    await session.commit()

    response = await client.get("/api/v1/platform/overview")
    assert response.status_code == 200
    payload = response.json()
    assert payload["attention"][0]["title"] == "Camera motion"
    assert {item["target"] for item in payload["attention"]} >= {"attention", "system", "automations", "files"}
    assert payload["workspace"]["backup"]["state"] == "failed"
    assert "devices" in payload["registry"]


@pytest.mark.asyncio
async def test_stop_cancels_unfinished_stages_and_resolves_running_alert(client, session, monkeypatch) -> None:
    from types import SimpleNamespace
    from app import api

    monkeypatch.setattr(api, "load_configuration", lambda _: SimpleNamespace(
        automation=lambda _: SimpleNamespace(actions=["run", "stop"]),
    ))
    session.add(AutomationRun(id="stop-audit", automation_id="safe-test", status="running"))
    session.add_all([
        AutomationStage(run_id="stop-audit", name="Already done", position=1, status="completed"),
        AutomationStage(run_id="stop-audit", name="Active", position=2, status="running"),
        AutomationStage(run_id="stop-audit", name="Waiting", position=3, status="queued"),
        AlertRecord(id="stop-alert", kind="running", severity="info", title="Still running",
                    source_type="automation", source_id="stop-audit"),
    ])
    await session.commit()
    response = await client.post("/api/v1/automations/runs/stop-audit/stop")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    runs = (await client.get("/api/v1/automations/runs")).json()
    stopped = next(run for run in runs if run["id"] == "stop-audit")
    assert [stage["status"] for stage in stopped["stages"]] == ["completed", "cancelled", "cancelled"]
    assert not any(alert["source_id"] == "stop-audit" for alert in (await client.get("/api/v1/alerts")).json())
    retry = await client.post("/api/v1/automations/runs/stop-audit/stop")
    assert retry.status_code == 200
    assert retry.json()["completed_at"] == response.json()["completed_at"]
