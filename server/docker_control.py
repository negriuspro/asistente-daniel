import os
from typing import Any

import docker
from docker.errors import APIError, DockerException, NotFound
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import PlainTextResponse

router = APIRouter(prefix="/api/docker", tags=["docker"])

_ALLOWED_STATES = {"created", "restarting", "running", "removing", "paused", "exited", "dead"}
_DEFAULT_LOG_LINES = int(os.environ.get("DOCKER_LOG_LINES", "200"))


def _require_admin_token(x_jarvis_admin_token: str | None = Header(default=None)) -> None:
    expected = os.environ.get("JARVIS_ADMIN_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="Docker controls are disabled")
    if x_jarvis_admin_token != expected:
        raise HTTPException(status_code=403, detail="Invalid admin token")


def _client() -> docker.DockerClient:
    try:
        return docker.from_env()
    except DockerException as exc:
        raise HTTPException(status_code=503, detail="Docker Engine is not available") from exc


def _serialize_container(container: Any) -> dict[str, Any]:
    attrs = container.attrs
    state = attrs.get("State", {})
    return {
        "id": container.short_id,
        "name": container.name,
        "image": attrs.get("Config", {}).get("Image"),
        "status": container.status,
        "state": state.get("Status"),
        "running": bool(state.get("Running")),
        "created": attrs.get("Created"),
        "ports": attrs.get("NetworkSettings", {}).get("Ports") or {},
        "labels": attrs.get("Config", {}).get("Labels") or {},
    }


def _get_container(container_id: str):
    try:
        return _client().containers.get(container_id)
    except NotFound as exc:
        raise HTTPException(status_code=404, detail="Container not found") from exc
    except APIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/containers", dependencies=[Depends(_require_admin_token)])
def list_containers(state: str | None = Query(default=None)):
    if state and state not in _ALLOWED_STATES:
        raise HTTPException(status_code=400, detail="Unsupported container state filter")
    try:
        containers = _client().containers.list(all=True)
    except APIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    items = [_serialize_container(container) for container in containers]
    if state:
        items = [item for item in items if item["state"] == state]
    return {"containers": items}


@router.get("/containers/{container_id}", dependencies=[Depends(_require_admin_token)])
def inspect_container(container_id: str):
    return _serialize_container(_get_container(container_id))


@router.post("/containers/{container_id}/start", dependencies=[Depends(_require_admin_token)])
def start_container(container_id: str):
    container = _get_container(container_id)
    try:
        container.start()
        container.reload()
    except APIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _serialize_container(container)


@router.post("/containers/{container_id}/stop", dependencies=[Depends(_require_admin_token)])
def stop_container(container_id: str):
    container = _get_container(container_id)
    try:
        container.stop(timeout=int(os.environ.get("DOCKER_STOP_TIMEOUT", "10")))
        container.reload()
    except APIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _serialize_container(container)


@router.post("/containers/{container_id}/restart", dependencies=[Depends(_require_admin_token)])
def restart_container(container_id: str):
    container = _get_container(container_id)
    try:
        container.restart(timeout=int(os.environ.get("DOCKER_STOP_TIMEOUT", "10")))
        container.reload()
    except APIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _serialize_container(container)


@router.get("/containers/{container_id}/logs", response_class=PlainTextResponse, dependencies=[Depends(_require_admin_token)])
def container_logs(container_id: str, tail: int = Query(default=_DEFAULT_LOG_LINES, ge=1, le=2000)):
    container = _get_container(container_id)
    try:
        return container.logs(tail=tail, timestamps=True).decode("utf-8", errors="replace")
    except APIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/containers/{container_id}/metrics", dependencies=[Depends(_require_admin_token)])
def container_metrics(container_id: str):
    container = _get_container(container_id)
    try:
        stats = container.stats(stream=False)
    except APIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "id": container.short_id,
        "name": container.name,
        "cpu_stats": stats.get("cpu_stats", {}),
        "memory_stats": stats.get("memory_stats", {}),
        "networks": stats.get("networks", {}),
        "blkio_stats": stats.get("blkio_stats", {}),
    }
