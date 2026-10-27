from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from app.homepage import summary


def alert(**overrides):
    values = dict(id="test-alert", status="active", kind="security", severity="error", title="Camera unavailable",
                  detail="PRIVATE: never exported", updated_at=datetime(2026, 10, 25), created_at=datetime(2026, 10, 24))
    return SimpleNamespace(**(values | overrides))


def test_summary_keeps_identity_excludes_success_and_never_exports_details():
    now = datetime(2026, 10, 25, tzinfo=timezone.utc)
    result = summary([alert(), alert(id="success", kind="success"), alert(id="dismissed", status="dismissed")], now=now)
    assert result["sourceID"] == "home-lab"
    assert len(result["items"]) == 1
    assert result["items"][0]["priority"] == "critical"
    assert result["items"][0]["revision"].endswith("+00:00")
    assert "PRIVATE" not in str(result)
    assert summary([], now=now)["summary"] == "No active platform alerts"


@pytest.mark.asyncio
async def test_endpoint_is_a_read_only_projection(monkeypatch):
    from app import api
    from app.db import get_session
    async def fake_alerts(session):
        return [alert()]
    async def fake_session():
        yield object()
    monkeypatch.setattr(api, "active_alerts", fake_alerts)
    api.app.dependency_overrides[get_session] = fake_session
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://testserver") as client:
            response = await client.get("/api/v1/home-page")
        assert response.status_code == 200
        assert response.json()["sourceID"] == "home-lab"
    finally:
        api.app.dependency_overrides.pop(get_session, None)
