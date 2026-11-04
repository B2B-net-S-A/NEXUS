#!/usr/bin/env python3
"""Field-level promotion CLI. Data and credentials never belong in arguments."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.services import staging_data_promotion as promotion


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument(
        "--list-recipes",
        action="store_true",
        help="Show reviewed recipe scope without connecting to a database",
    )
    commands = result.add_subparsers(dest="command", required=False)
    for name in ("snapshot", "package", "preview", "apply"):
        command = commands.add_parser(name)
        command.add_argument(
            "--source-url-env"
            if name in {"snapshot", "package"}
            else "--target-url-env",
            required=True,
            help="Name of an existing environment variable; never the database URL itself",
        )
        if name == "snapshot":
            command.add_argument("--selection", required=True)
        elif name == "package":
            command.add_argument("--baseline", required=True)
        else:
            command.add_argument("--package", required=True)
            command.add_argument("--actor-id", type=int, required=True)
        if name == "apply":
            command.add_argument("--preview", required=True)
            command.add_argument("--approve-digest", required=True)
        else:
            command.add_argument("--out", required=True)
    return result


async def run(args: argparse.Namespace) -> dict:
    source = args.command in {"snapshot", "package"}
    env_name = args.source_url_env if source else args.target_url_env
    if not env_name.isidentifier() or not os.environ.get(env_name):
        raise promotion.PromotionError("database_url_environment_variable_missing")
    try:
        url = make_url(os.environ[env_name])
    except Exception as exc:
        raise promotion.PromotionError("invalid_database_url") from exc
    if url.drivername != "postgresql+asyncpg":
        raise promotion.PromotionError("postgresql_asyncpg_required")
    if source:
        promotion.validate_source_url(url)
    engine = create_async_engine(url, echo=False, hide_parameters=True)
    try:
        async with engine.connect() as conn:
            if args.command != "apply":
                # A consistent, database-enforced read-only snapshot across all
                # selected rows. Apply uses its own separate writable transaction.
                await conn.execute(
                    text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                )
            if args.command == "snapshot":
                artifact = await promotion.snapshot(
                    conn, promotion.read_artifact(args.selection)
                )
            elif args.command == "package":
                artifact = await promotion.package(
                    conn, promotion.read_artifact(args.baseline)
                )
            elif args.command == "preview":
                artifact = await promotion.preview(
                    conn, promotion.read_artifact(args.package), actor_id=args.actor_id
                )
            else:
                return await promotion.apply(
                    conn,
                    promotion.read_artifact(args.package),
                    promotion.read_artifact(args.preview),
                    args.approve_digest,
                    actor_id=args.actor_id,
                )
            promotion.write_artifact(args.out, artifact)
            return {
                "kind": artifact["kind"],
                "digest": artifact["digest"],
                "package_digest": artifact.get("package_digest"),
                "records": len(
                    artifact.get(
                        "records", artifact.get("changes", artifact.get("states", []))
                    )
                ),
                "conflicts": len(artifact.get("conflicts", [])),
            }
    finally:
        await engine.dispose()


def main() -> int:
    argument_parser = parser()
    args = argument_parser.parse_args()
    if args.list_recipes:
        if args.command:
            argument_parser.error("--list-recipes cannot be combined with an operation")
        print(
            json.dumps(
                {"ok": True, "recipes": promotion.list_recipes()}, sort_keys=True
            )
        )
        return 0
    if not args.command:
        argument_parser.error("an operation or --list-recipes is required")
    try:
        result = asyncio.run(run(args))
    except promotion.PromotionError as exc:
        print(json.dumps({"ok": False, "code": str(exc)}))
        return 2
    except Exception:
        # Connection/driver/PG errors may embed URL credentials or row data.
        print(json.dumps({"ok": False, "code": "database_or_io_operation_failed"}))
        return 2
    print(json.dumps({"ok": True, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
