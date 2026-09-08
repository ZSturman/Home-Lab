"""Safe, live projection of Tailscale's LocalAPI status.

The control plane is deliberately a *reader* of the local tailscaled socket.
It does not store or publish the raw response: that response contains node
keys, peer API URLs, and network endpoints which do not belong in a dashboard.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .settings import get_settings

logger = logging.getLogger(__name__)


def _friendly_name(item: dict) -> str:
    hostname = str(item.get("HostName") or "")
    dns_name = str(item.get("DNSName") or "").rstrip(".")
    # iOS commonly reports its local hostname as "localhost". The MagicDNS
    # label is a much more useful, stable dashboard name in that case.
    if hostname and hostname.lower() != "localhost":
        return hostname
    return dns_name.split(".", 1)[0] or hostname or "Unknown device"


def _timestamp(value: object) -> str | None:
    if not isinstance(value, str) or value.startswith("0001-01-01"):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def _transport(item: dict) -> str:
    if item.get("CurAddr"):
        return "direct"
    if item.get("Relay") or item.get("PeerRelay"):
        return "relay"
    return "unknown"


def _normalise_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _agent_for_device(item: dict, *, local: bool, agents: list[dict], platform_node_id: str) -> dict | None:
    """Match only an existing platform agent; tailnet presence never becomes
    a synthetic platform heartbeat. The local host maps to the configured
    platform node, while a non-local device needs an unambiguous name match.
    """
    if local:
        return next((agent for agent in agents if agent["id"] == platform_node_id), None)
    device_name = _normalise_name(_friendly_name(item))
    for agent in agents:
        candidate = _normalise_name(f"{agent['id']} {agent['name']}")
        display_name = _normalise_name(str(agent["name"]))
        if candidate and (candidate == device_name or candidate in device_name or device_name in candidate or display_name in device_name):
            return agent
    return None


def project_tailnet_status(raw: dict, *, agents: list[dict] | None = None, platform_node_id: str = "") -> dict:
    """Return an allowlisted tailnet model suitable for unauthenticated UI use.

    `raw` is intentionally accepted as a dict to keep all parser behaviour
    unit-testable with a small fixture rather than a real tailnet dependency.
    """
    agents = agents or []
    self_item = raw.get("Self") if isinstance(raw.get("Self"), dict) else {}
    peers = raw.get("Peer") if isinstance(raw.get("Peer"), dict) else {}
    records = [(self_item, True), *((item, False) for item in peers.values() if isinstance(item, dict))]
    devices = []
    for item, local in records:
        ips = [str(ip) for ip in item.get("TailscaleIPs", []) if isinstance(ip, str)]
        agent = _agent_for_device(item, local=local, agents=agents, platform_node_id=platform_node_id)
        devices.append({
            # Node ID is opaque but stable within this tailnet and safer than a
            # public key. It supports future capability associations.
            "id": str(item.get("NodeID") or item.get("ID") or _friendly_name(item)),
            "name": _friendly_name(item),
            "dns_name": str(item.get("DNSName") or "").rstrip(".") or None,
            "ips": ips,
            "online": bool(item.get("Online")),
            "last_seen_at": _timestamp(item.get("LastSeen")),
            "os": str(item.get("OS") or "unknown"),
            "local": local,
            "exit_node": bool(item.get("ExitNode")),
            "exit_node_option": bool(item.get("ExitNodeOption")),
            "subnet_routes": [str(route) for route in item.get("PrimaryRoutes", []) if isinstance(route, str)],
            "transport": _transport(item),
            "key_expiry": _timestamp(item.get("KeyExpiry")),
            "platform_agent": agent,
        })
    devices.sort(key=lambda device: (not device["local"], device["name"].lower()))
    health = [str(item) for item in raw.get("Health", []) if isinstance(item, str)]
    return {
        "state": str(raw.get("BackendState") or "unknown").lower(),
        "online": bool(self_item.get("Online")),
        "dns_name": str(self_item.get("DNSName") or "").rstrip(".") or None,
        "warnings": health,
        "devices": devices,
    }


async def fetch_tailnet_status(*, agents: list[dict] | None = None) -> dict:
    """Read tailscaled's Unix LocalAPI. Any failure is isolated from the
    dashboard, just like the sibling storage contract."""
    settings = get_settings()
    socket = settings.tailscale_local_api_socket
    if not socket or not Path(socket).exists():
        return {"state": "unavailable", "online": False, "dns_name": None, "warnings": ["Tailscale LocalAPI is unavailable."], "devices": []}
    try:
        transport = httpx.AsyncHTTPTransport(uds=str(socket))
        async with httpx.AsyncClient(transport=transport, timeout=5) as client:
            # local-tailscaled.sock is the host name required by LocalAPI.
            response = await client.get("http://local-tailscaled.sock/localapi/v0/status")
            response.raise_for_status()
            return project_tailnet_status(response.json(), agents=agents, platform_node_id=settings.platform_node_id)
    except Exception as exc:  # noqa: BLE001 -- telemetry must never break API availability
        logger.warning("tailscale LocalAPI unavailable: %s", exc)
        return {"state": "unavailable", "online": False, "dns_name": None, "warnings": [f"Tailscale LocalAPI unavailable: {exc}"], "devices": []}
