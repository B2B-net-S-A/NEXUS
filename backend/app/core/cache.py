"""
Simple in-memory TTL cache for heavy API endpoints.
No external dependencies required — uses plain dict + timestamps.
"""
import time
import asyncio
from typing import Any, Callable, Dict, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

# Global cache store: key → (value, expires_at)
_cache: Dict[str, Tuple[Any, float]] = {}
_lock = asyncio.Lock()


def _make_key(prefix: str, *args, **kwargs) -> str:
    """Build a deterministic cache key."""
    parts = [prefix]
    parts.extend(str(a) for a in args)
    parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
    return ":".join(parts)


async def cache_get(key: str) -> Optional[Any]:
    """Return cached value if not expired, else None."""
    async with _lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.monotonic() > expires_at:
            del _cache[key]
            return None
        return value


async def cache_set(key: str, value: Any, ttl_seconds: int):
    """Store value in cache with TTL."""
    async with _lock:
        _cache[key] = (value, time.monotonic() + ttl_seconds)


async def cache_invalidate(prefix: str):
    """Invalidate all keys starting with prefix."""
    async with _lock:
        keys_to_delete = [k for k in _cache if k.startswith(prefix)]
        for k in keys_to_delete:
            del _cache[k]
    logger.debug(f"Cache invalidated: {prefix} ({len(keys_to_delete)} keys)")


def cached(ttl_seconds: int, key_prefix: str):
    """
    Decorator for async endpoint functions.
    Caches the return value for ttl_seconds.
    The cache key includes all function arguments.
    
    Usage:
        @cached(ttl_seconds=120, key_prefix="dashboard_kpis")
        async def get_kpis(current_user, db):
            ...
    """
    def decorator(func: Callable):
        async def wrapper(*args, **kwargs):
            # Build cache key from kwargs that are simple scalars
            cache_kwargs = {
                k: v for k, v in kwargs.items()
                if isinstance(v, (str, int, float, bool, type(None)))
            }
            key = _make_key(key_prefix, **cache_kwargs)
            
            cached_value = await cache_get(key)
            if cached_value is not None:
                logger.debug(f"Cache HIT: {key}")
                return cached_value
            
            logger.debug(f"Cache MISS: {key}")
            result = await func(*args, **kwargs)
            await cache_set(key, result, ttl_seconds)
            return result
        
        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper
    return decorator
