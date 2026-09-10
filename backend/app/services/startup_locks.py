"""Bounded lock waits for the schema safety nets that run before uvicorn.

`entrypoint.sh` runs under ``set -e`` and re-applies idempotent DDL on every
start. ``ADD COLUMN IF NOT EXISTS`` and friends request ACCESS EXCLUSIVE even
when there is nothing to add, so without a limit the start waits for as long
as anybody holds a conflicting lock — the nightly ``pg_dump`` holds ACCESS
SHARE on every table for the whole dump. And the waiting request is not
harmless: it sits in the lock queue in front of every later reader of that
table, so the container that is still serving traffic stalls with it.
"""

from __future__ import annotations

BOOT_LOCK_TIMEOUT = "10s"
_LOCK_NOT_AVAILABLE = "55P03"


def is_lock_timeout(exc: BaseException) -> bool:
    """True for PostgreSQL ``lock_not_available`` (lock_timeout, NOWAIT).

    SQLAlchemy wraps the driver error in ``DBAPIError.orig``; asyncpg's adapter
    exposes ``sqlstate`` there, psycopg ``pgcode``. The chain is walked too, so
    a wrapper that re-raises keeps being recognised.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        for candidate in (current, getattr(current, "orig", None)):
            code = getattr(candidate, "sqlstate", None) or getattr(
                candidate, "pgcode", None
            )
            if code == _LOCK_NOT_AVAILABLE:
                return True
        current = current.__cause__ or current.__context__
    return False
