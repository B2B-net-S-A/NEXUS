"""
InfraReporter integration service.
Fetches KPI data from https://infrareporter.onrender.com/api/kpi/board/monthly
and caches results for 1 hour.
"""

import asyncio
import logging
import time
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 3600  # 1 hour

# Simple in-memory cache
_cache: Dict[str, Any] = {
    "data": None,
    "fetched_at": 0.0,
}
_cache_lock = asyncio.Lock()


async def get_infrareporter_kpis() -> Optional[Dict[str, Any]]:
    """
    Fetch KPI data from InfraReporter API.
    Returns cached data if available and not expired.
    Returns None if fetch fails.
    """
    if not settings.INFRAREPORTER_API_KEY:
        logger.info("InfraReporter: disabled because API key is not configured")
        return None

    async with _cache_lock:
        now = time.time()
        if (
            _cache["data"] is not None
            and (now - _cache["fetched_at"]) < CACHE_TTL_SECONDS
        ):
            logger.debug("InfraReporter: returning cached data")
            return _cache["data"]

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    settings.INFRAREPORTER_URL,
                    headers={"X-Api-Key": settings.INFRAREPORTER_API_KEY},
                )
                response.raise_for_status()
                data = response.json()
                _cache["data"] = data
                _cache["fetched_at"] = now
                logger.info("InfraReporter: fetched fresh data")
                return data
        except httpx.HTTPStatusError as e:
            logger.warning(f"InfraReporter HTTP error: {e.response.status_code} — {e}")
        except httpx.RequestError as e:
            logger.warning(f"InfraReporter request error: {e}")
        except Exception as e:
            logger.error(f"InfraReporter unexpected error: {e}")

        # Return stale cache if available
        if _cache["data"] is not None:
            logger.info("InfraReporter: returning stale cache due to fetch error")
            return _cache["data"]

        return None


def invalidate_cache() -> None:
    """Force cache invalidation on next request."""
    _cache["data"] = None
    _cache["fetched_at"] = 0.0
