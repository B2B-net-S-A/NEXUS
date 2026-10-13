"""Pomiar QC CV na produkcji — tylko odczyt, same liczby (13.10.2026).

Przelicza QC bieżącym kodem dla par z przebiegiem w ostatnich N dniach
(`QC_AUDIT_DAYS`, domyślnie 3) i wypisuje JSON z liczbami: uwagi na parę,
porażki i pozycje per sprawdzenie, informacje, klasy błędów. Bez nazw,
treści i identyfikatorów osób — repo i logi Actions są publiczne.

Po co: zespół mówił, że QC „proponuje głupoty”. Pomiar z 13.10.2026 dał
średnio 9 uwag na CV, z czego około połowa była fałszywa. Przed podbiciem
`cv_qc.QC_VERSION` uruchom ten skrypt starym i nowym kodem na tych samych
parach i porównaj liczby (reguła w docs/claude/rekrutacja-tablica/
qc-cv-tryb-doradczy-role-z-odczytu-potwierdzenie.md).

Uruchomienie w kontenerze backendu (sesja bazy w trybie tylko do odczytu):
    ssh … "docker exec -i <backend> python -" < backend/scripts/qc_truth_audit.py
"""

import asyncio
import collections
import json
import os

DAYS = int(os.environ.get("QC_AUDIT_DAYS", "3"))


async def main() -> None:
    from sqlalchemy import text

    from app.core.database import AsyncSessionLocal, engine
    from app.models.recruitment_pipeline import CandidateStage
    from app.services import cv_qc
    from app.services.skill_taxonomy_loader import refresh_alias_map

    # Słownik technologii jak po starcie aplikacji (pogrubienia bez pokrycia).
    await refresh_alias_map()
    stats: collections.Counter = collections.Counter()
    per_check: dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter
    )
    errors: collections.Counter = collections.Counter()
    read_only = text("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
    async with AsyncSessionLocal() as db:
        await db.execute(read_only)
        stage_ids = (
            (
                await db.execute(
                    text(
                        "SELECT DISTINCT candidate_stage_id FROM cv_qc_runs "
                        "WHERE created_at > now() - make_interval(days => :days) "
                        "AND candidate_stage_id IS NOT NULL"
                    ),
                    {"days": DAYS},
                )
            )
            .scalars()
            .all()
        )
        for stage_id in stage_ids:
            try:
                stage = await db.get(CandidateStage, stage_id)
                if stage is None:
                    continue
                _src, checks, _notes = await cv_qc.evaluate(db, stage)
            except Exception as exc:  # noqa: BLE001 — pomiar liczy klasy błędów
                errors[type(exc).__name__] += 1
                await db.rollback()
                await db.execute(read_only)
                continue
            stats["pairs"] += 1
            passed, _blocking, _warnings = cv_qc.summarize(checks)
            stats["passed"] += int(passed)
            for check in checks:
                counter = per_check[check["key"]]
                counter["info"] += len(check.get("info") or [])
                if check["status"] != "fail":
                    continue
                items = len(check["items"]) or 1
                counter["fail"] += 1
                counter["items"] += items
                stats["items"] += items
                if check["severity"] == "blocking":
                    stats["blocking_items"] += items
    await engine.dispose()
    print(
        json.dumps(
            {
                "qc_version": getattr(cv_qc, "QC_VERSION", None),
                "days": DAYS,
                **stats,
                "items_per_pair": round(stats["items"] / max(1, stats["pairs"]), 2),
                "checks": {key: dict(c) for key, c in sorted(per_check.items())},
                "errors": dict(errors),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
