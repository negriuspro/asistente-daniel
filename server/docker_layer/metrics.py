from __future__ import annotations

from typing import Any

from ..core.security import validate_container_id
from .client import get_docker_client
from .containers import uptime_seconds


def _safe_percent(current: float, limit: float) -> float:
    if limit <= 0:
        return 0.0
    return round((current / limit) * 100.0, 2)


def _calc_cpu(stats: dict) -> float:
    cu = stats.get("cpu_stats", {}).get("cpu_usage", {})
    pc = stats.get("precpu_stats", {}).get("cpu_usage", {})
    cpu_total = float(cu.get("total_usage", 0))
    precpu_total = float(pc.get("total_usage", 0))
    system_cpu = float(stats.get("cpu_stats", {}).get("system_cpu_usage", 0))
    presystem_cpu = float(stats.get("precpu_stats", {}).get("system_cpu_usage", 0))
    cpu_delta = cpu_total - precpu_total
    system_delta = system_cpu - presystem_cpu
    online_cpus = float(stats.get("cpu_stats", {}).get("online_cpus", 1))
    if system_delta > 0 and cpu_delta > 0:
        return round((cpu_delta / system_delta) * online_cpus * 100.0, 4)
    return 0.0


def get_container_metrics(container_id: str) -> dict[str, Any]:
    validate_container_id(container_id)
    container = get_docker_client().containers.get(container_id)
    stats = container.stats(stream=False)

    cpu_percent = _calc_cpu(stats)

    memory_usage = int(stats.get("memory_stats", {}).get("usage", 0))
    memory_limit = int(stats.get("memory_stats", {}).get("limit", 0))
    memory_percent = _safe_percent(memory_usage, memory_limit)

    net_rx = 0
    net_tx = 0
    for iface in stats.get("networks", {}).values():
        net_rx += int(iface.get("rx_bytes", 0))
        net_tx += int(iface.get("tx_bytes", 0))

    block_read = 0
    block_write = 0
    for blk in stats.get("blkio_stats", {}).get("io_service_bytes_recursive", []) or []:
        op = blk.get("op", "")
        val = int(blk.get("value", 0))
        if op.lower() == "read":
            block_read += val
        elif op.lower() == "write":
            block_write += val

    return {
        "id": container.id[:12],
        "cpu_percent": cpu_percent,
        "memory_usage_bytes": memory_usage,
        "memory_limit_bytes": memory_limit,
        "memory_percent": memory_percent,
        "network_rx_bytes": net_rx,
        "network_tx_bytes": net_tx,
        "block_read_bytes": block_read,
        "block_write_bytes": block_write,
        "status": stats.get("name", container.status),
        "uptime_seconds": uptime_seconds(container),
        "restart_count": container.attrs.get("RestartCount", 0),
    }
