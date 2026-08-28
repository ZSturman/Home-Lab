from __future__ import annotations

from dataclasses import dataclass

from .configuration import RouteConfig


@dataclass(frozen=True)
class ProviderAvailability:
    node_id: str
    service_id: str
    health: str


def resolve_route(route: RouteConfig, providers: list[ProviderAvailability]) -> ProviderAvailability | None:
    """Resolve only healthy configured providers; no hidden endpoint fallback."""
    by_identity = {(provider.node_id, provider.service_id): provider for provider in providers}
    for candidate in sorted(route.providers, key=lambda item: item.priority, reverse=True):
        provider = by_identity.get((candidate.node, candidate.service))
        if provider and provider.health == "healthy":
            return provider
    return None
