"""Cache backend (Redis in deployment, in-process for tests / single-node dev).

Every key the platform writes is namespaced by tenant and, for retrieval and
answer caches, by the caller's permission fingerprint and the tenant's content
epoch (bumped on any document / ACL change), so cached results can never be
served across tenants or across differing permissions (FR-108, extension 3).
"""
from __future__ import annotations

import json
import threading
import time
from functools import lru_cache
from typing import Any, Protocol

from app.core.config import get_settings


class CacheBackend(Protocol):
    def get(self, key: str) -> Any | None: ...
    def set(self, key: str, value: Any, ttl: int) -> None: ...
    def incr(self, key: str, ttl: int) -> int: ...
    def delete_prefix(self, prefix: str) -> int: ...
    def ping(self) -> bool: ...


class MemoryCache:
    def __init__(self) -> None:
        self._data: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            item = self._data.get(key)
            if not item:
                return None
            if item[0] < time.time():
                self._data.pop(key, None)
                return None
            return item[1]

    def set(self, key: str, value: Any, ttl: int) -> None:
        with self._lock:
            self._data[key] = (time.time() + ttl, value)

    def incr(self, key: str, ttl: int) -> int:
        with self._lock:
            exp, val = self._data.get(key, (time.time() + ttl, 0))
            if exp < time.time():
                exp, val = time.time() + ttl, 0
            val += 1
            self._data[key] = (exp, val)
            return val

    def delete_prefix(self, prefix: str) -> int:
        with self._lock:
            keys = [k for k in self._data if k.startswith(prefix)]
            for k in keys:
                del self._data[k]
            return len(keys)

    def ping(self) -> bool:
        return True


class RedisCache:
    def __init__(self, url: str) -> None:
        import redis

        self._r = redis.Redis.from_url(url, socket_timeout=2, socket_connect_timeout=2)

    def get(self, key: str) -> Any | None:
        raw = self._r.get(key)
        return json.loads(raw) if raw is not None else None

    def set(self, key: str, value: Any, ttl: int) -> None:
        self._r.set(key, json.dumps(value, default=str), ex=ttl)

    def incr(self, key: str, ttl: int) -> int:
        pipe = self._r.pipeline()
        pipe.incr(key)
        pipe.expire(key, ttl, nx=True)
        return int(pipe.execute()[0])

    def delete_prefix(self, prefix: str) -> int:
        n = 0
        for key in self._r.scan_iter(match=prefix + "*", count=500):
            self._r.delete(key)
            n += 1
        return n

    def ping(self) -> bool:
        try:
            return bool(self._r.ping())
        except Exception:
            return False


@lru_cache
def get_cache() -> CacheBackend:
    s = get_settings()
    if s.cache_backend == "memory":
        return MemoryCache()
    return RedisCache(s.redis_url)
