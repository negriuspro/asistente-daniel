from __future__ import annotations

from typing import Any

from .client import get_docker_client


def list_images() -> list[dict[str, Any]]:
    client = get_docker_client()
    results: list[dict[str, Any]] = []
    for image in client.images.list():
        tags = image.tags or [image.id]
        results.append(
            {
                "id": image.id[:12],
                "tags": tags,
                "short_id": image.short_id,
                "created": image.attrs.get("Created"),
                "size": image.attrs.get("Size", 0),
            }
        )
    return results
