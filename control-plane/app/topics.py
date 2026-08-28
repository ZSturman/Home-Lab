from __future__ import annotations

BASE_TOPIC = "homeplatform/v1"


def node_presence(node_id: str) -> str:
    return f"{BASE_TOPIC}/nodes/{node_id}/presence"


def node_actual_state(node_id: str) -> str:
    return f"{BASE_TOPIC}/nodes/{node_id}/actual-state"


def node_capabilities(node_id: str) -> str:
    return f"{BASE_TOPIC}/nodes/{node_id}/capabilities"


def service_health(node_id: str, service_id: str) -> str:
    return f"{BASE_TOPIC}/services/{node_id}/{service_id}/health"


def command_request(node_id: str) -> str:
    return f"{BASE_TOPIC}/commands/{node_id}/request"


def command_result(node_id: str) -> str:
    return f"{BASE_TOPIC}/commands/{node_id}/result"


def desired_state(scope: str) -> str:
    return f"{BASE_TOPIC}/config/desired-state/{scope}"


ALERTS_CURRENT = f"{BASE_TOPIC}/alerts/current"
