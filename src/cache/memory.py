"""In-memory cache with TTL support.

Provides a simple LRU-style cache with automatic expiration.
"""

import time
from typing import TypeVar, Generic, Optional, Dict, Any
from dataclasses import dataclass, field
from threading import Lock
import logging


logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class CacheEntry(Generic[T]):
    """A single cache entry with TTL."""

    value: T
    timestamp: float = field(default_factory=time.time)
    ttl_seconds: int = 3600

    def is_expired(self) -> bool:
        """Check if entry has expired."""
        return time.time() - self.timestamp > self.ttl_seconds


class MemoryCache(Generic[T]):
    """Thread-safe in-memory cache with TTL support."""

    def __init__(self, max_size: int = 1000, default_ttl: int = 3600):
        """Initialize cache.

        Args:
            max_size: Maximum number of entries before eviction
            default_ttl: Default TTL in seconds for new entries
        """
        self._cache: Dict[str, CacheEntry[T]] = {}
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._lock = Lock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[T]:
        """Retrieve value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None if missing/expired
        """
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None

            entry = self._cache[key]
            if entry.is_expired():
                del self._cache[key]
                self._misses += 1
                logger.debug(f"Cache entry expired: {key}")
                return None

            self._hits += 1
            return entry.value

    def set(self, key: str, value: T, ttl: Optional[int] = None) -> None:
        """Store value in cache.

        Args:
            key: Cache key
            value: Value to cache
            ttl: TTL in seconds (uses default if not specified)
        """
        with self._lock:
            if len(self._cache) >= self._max_size:
                # Simple eviction: remove oldest entry
                oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k].timestamp)
                del self._cache[oldest_key]
                logger.debug(f"Cache full, evicted: {oldest_key}")

            ttl_seconds = ttl if ttl is not None else self._default_ttl
            self._cache[key] = CacheEntry(value=value, ttl_seconds=ttl_seconds)
            logger.debug(f"Cached: {key} (TTL: {ttl_seconds}s)")

    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
            logger.info("Cache cleared")

    def remove_expired(self) -> int:
        """Remove all expired entries.

        Returns:
            Number of entries removed
        """
        with self._lock:
            expired_keys = [k for k, v in self._cache.items() if v.is_expired()]
            for key in expired_keys:
                del self._cache[key]
            logger.debug(f"Removed {len(expired_keys)} expired entries")
            return len(expired_keys)

    def stats(self) -> Dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with cache stats
        """
        total_requests = self._hits + self._misses
        hit_rate = self._hits / total_requests if total_requests > 0 else 0.0

        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "hits": self._hits,
            "misses": self._misses,
            "total_requests": total_requests,
            "hit_rate": hit_rate,
        }

    def __len__(self) -> int:
        """Return current cache size."""
        return len(self._cache)

    def __contains__(self, key: str) -> bool:
        """Check if key exists in cache (and is not expired)."""
        if key not in self._cache:
            return False
        return not self._cache[key].is_expired()
