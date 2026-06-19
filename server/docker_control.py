"""
docker_control.py — Interfaz pública de control Docker para Daniel Core.

Responsabilidad de este archivo (y SOLO esto):
  - auth (single source of truth para el token admin)
  - validación de entrada HTTP (tipos, query params)
  - respuestas HTTP / WebSocket (routing)

Todo lo demás (cliente Docker, cálculos de métricas, cache, validación de dominio,
alertas, lógica de canales WS) vive en docker_layer/, core/ y realtime/ — este
archivo delega, no implementa. Si esto empieza a crecer con cálculos o lógica de
Docker SDK, esa lógica está en el lugar equivocado.
"""

from __future__ import annotations

import asyncio
import logging
import os

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import PlainTextResponse

from .docker_layer.aggregates import get_batch_metrics, get_container_alerts
from .docker_layer.containers import inspect_container, list_containers, perform_action
from .docker_layer.images import list_images
from .docker_layer.logs import get_container_logs
from .docker_layer.metrics import get_container_metrics
from .docker_layer.networks import list_networks
from .realtime.manager import WebSocketManager

log = logging.getLogger("daniel.docker_control")

router = APIRouter(prefix="/api/docker", tags=["docker"])

# Convención de WebSockets de dominio: /ws/<dominio> (docker, system, agents, memory...)
ws_router = APIRouter(tags=["docker-ws"])
_ws_manager = WebSocketManager()

# ─── Auth — única política de permisos para control Docker ───────────────────

_INSECURE_DEFAULTS = {
    "", "changeme", "change_me", "secret", "password", "admin",
    "cambia-este-token-secreto", "cambia_esto", "cambia_esto_por_una_clave_segura",
}


def require_admin_token(x_daniel_admin_token: str | None = Header(default=None)) -> None:
    expected = os.environ.get("DANIEL_ADMIN_TOKEN", "")
    if expected.strip().lower() in _INSECURE_DEFAULTS:
        log.error("[AUTH] DANIEL_ADMIN_TOKEN no configurado o inseguro — bloqueando control Docker")
        raise HTTPException(status_code=503, detail="Server misconfigured: set a secure DANIEL_ADMIN_TOKEN")
    if not x_daniel_admin_token or x_daniel_admin_token != expected:
        raise HTTPException(status_code=403, detail="Invalid admin token")


# ─── REST — contenedores ───────────────────────────────────────────────────────


@router.get("/containers", dependencies=[Depends(require_admin_token)])
async def http_list_containers() -> list[dict]:
    try:
        return await asyncio.to_thread(list_containers)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Docker no disponible: {exc}") from exc


@router.get("/containers/{container_id}", dependencies=[Depends(require_admin_token)])
async def http_get_container(container_id: str) -> dict:
    try:
        return await asyncio.to_thread(inspect_container, container_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/containers/{container_id}/{action}", dependencies=[Depends(require_admin_token)])
async def http_container_action(container_id: str, action: str, request: Request) -> dict:
    caller_ip = request.client.host if request.client else "unknown"
    log.info(
        "[AUDIT] container_action caller=%s container=%s action=%s",
        caller_ip, container_id, action,
    )
    try:
        return await asyncio.to_thread(perform_action, container_id, action)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/containers/{container_id}/logs",
    response_class=PlainTextResponse,
    dependencies=[Depends(require_admin_token)],
)
async def http_container_logs(container_id: str, tail: int = Query(default=200, ge=1, le=2000)) -> str:
    try:
        return await asyncio.to_thread(get_container_logs, container_id, tail)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/containers/{container_id}/metrics", dependencies=[Depends(require_admin_token)])
async def http_container_metrics(container_id: str) -> dict:
    try:
        return await asyncio.to_thread(get_container_metrics, container_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ─── REST — imágenes / redes ────────────────────────────────────────────────────


@router.get("/images", dependencies=[Depends(require_admin_token)])
async def http_list_images() -> list[dict]:
    try:
        return await asyncio.to_thread(list_images)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Docker no disponible: {exc}") from exc


@router.get("/networks", dependencies=[Depends(require_admin_token)])
async def http_list_networks() -> list[dict]:
    try:
        return await asyncio.to_thread(list_networks)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Docker no disponible: {exc}") from exc


# ─── REST — métricas batch / alertas (cálculo real en docker_layer.aggregates) ─


@router.get("/metrics/all", dependencies=[Depends(require_admin_token)])
async def http_batch_metrics() -> dict:
    try:
        return await get_batch_metrics()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Docker no disponible: {exc}") from exc


@router.get("/metrics/alerts", dependencies=[Depends(require_admin_token)])
async def http_container_alerts() -> dict:
    try:
        return await get_container_alerts()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Docker no disponible: {exc}") from exc


# ─── WebSocket — /ws/docker (convención de dominio para futuros /ws/system, etc.) ─


@ws_router.websocket("/ws/docker")
async def docker_ws(websocket: WebSocket):
    """
    Snapshot inicial + comandos on-demand:
      "snapshot"                → lista de contenedores actual
      "metrics:{container_id}"  → métricas puntuales de un contenedor
    Rate-limit: 60 mensajes/minuto por IP (delegado a realtime.manager).
    """
    channel = "docker"
    await _ws_manager.connect(channel, websocket)
    client_ip = websocket.client.host if websocket.client else "unknown"
    try:
        snapshot = await asyncio.to_thread(list_containers)
        await websocket.send_json({"type": "snapshot", "containers": snapshot})

        while True:
            msg = await websocket.receive_text()
            if not _ws_manager.allow_event(client_ip, limit_per_minute=60):
                await websocket.send_json({"type": "error", "detail": "rate limit exceeded"})
                continue

            if msg == "snapshot":
                snapshot = await asyncio.to_thread(list_containers)
                await websocket.send_json({"type": "snapshot", "containers": snapshot})
            elif msg.startswith("metrics:"):
                cid = msg.split(":", 1)[1]
                try:
                    metrics = await asyncio.to_thread(get_container_metrics, cid)
                    await websocket.send_json({"type": "metrics", "data": metrics})
                except Exception as exc:
                    await websocket.send_json({"type": "error", "detail": str(exc)})
    except WebSocketDisconnect:
        pass
    finally:
        await _ws_manager.disconnect(channel, websocket)
