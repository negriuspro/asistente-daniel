from __future__ import annotations

from typing import Iterator

from ..core.security import validate_container_id
from .client import get_docker_client

MAX_LOG_BYTES = 512_000


def get_container_logs(container_id: str, tail: int = 200) -> str:
    validate_container_id(container_id)
    container = get_docker_client().containers.get(container_id)
    logs = container.logs(tail=tail, timestamps=True, stdout=True, stderr=True)
    if isinstance(logs, bytes):
        return logs[:MAX_LOG_BYTES].decode("utf-8", errors="replace")
    return str(logs)[:MAX_LOG_BYTES]


def stream_container_logs(container_id: str) -> Iterator[str]:
    validate_container_id(container_id)
    container = get_docker_client().containers.get(container_id)
    for chunk in container.logs(stream=True, follow=True, timestamps=True, stdout=True, stderr=True):
        yield chunk.decode("utf-8", errors="replace") if isinstance(chunk, bytes) else str(chunk)
