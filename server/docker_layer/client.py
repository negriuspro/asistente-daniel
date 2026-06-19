from __future__ import annotations

import logging
import os

import docker
from docker.client import DockerClient

logger = logging.getLogger("daniel.docker_layer")

_client: DockerClient | None = None


def get_docker_client() -> DockerClient:
    global _client
    if _client is None:
        base_url = os.environ.get("DOCKER_HOST", "unix:///var/run/docker.sock")
        _client = docker.DockerClient(base_url=base_url)
    return _client


def ping_docker() -> bool:
    try:
        return bool(get_docker_client().ping())
    except Exception as exc:
        logger.debug("Docker ping falló (socket-proxy inalcanzable?): %s", exc)
        return False
