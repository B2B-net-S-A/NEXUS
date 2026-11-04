"""Czy nowy kod QC nadal zgłasza uwagi oznaczone „To nieprawda” — tylko odczyt.

Przelicza QC bieżącym kodem dla par z aktywnymi pominięciami „QC się myli”
(`cv_finding_dismissals.QC_WRONG_REASONS`) i wypisuje per sprawdzenie, ile
pominiętych uwag kod nadal zgłasza (`dismissed_items`), a ile już nie. Same
liczby, bez osób i treści — repo i logi Actions są publiczne.

Reguła (docs/claude/rekrutacja-tablica/qc-to-nieprawda-i-jakosc-qc.md): przed
podbiciem `cv_qc.QC_VERSION` uruchom ten skrypt starym i nowym kodem; nowa
wersja nie może zgłaszać więcej uwag, które zespół oznaczył jako nieprawdziwe.

Uruchomienie w kontenerze backendu:
    ssh … "docker exec -i <backend> python -" < backend/scripts/qc_eval_dismissals.py
"""

import asyncio
import collections
import json


async def main() -> None:
    from sqlalchemy import select, text

    from app.core.database import AsyncSessionLocal, engine
    from app.models.cv_finding_dismissal import CvFindingDismissal
    from app.models.recruitment_pipeline import CandidateStage
    from app.services import cv_qc
    from app.services.cv_finding_dismissals import QC_WRONG_REASONS
    from app.services.skill_taxonomy_loader import refresh_alias_map

    await refresh_alias_map()
    still: collections.Counter = collections.Counter()
    gone: collections.Counter = collections.Counter()
    errors: collections.Counter = collections.Counter()
    read_only = text("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
    async with AsyncSessionLocal() as db:
        # Ustawienie sesji działa od następnej transakcji.
        await db.execute(read_only)
        await db.commit()
        rows = (
            await db.execute(
                select(
                    CvFindingDismissal.candidate_stage_id,
                    CvFindingDismissal.check_key,
                    CvFindingDismissal.finding_key,
                ).where(
                    CvFindingDismissal.source == "qc",
                    CvFindingDismissal.restored_at.is_(None),
                    CvFindingDismissal.reason.in_(tuple(QC_WRONG_REASONS)),
                    CvFindingDismissal.candidate_stage_id.is_not(None),
                )
            )
        ).all()
        by_stage: dict[int, list[tuple[str, str]]] = collections.defaultdict(list)
        for stage_id, check_key, key in rows:
            by_stage[stage_id].append((check_key, key))
        for stage_id, wanted in by_stage.items():
            try:
                stage = await db.get(CandidateStage, stage_id)
                if stage is None:
                    continue
                _src, checks, _notes = await cv_qc.evaluate(db, stage)
            except Exception as exc:  # noqa: BLE001 — pomiar liczy klasy błędów
                errors[type(exc).__name__] += 1
                await db.rollback()
                await db.execute(read_only)
                await db.commit()
                continue
            emitted = {
                (check["key"], item.get("key"))
                for check in checks
                for item in check.get("dismissed_items") or []
            }
            for check_key, key in wanted:
                if (check_key, key) in emitted:
                    still[check_key] += 1
                else:
                    gone[check_key] += 1
    await engine.dispose()
    keys = sorted(set(still) | set(gone))
    print(
        json.dumps(
            {
                "qc_version": cv_qc.QC_VERSION,
                "pairs": len(by_stage),
                "checks": {
                    key: {"still_reported": still[key], "no_longer": gone[key]}
                    for key in keys
                },
                "errors": dict(errors),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
