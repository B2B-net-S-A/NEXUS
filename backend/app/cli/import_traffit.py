"""CLI: jednorazowa migracja Traffit → Nexus (clients + contacts).

Uruchomienie:
    python -m app.cli.import_traffit --phase clients
    python -m app.cli.import_traffit --phase contacts
    python -m app.cli.import_traffit --phase clients,contacts
    python -m app.cli.import_traffit --phase reconcile
    python -m app.cli.import_traffit --phase clients,contacts --dry-run

Sekrety w env (Coolify env vault, NIE w repo):
    TRAFFIT_TENANT, TRAFFIT_CLIENT_ID, TRAFFIT_CLIENT_SECRET
    TRAFFIT_THROTTLE_RPS (opcjonalnie, default 5).
Wartości — patrz docs/traffit-discovery.md.

Idempotent — drugi run = 0 inserts, N updates.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from typing import Iterable

from app.core.database import AsyncSessionLocal
from app.services.traffit.client import TraffitClient, TraffitConfig
from app.services.traffit.importer import TraffitImporter

logger = logging.getLogger(__name__)


VALID_PHASES = {"clients", "contacts", "reconcile"}


def _parse_phases(arg: str) -> list[str]:
    phases = [p.strip() for p in arg.split(",") if p.strip()]
    invalid = [p for p in phases if p not in VALID_PHASES]
    if invalid:
        raise argparse.ArgumentTypeError(
            f"Unknown phase(s): {invalid}. Valid: {sorted(VALID_PHASES)}"
        )
    return phases


async def _run(phases: Iterable[str], *, dry_run: bool, batch_size: int) -> int:
    config = TraffitConfig.from_env()
    exit_code = 0

    async with TraffitClient(config) as traffit:
        async with AsyncSessionLocal() as db:
            importer = TraffitImporter(
                traffit, db, dry_run=dry_run, batch_size=batch_size
            )
            for phase in phases:
                if phase == "clients":
                    progress = await importer.import_clients()
                    print(json.dumps(progress.as_dict(), default=str, indent=2))
                    if progress.errors:
                        exit_code = 1
                elif phase == "contacts":
                    progress = await importer.import_contacts()
                    print(json.dumps(progress.as_dict(), default=str, indent=2))
                    if progress.errors:
                        exit_code = 1
                elif phase == "reconcile":
                    report = await importer.reconcile()
                    print(json.dumps(report, indent=2))
                    if not report["clients"]["match"] or not report["contacts"]["match"]:
                        exit_code = 2  # mismatch — non-fatal but actionable
    return exit_code


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Traffit → Nexus migration CLI (clients + contacts)"
    )
    parser.add_argument(
        "--phase",
        type=_parse_phases,
        required=True,
        help="comma-separated: clients,contacts,reconcile",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="don't write to DB; just count and validate mappings",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="X-Request-Page-Size dla Traffit API (default 200)",
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
        _run(args.phase, dry_run=args.dry_run, batch_size=args.batch_size)
    )
    sys.exit(code)


if __name__ == "__main__":
    main()
