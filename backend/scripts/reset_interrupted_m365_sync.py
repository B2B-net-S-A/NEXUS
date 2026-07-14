"""Recover interrupted M365 data-state leases without changing schema."""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.core.database import engine


async def _reset() -> None:
    async with engine.begin() as connection:
        result = await connection.execute(
            text(
                "UPDATE m365_connections "
                "SET last_sync_status='idle', "
                "last_error=COALESCE(last_error, 'reset after container restart') "
                "WHERE last_sync_status='running'"
            )
        )
        print(f"interrupted M365 sync reset: rowcount={result.rowcount}")


if __name__ == "__main__":
    asyncio.run(_reset())
