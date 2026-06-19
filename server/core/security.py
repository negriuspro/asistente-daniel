from __future__ import annotations

import re

CONTAINER_ID_RE = re.compile(r"^[a-f0-9]{6,64}$")
ALLOWED_CONTAINER_ACTIONS = {"start", "stop", "restart"}


def validate_container_id(container_id: str) -> str:
    if not CONTAINER_ID_RE.match(container_id):
        raise ValueError("Invalid container id")
    return container_id


def validate_action(action: str) -> str:
    if action not in ALLOWED_CONTAINER_ACTIONS:
        raise ValueError("Action not allowed")
    return action
