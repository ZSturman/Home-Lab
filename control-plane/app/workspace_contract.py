"""Client for the Workspace Sync & Backup Utility's storage-health contract.

Workspace Sync & Backup Utility owns everything about physical storage on
kiosk-lab: disks, UUID-based mounts, TEST/PENDING/PRODUCTION workspace
state, the backup HDD, Syncthing. This project (home-platform / Bidirectional
Project Hub) is a sibling on the same Pi, not that project's owner or a
dependency of it -- this module is the *only* place allowed to ask it
anything, and it must ask over HTTP (`GET /api/storage/contract`), never by
reading /dev, /etc/fstab, mount tables, or workspace_util's own config/state
files directly. See docs/project-hub.md and docs/kiosk-lab-platform.md.

Every call is best-effort and never raises: an unreachable or misbehaving
Workspace Sync Utility must degrade this project's view of storage to
"unknown", never crash a request or block Notion/project reconciliation
(see docs/project-hub.md's storage-failure-isolation requirement).
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from .settings import get_settings

logger = logging.getLogger(__name__)

UNKNOWN_CONTRACT: dict = {
    "mode": "unknown",
    "production_sync_safe": False,
    "workspace_disk_mounted": False,
    "workspace_root": None,
    "syncthing_workspace_folder": "unknown",
    "storage_health": "unknown",
    "storage_health_detail": "Workspace Sync Utility unreachable or not configured",
    "project_directory_creation_allowed": False,
    "detail": "Workspace Sync Utility unreachable or not configured",
}

UNKNOWN_STATUS: dict = {
    "storage": dict(UNKNOWN_CONTRACT),
    "backup": {
        "state": "unknown", "active": False, "stage": "waiting",
        "updated_at": None,
        "warning": "Workspace Sync Utility unreachable or not configured.",
    },
    "backup_destination": None,
}


def _backup_destination(status: dict) -> dict | None:
    """Extract backup-HDD facts, not the separate Workspace mirror mode."""
    storage = status.get("storage") if isinstance(status, dict) else None
    backup = storage.get("backup") if isinstance(storage, dict) else None
    if not isinstance(backup, dict) or not isinstance(backup.get("total"), int):
        return None
    checks = status.get("checks") if isinstance(status, dict) else []
    disk_check = next((check for check in checks if isinstance(check, dict) and "backup" in str(check.get("name", "")).lower() and "disk" in str(check.get("name", "")).lower()), None)
    return {
        "mounted": bool(disk_check and disk_check.get("status") == "ok"),
        "detail": disk_check.get("detail") if isinstance(disk_check, dict) else "Backup destination capacity reported",
        "used_bytes": backup.get("used"), "total_bytes": backup.get("total"),
        "available_bytes": backup.get("total") - backup.get("used", 0),
        "snapshots": (status.get("backup") or {}).get("snapshots") if isinstance(status.get("backup"), dict) else None,
        "last_snapshot_at": (status.get("backup") or {}).get("last") if isinstance(status.get("backup"), dict) else None,
    }


async def fetch_storage_contract() -> dict:
    """Best-effort fetch of the sibling project's storage contract. Always
    returns a dict shaped like UNKNOWN_CONTRACT on any failure -- callers
    should never need a try/except around this."""
    settings = get_settings()
    if not settings.workspace_contract_url:
        return dict(UNKNOWN_CONTRACT)
    headers = {}
    token = settings.workspace_contract_token_value
    if token:
        headers["X-Workspace-Token"] = token
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(settings.workspace_contract_url, headers=headers)
            r.raise_for_status()
            return r.json()
    except Exception as exc:  # noqa: BLE001 -- deliberately broad: any failure degrades, never propagates
        logger.warning("workspace storage contract unreachable: %s", exc)
        return {**UNKNOWN_CONTRACT, "detail": f"unreachable: {exc}", "storage_health_detail": f"unreachable: {exc}"}


async def fetch_workspace_status() -> dict:
    """Proxy the owning service's client-safe backup view without inspecting
    disks or state files locally. Kiosk and phone clients need no storage token.
    """
    settings = get_settings()
    if not settings.workspace_contract_url:
        return dict(UNKNOWN_STATUS)
    headers = {}
    if settings.workspace_contract_token_value:
        headers["X-Workspace-Token"] = settings.workspace_contract_token_value
    base_url = settings.workspace_contract_url.rsplit("/api/storage/contract", 1)[0]
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            storage_response, backup_response, status_response = await asyncio.gather(
                client.get(f"{base_url}/api/storage/contract", headers=headers),
                client.get(f"{base_url}/api/backup/status", headers=headers),
                client.get(f"{base_url}/api/status", headers=headers),
            )
            storage_response.raise_for_status()
            backup_response.raise_for_status()
            status_response.raise_for_status()
            return {"storage": storage_response.json(), "backup": backup_response.json(), "backup_destination": _backup_destination(status_response.json())}
    except Exception as exc:  # noqa: BLE001 -- storage failure must degrade
        logger.warning("workspace status unreachable: %s", exc)
        return {
            **UNKNOWN_STATUS,
            "storage": {**UNKNOWN_CONTRACT, "detail": f"unreachable: {exc}"},
            "backup": {**UNKNOWN_STATUS["backup"], "warning": f"unreachable: {exc}"},
        }


async def is_directory_creation_allowed_for_node(node_id: str) -> bool:
    """Whether `project.create_directory` may run for the given node right
    now, per the sibling project's contract.

    Deliberately a no-op (always True) for every node except this Pi's own
    control-plane node: today `workspace_node_id` is always the Mac
    ("macbook"), which has its own always-available real disk, so this
    check is structurally irrelevant to it. If a Pi-resident workspace node
    is ever added, its command handler for `project.create_directory` MUST
    call this before creating anything, and must leave the command queued
    (never fall back to writing under the Pi's SD-card test path) when it
    returns False -- see docs/kiosk-lab-platform.md, "Project creation
    while storage is unavailable"."""
    settings = get_settings()
    if node_id != settings.platform_node_id:
        return True
    contract = await fetch_storage_contract()
    return bool(contract.get("project_directory_creation_allowed"))
