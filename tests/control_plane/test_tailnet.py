from __future__ import annotations

from app.tailnet import project_tailnet_status


def test_tailnet_projection_allowlists_live_device_fields_and_agent_is_independent():
    raw = {
        "BackendState": "Running",
        "Health": ["System DNS config not ideal"],
        "Self": {
            "NodeID": 1, "HostName": "kiosk-lab", "DNSName": "kiosk-lab.example.ts.net.",
            "TailscaleIPs": ["100.90.61.70", "fd7a::1"], "OS": "linux", "Online": True,
            "CurAddr": "10.0.0.235:41641", "ExitNode": False, "ExitNodeOption": False,
        },
        "Peer": {
            "unsafe-public-key": {
                "NodeID": 2, "HostName": "localhost", "DNSName": "ipad-pro.example.ts.net.",
                "TailscaleIPs": ["100.73.144.109"], "OS": "iOS", "Online": True,
                "Relay": "sea", "LastSeen": "0001-01-01T00:00:00Z", "PublicKey": "must-not-leak",
                "PeerAPIURL": ["http://100.0.0.1"], "Addrs": ["198.51.100.1:41641"],
            },
            "offline": {
                "NodeID": 3, "HostName": "Zachary's MacBook Pro", "DNSName": "mac.example.ts.net.",
                "TailscaleIPs": ["100.84.135.118"], "OS": "macOS", "Online": False,
                "LastSeen": "2026-09-08T18:00:00Z", "KeyExpiry": "2027-02-13T00:00:00Z",
            },
        },
    }
    projected = project_tailnet_status(raw, agents=[
        {"id": "pi-control-plane", "name": "Home Pi", "status": "offline", "health": "unknown", "last_seen_at": None},
        {"id": "macbook", "name": "MacBook", "status": "online", "health": "ok", "last_seen_at": "2026-09-08T18:00:00+00:00"},
    ], platform_node_id="pi-control-plane")

    assert projected["state"] == "running"
    assert projected["warnings"] == ["System DNS config not ideal"]
    pi, ipad, mac = projected["devices"]
    assert pi["local"] is True and pi["online"] is True
    # An offline application heartbeat remains visible as separate, non-tailnet state.
    assert pi["platform_agent"]["status"] == "offline"
    assert ipad["name"] == "ipad-pro" and ipad["transport"] == "relay"
    assert ipad["last_seen_at"] is None and ipad["platform_agent"] is None
    assert mac["online"] is False and mac["last_seen_at"] == "2026-09-08T18:00:00+00:00"
    assert mac["platform_agent"]["id"] == "macbook"
    assert "PublicKey" not in str(projected) and "PeerAPIURL" not in str(projected) and "198.51.100.1" not in str(projected)
