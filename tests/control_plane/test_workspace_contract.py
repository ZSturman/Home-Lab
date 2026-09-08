from __future__ import annotations

import httpx
import pytest

from app.api import app, lifespan
from app.settings import get_settings
from app.workspace_contract import (
    UNKNOWN_CONTRACT,
    fetch_storage_contract,
    fetch_workspace_status,
    is_directory_creation_allowed_for_node,
)


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """Settings() is process-wide cached (@lru_cache) -- each test mutates
    env vars, so the cache must be dropped before and after or tests leak
    into each other (and into every other test module in the run)."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_fetch_storage_contract_degrades_when_url_not_configured(monkeypatch):
    monkeypatch.delenv("WORKSPACE_CONTRACT_URL", raising=False)
    result = await fetch_storage_contract()
    assert result["mode"] == "unknown"
    assert result["production_sync_safe"] is False


@pytest.mark.asyncio
async def test_fetch_workspace_status_degrades_when_url_not_configured(monkeypatch):
    monkeypatch.delenv("WORKSPACE_CONTRACT_URL", raising=False)
    result = await fetch_workspace_status()
    assert result["storage"]["mode"] == "unknown"
    assert result["backup"]["state"] == "unknown"


@pytest.mark.asyncio
async def test_fetch_storage_contract_degrades_on_unreachable_host(monkeypatch):
    """Storage failures must never crash this project -- this is the
    property behind "Storage failures do not crash Project Hub"."""
    monkeypatch.setenv("WORKSPACE_CONTRACT_URL", "http://127.0.0.1:1/api/storage/contract")
    result = await fetch_storage_contract()
    assert result["mode"] == "unknown"
    assert "unreachable" in result["detail"]


@pytest.mark.asyncio
async def test_fetch_storage_contract_returns_upstream_json(monkeypatch):
    monkeypatch.setenv("WORKSPACE_CONTRACT_URL", "http://workspace.example/api/storage/contract")

    async def fake_get(self, url, headers=None):
        assert url == "http://workspace.example/api/storage/contract"
        return httpx.Response(200, json={
            "mode": "production", "production_sync_safe": True, "workspace_disk_mounted": True,
            "workspace_root": "/mnt/workspace/Workspace", "syncthing_workspace_folder": "active",
            "storage_health": "ok", "storage_health_detail": "ok", "project_directory_creation_allowed": True,
            "detail": "ok",
        }, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    result = await fetch_storage_contract()
    assert result["mode"] == "production"
    assert result["project_directory_creation_allowed"] is True


@pytest.mark.asyncio
async def test_directory_creation_allowed_is_noop_for_non_pi_node(monkeypatch):
    """Today's real behavior: the Mac node ("macbook") always has its own
    real disk, so this check must never even call out to the contract for
    it -- see workspace_contract.py's docstring."""
    monkeypatch.delenv("WORKSPACE_CONTRACT_URL", raising=False)
    assert await is_directory_creation_allowed_for_node("macbook") is True


@pytest.mark.asyncio
async def test_directory_creation_allowed_gates_on_contract_for_pi_node(monkeypatch):
    monkeypatch.setenv("WORKSPACE_CONTRACT_URL", "http://workspace.example/api/storage/contract")

    async def fake_get(self, url, headers=None):
        return httpx.Response(200, json={**UNKNOWN_CONTRACT, "project_directory_creation_allowed": False},
                               request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    settings = get_settings()
    assert await is_directory_creation_allowed_for_node(settings.platform_node_id) is False


@pytest.mark.asyncio
async def test_storage_status_endpoint_never_errors_when_unconfigured(monkeypatch):
    monkeypatch.delenv("WORKSPACE_CONTRACT_URL", raising=False)
    async with lifespan(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            r = await ac.get("/api/v1/storage/status")
    assert r.status_code == 200
    assert r.json()["storage"]["mode"] == "unknown"
