"""
services/cache.py — Lightweight thread-safe in-memory TTL cache.

Used to avoid redundant API calls for identical city/budget queries
within the same server process lifetime.

Usage:
    from services.cache import api_cache

    result = api_cache.get("weather:london")
    if result is None:
        result = fetch_from_api(...)
        api_cache.set("weather:london", result, ttl=600)
"""

import time
import threading
import logging
from typing import Any

logger = logging.getLogger(__name__)


class TTLCache:
    """
    A dictionary-backed in-memory cache with per-entry TTL expiry.

    Thread-safe via a single RLock (reentrant so nested calls within the
    same thread don't deadlock). Uses lazy expiry — stale entries are
    only evicted on access, not by a background sweep thread.
    """

    def __init__(self, name: str = "cache") -> None:
        self._store: dict[str, tuple[Any, float]] = {}  # key → (value, expires_at)
        self._lock  = threading.RLock()
        self._name  = name

    def get(self, key: str) -> Any | None:
        """
        Return cached value for key, or None if missing/expired.
        Expired entries are evicted on access.
        """
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if time.monotonic() > expires_at:
                del self._store[key]
                logger.debug("[%s] MISS (expired) %s", self._name, key)
                return None
            logger.debug("[%s] HIT %s", self._name, key)
            return value

    def set(self, key: str, value: Any, ttl: int) -> None:
        """
        Store value under key with a TTL in seconds.
        ttl=0 disables caching for this entry.
        """
        if ttl <= 0:
            return
        with self._lock:
            self._store[key] = (value, time.monotonic() + ttl)
            logger.debug("[%s] SET %s (ttl=%ds)", self._name, key, ttl)

    def delete(self, key: str) -> None:
        """Manually invalidate a cache entry."""
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        """Flush all entries."""
        with self._lock:
            self._store.clear()
            logger.info("[%s] Cleared.", self._name)

    def stats(self) -> dict:
        """Return a snapshot of cache size (for health/debug endpoints)."""
        with self._lock:
            now = time.monotonic()
            total  = len(self._store)
            live   = sum(1 for _, exp in self._store.values() if exp > now)
            return {"name": self._name, "total_entries": total, "live_entries": live}


# Singleton instance shared across the whole application process
api_cache = TTLCache(name="api")
