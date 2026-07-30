"""Operate the checked-in, local NEXUS client-portfolio manifest.

No Traffit client, configuration or data path is imported here.

Examples:

    python -m app.cli.client_portfolio_import --dry-run
    python -m app.cli.client_portfolio_import --apply-once
    python -m app.cli.client_portfolio_import --rollback 42
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from typing import Any

from app.core.database import AsyncSessionLocal
from app.services.client_portfolio_import import (
    ClientPortfolioImportError,
    apply_client_portfolio_manifest,
    build_client_portfolio_plan,
    rollback_client_portfolio_import,
)

logger = logging.getLogger(__name__)


def _print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


async def _run(*, dry_run: bool, apply_once: bool, rollback_run_id: int | None) -> int:
    async with AsyncSessionLocal() as db:
        try:
            if dry_run:
                plan = await build_client_portfolio_plan(db)
                _print(plan)
                return 2 if plan["blockers"] else 0

            if apply_once:
                result = await apply_client_portfolio_manifest(db)
                if result["status"] == "applied":
                    await db.commit()
                    _print(result)
                    return 0
                # ``already_applied`` is intentionally read-only. Rolling the
                # transaction back releases the transaction-scoped advisory
                # lock without producing a second audit record.
                if result["status"] == "already_applied":
                    await db.rollback()
                    _print(result)
                    return 0
                # A blocked/failed plan may have built an in-memory audit run,
                # but startup is fail-closed: no row or business-data mutation
                # survives when the process exits non-zero.
                await db.rollback()
                _print(result)
                if result["status"] == "blocked":
                    return 2
                return 1

            if rollback_run_id is not None:
                result = await rollback_client_portfolio_import(
                    db,
                    run_id=rollback_run_id,
                )
                await db.commit()
                _print(result)
                return 2 if result.get("conflicts") else 0
        except ClientPortfolioImportError as exc:
            await db.rollback()
            _print({"status": "failed", "error": str(exc)})
            return 2
        except Exception:
            await db.rollback()
            logger.exception("Client portfolio command failed")
            return 1

    return 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plan/apply/rollback the local NEXUS client portfolio"
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "--dry-run",
        action="store_true",
        help="build and print the plan; never write to the database",
    )
    action.add_argument(
        "--apply-once",
        action="store_true",
        help="apply the manifest atomically; an already-applied hash is a no-op",
    )
    action.add_argument(
        "--rollback",
        type=int,
        metavar="RUN_ID",
        help="non-destructively roll back one applied import run",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    code = asyncio.run(
        _run(
            dry_run=args.dry_run,
            apply_once=args.apply_once,
            rollback_run_id=args.rollback,
        )
    )
    sys.exit(code)


if __name__ == "__main__":
    main()
