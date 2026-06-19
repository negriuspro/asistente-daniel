from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger("daniel.cache")

_redis_client: aioredis.Redis | None = None
_redis_failed_at: float = 0.0
_REDIS_RETRY_COOLDOWN = 30.0  # segundos entre reintentos tras un fallo


class TTLCache:
    """Cache en memoria — usado como fallback si Redis no está disponible."""

    def __init__(self, default_ttl: float = 12.0) -> None:
        self._store: dict[str, tuple[Any, float]] = {}
        self._default_ttl = default_ttl

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        val, expires_at = entry
        if time.monotonic() > expires_at:
            del self._store[key]
            return None
        return val

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        self._store[key] = (value, time.monotonic() + (ttl or self._default_ttl))


_memory_cache = TTLCache(default_ttl=12.0)


async def get_redis() -> aioredis.Redis | None:
    """Reutiliza REDIS_URL — la misma instancia Redis que ya usa Daniel para conversaciones."""
    global _redis_client, _redis_failed_at
    if _redis_client is not None:
        return _redis_client
    if time.monotonic() - _redis_failed_at < _REDIS_RETRY_COOLDOWN:
        return None
    redis_url = os.environ.get("REDIS_URL", "")
    if not redis_url:
        return None
    try:
        client: aioredis.Redis = aioredis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        await client.ping()
        _redis_client = client
        _redis_failed_at = 0.0
        logger.info("Redis cache conectado en %s", redis_url)
        return _redis_client
    except Exception as exc:
        _redis_failed_at = time.monotonic()
        logger.warning("Redis no disponible, usando cache en memoria: %s", exc)
        return None


async def cache_get(key: str) -> Any | None:
    redis = await get_redis()
    if redis:
        try:
            raw = await redis.get(key)
            return json.loads(raw) if raw else None
        except Exception as exc:
            logger.debug("Redis cache_get falló para key=%r: %s", key, exc)
    return _memory_cache.get(key)


async def cache_set(key: str, value: Any, ttl: int = 12) -> None:
    redis = await get_redis()
    if redis:
        try:
            await redis.setex(key, ttl, json.dumps(value, default=str))
            return
        except Exception as exc:
            logger.debug("Redis cache_set falló para key=%r: %s", key, exc)
    _memory_cache.set(key, value, ttl=float(ttl))
