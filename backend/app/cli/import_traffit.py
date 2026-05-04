"""CLI: jednorazowa migracja Traffit → Nexus.

Phases (uruchamiać w tej kolejności przy pierwszej migracji):
    1. workflows           — Traffit workflows → pipeline_templates + stage_defs
    2. clients             — /clients/ → clients
    3. contacts            — /crm_persons/ → contacts (lookup po klientach)
    4. candidates          — /employees/ → candidates (metadata, BEZ binary CV)
    5. jobs                — /recruitments/ → jobs (lookup po klientach/workflows)
    6. talents             — /talents/ → talent_pools

  (Faza 5b — wymaga ukończonych phases 1-5)
    7. candidates-cv       — pobiera CV (binary) per kandydat z external_source=traffit
    8. pipelines           — /employees/recruitment_history → candidate_stages
                             (151k stage moves; ~2.5h przy 5 RPS)
    9. candidate-activities — /employees/activities → activities
                             (343k records; ~5.7h)
   10. candidate-sources   — /sources/ → candidate.tags (JSONB list)

   11. reconcile           — counts Traffit vs Nexus dla wszystkich encji

Uruchomienie:
    python -m app.cli.import_traffit --phase clients
    python -m app.cli.import_traffit --phase clients,contacts,workflows,candidates,jobs,talents
    python -m app.cli.import_traffit --phase reconcile
    python -m app.cli.import_traffit --phase candidates --dry-run

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


VALID_PHASES = {
    "clients",
    "contacts",
    "workflows",
    "candidates",
    "jobs",
    "talents",
    "candidates-cv",
    "pipelines",
    "candidate-activities",
    "candidate-sources",
    "reconcile",
}


def _parse_phases(arg: str) -> list[str]:
    phases = [p.strip() for p in arg.split(",") if p.strip()]
    invalid = [p for p in phases if p not in VALID_PHASES]
    if invalid:
        raise argparse.ArgumentTypeError(
            f"Unknown phase(s): {invalid}. Valid: {sorted(VALID_PHASES)}"
        )
    return phases


_PHASE_RUNNERS: dict[str, str] = {
    "clients": "import_clients",
    "contacts": "import_contacts",
    "workflows": "import_workflows",
    "candidates": "import_candidates",
    "jobs": "import_jobs",
    "talents": "import_talents",
    "candidates-cv": "import_candidates_cv",
    "pipelines": "import_pipelines",
    "candidate-activities": "import_candidate_activities",
    "candidate-sources": "import_candidate_sources",
}


async def _run(phases: Iterable[str], *, dry_run: bool, batch_size: int) -> int:
    config = TraffitConfig.from_env()
    exit_code = 0

    async with TraffitClient(config) as traffit:
        async with AsyncSessionLocal() as db:
            importer = TraffitImporter(
                traffit, db, dry_run=dry_run, batch_size=batch_size
            )
            for phase in phases:
                if phase == "reconcile":
                    report = await importer.reconcile()
                    print(json.dumps(report, indent=2))
                    if any(
                        isinstance(v, dict) and v.get("match") is False
                        for v in report.values()
                    ):
                        exit_code = 2  # mismatch — non-fatal but actionable
                else:
                    method_name = _PHASE_RUNNERS[phase]
                    progress = await getattr(importer, method_name)()
                    print(json.dumps(progress.as_dict(), default=str, indent=2))
                    if progress.errors:
                        exit_code = 1
    return exit_code


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Traffit → Nexus migration CLI (clients, contacts, workflows, "
            "candidates, jobs, talents)"
        )
    )
    parser.add_argument(
        "--phase",
        type=_parse_phases,
        required=True,
        help=(
            "comma-separated: workflows,clients,contacts,candidates,jobs,"
            "talents,reconcile"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="don't write to DB; just count and validate mappings",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="X-Request-Page-Size dla Traffit API (default 100; server hard cap)",
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
