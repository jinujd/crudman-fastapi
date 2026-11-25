"""Caching for list and details responses.

Keys are prefixed with the section name, so a write can invalidate only its own section
(crudman-nestjs flushes the whole cache).
"""

from __future__ import annotations

import json
import time
from collections import OrderedDict
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CacheAdapter(Protocol):
    async def get(self, key: str) -> Any | None: ...
    async def set(self, key: str, value: Any, ttl: int | None = None) -> None: ...
    async def invalidate_section(self, section: str) -> None: ...
    async def clear(self) -> None: ...


class MemoryCache:
    """In-process TTL cache with a size limit (oldest entries are evicted first)."""

    def __init__(self, ttl: int = 60, max_keys: int = 10_000) -> None:
        self.ttl = ttl
        self.max_keys = max_keys
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    async def get(self, key: str) -> Any | None:
        item = self._data.get(key)
        if item is None:
            return None
        expires, value = item
        if expires < time.monotonic():
            self._data.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        seconds = self.ttl if ttl is None else ttl
        self._data[key] = (time.monotonic() + seconds, value)
        self._data.move_to_end(key)
        while len(self._data) > self.max_keys:
            self._data.popitem(last=False)

    async def invalidate_section(self, section: str) -> None:
        prefix = f"{section}:"
        for key in [k for k in self._data if k.startswith(prefix)]:
            self._data.pop(key, None)

    async def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)


class RedisCache:
    """Redis-backed cache (``pip install "crudman-fastapi[redis]"``). Values are stored as JSON."""

    def __init__(self, url: str = "redis://localhost:6379/0", ttl: int = 60, namespace: str = "crudman") -> None:
        try:
            from redis import asyncio as redis_asyncio
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ImportError('RedisCache needs the redis extra: pip install "crudman-fastapi[redis]"') from exc
        self.ttl = ttl
        self.namespace = namespace
        self._client = redis_asyncio.from_url(url)

    def _key(self, key: str) -> str:
        return f"{self.namespace}:{key}"

    async def get(self, key: str) -> Any | None:  # pragma: no cover - needs a Redis server
        raw = await self._client.get(self._key(key))
        return None if raw is None else json.loads(raw)

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:  # pragma: no cover
        await self._client.set(self._key(key), json.dumps(value, default=str), ex=ttl or self.ttl)

    async def invalidate_section(self, section: str) -> None:  # pragma: no cover
        async for key in self._client.scan_iter(match=self._key(f"{section}:*")):
            await self._client.delete(key)

    async def clear(self) -> None:  # pragma: no cover
        async for key in self._client.scan_iter(match=self._key("*")):
            await self._client.delete(key)


def default_cache_key(section: str, action: str, params: Any, query: Any, relations: Any, identity: Any) -> str:
    payload = json.dumps(
        {"p": params, "q": sorted((str(k), str(v)) for k, v in dict(query).items()), "r": relations, "i": identity},
        sort_keys=True,
        default=str,
    )
    return f"{section}:{action}:{payload}"


__all__ = ["CacheAdapter", "MemoryCache", "RedisCache", "default_cache_key"]
