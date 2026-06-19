from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from typing import Any

from fastapi import WebSocket


class WebSocketManager:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._rate_windows: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def connect(self, channel: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections[channel].add(websocket)

    async def disconnect(self, channel: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections[channel].discard(websocket)

    async def broadcast(self, channel: str, payload: dict[str, Any]) -> None:
        async with self._lock:
            targets = list(self._connections[channel])
        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections[channel].discard(ws)

    def allow_event(self, client_key: str, limit_per_minute: int) -> bool:
        now = time.time()
        window = self._rate_windows[client_key]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= limit_per_minute:
            return False
        window.append(now)
        return True
