from __future__ import annotations

from typing import Any

from .client import get_docker_client


def list_networks() -> list[dict[str, Any]]:
    client = get_docker_client()
    results: list[dict[str, Any]] = []
    for network in client.networks.list():
        attrs = network.attrs
        results.append(
            {
                "id": network.id[:12],
                "name": attrs.get("Name", network.name),
                "driver": attrs.get("Driver"),
                "scope": attrs.get("Scope"),
                "internal": attrs.get("Internal", False),
                "attachable": attrs.get("Attachable", False),
                "containers": len(attrs.get("Containers", {}) or {}),
            }
        )
    return results
