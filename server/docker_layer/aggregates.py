"""
aggregates.py — Cálculos batch sobre el dominio Docker (métricas + alertas).

Vive aquí, no en docker_control.py: cálculos, cache y orquestación de Docker SDK
son responsabilidad del Docker Layer, no de la fachada HTTP.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from ..core.cache import cache_get, cache_set
from ..system_monitor import get_server_metrics
from .client import get_docker_client
from .metrics import get_container_metrics

_METRICS_TTL = 12
_ALERTS_TTL = 30


async def _safe_metrics(container_id: str) -> dict[str, Any] | None:
    try:
        return await asyncio.to_thread(get_container_metrics, container_id)
    except Exception:
        return None


async def get_batch_metrics() -> dict[str, Any]:
    """Host + métricas de todos los contenedores corriendo en una sola llamada, cacheado."""
    cache_key = "docker:metrics:all"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    client = get_docker_client()
    containers_raw, host = await asyncio.gather(
        asyncio.to_thread(lambda: client.containers.list(all=True)),
        asyncio.to_thread(get_server_metrics),
    )

    running = [c for c in containers_raw if c.status == "running"]
    running_ids = [c.id[:12] for c in running]
    metrics_list = list(await asyncio.gather(*[_safe_metrics(cid) for cid in running_ids]))
    metrics_map = {cid: m for cid, m in zip(running_ids, metrics_list) if m is not None}

    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "host": host,
        "containers_running": len(running),
        "containers_total": len(containers_raw),
        "metrics": metrics_map,
    }
    await cache_set(cache_key, result, ttl=_METRICS_TTL)
    return result


async def get_container_alerts() -> dict[str, Any]:
    """Detecta contenedores con reinicios excesivos, crashes o healthcheck fallando."""
    cache_key = "docker:metrics:alerts"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    client = get_docker_client()
    containers = await asyncio.to_thread(lambda: client.containers.list(all=True))

    alerts: list[dict[str, Any]] = []
    for c in containers:
        name = c.name.lstrip("/")
        restart_count = c.attrs.get("RestartCount", 0)
        state = c.attrs.get("State", {})
        health = state.get("Health", {}).get("Status", "none")
        status = state.get("Status", c.status)
        exit_code = state.get("ExitCode", 0)

        if restart_count >= 3:
            alerts.append({
                "container": name,
                "severity": "warning" if restart_count < 10 else "critical",
                "type": "high_restart_count",
                "detail": f"Reinicios: {restart_count}",
            })
        if status == "exited" and exit_code != 0:
            alerts.append({
                "container": name,
                "severity": "error",
                "type": "crashed",
                "detail": f"Terminado con exit code {exit_code}",
            })
        if health == "unhealthy":
            alerts.append({
                "container": name,
                "severity": "critical",
                "type": "unhealthy",
                "detail": "Docker healthcheck fallando",
            })

    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "alert_count": len(alerts),
        "alerts": alerts,
    }
    await cache_set(cache_key, result, ttl=_ALERTS_TTL)
    return result
