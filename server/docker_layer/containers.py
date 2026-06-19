from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from docker.models.containers import Container

from ..core.security import validate_action, validate_container_id
from .client import get_docker_client


def uptime_seconds(container: Container) -> int | None:
    started = container.attrs.get("State", {}).get("StartedAt")
    if not started:
        return None
    try:
        dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
        return max(0, int((datetime.now(timezone.utc) - dt).total_seconds()))
    except ValueError:
        return None


def _project_name(container: Container, name: str) -> str:
    labels = container.attrs.get("Config", {}).get("Labels") or {}
    project = labels.get("com.docker.compose.project")
    if project:
        return project
    return name.split("-")[0].split("_")[0]


def list_containers() -> list[dict[str, Any]]:
    client = get_docker_client()
    containers = client.containers.list(all=True)
    results: list[dict[str, Any]] = []
    for container in containers:
        attrs = container.attrs
        name = (attrs.get("Name") or container.name).lstrip("/")
        results.append(
            {
                "id": container.id[:12],
                "name": name,
                "project": _project_name(container, name),
                "image": attrs.get("Config", {}).get("Image", ""),
                "status": attrs.get("State", {}).get("Status", container.status),
                "state": attrs.get("State", {}).get("Status"),
                "created_at": attrs.get("Created"),
                "uptime_seconds": uptime_seconds(container),
                "restart_count": attrs.get("RestartCount", 0),
            }
        )
    return results


def inspect_container(container_id: str) -> dict[str, Any]:
    validate_container_id(container_id)
    return get_docker_client().containers.get(container_id).attrs


def perform_action(container_id: str, action: str) -> dict[str, Any]:
    validate_container_id(container_id)
    validate_action(action)
    container = get_docker_client().containers.get(container_id)
    if action == "start":
        container.start()
    elif action == "stop":
        container.stop()
    elif action == "restart":
        container.restart()
    return {"id": container.id[:12], "action": action, "status": "ok"}
