"""Jednorazowe „Zatrudniony” dla par z podpisaną umową, zostawionych na „Akceptacji”.

Zgłoszenie 18.11.2026: kafelek „Kandydaci do zamknięcia” pokazał osobę
podpisaną 17.09 jako „Zaakceptowany od 62 dni”. Umowę i kontrakt założono
poza Generatorem, więc karty nikt nie przesunął na „Zatrudniony”. Rekrutację
zakończono, a 04.11 ktoś otworzył ją ponownie, więc para wróciła do kafelka
(kafelek bierze każdą opublikowaną rekrutację). Na produkcji są cztery takie
pary: karta na „Akceptacji”, otwarty proces i żywy kontrakt na tę samą
rekrutację. Trzy z nich wróciłyby tak samo po ponownym otwarciu rekrutacji.

Decyzja Artura z 18.11.2026: „Zatrudniony” z datą akceptacji, żeby zatrudnienie
liczyło się w miesiącu podpisu (DynaReporter liczy je we wrześniu), a nie w dniu
naprawy. Ruch idzie przez ``transition_process`` (proces się zamyka) minutę po
wierszu akceptacji. Bez maili i dzwonków: to korekta historii, nie nowe
zdarzenie. Pary przypięte po ID (bez nazwisk w repo). Inny ostatni etap, brak
kontraktu tej pary albo kontrakt wycofany = pominięcie z kodem powodu.
Paragon pod kluczem ``REPAIR_MARKER``: liczniki i ID.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.contract import Contract, ContractStatus
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.services.b2b_contract_automation import _resolve_hired_stage_def
from app.services.candidate_contact_hooks import maybe_close_contact_opportunity
from app.services.priority_work_policy import PriorityWorkLocked
from app.services.recruitment_process_commands import transition_process

logger = logging.getLogger(__name__)

REPAIR_MARKER = "stale_acceptance_hired_2026_11_18"
REPAIR_NOTE = (
    "Zatrudniony z datą akceptacji: umowa podpisana poza Generatorem, "
    "karta została na „Akceptacji” (korekta 18.11.2026)."
)
# „Zatrudniony” ląduje tuż po wierszu akceptacji: ten sam dzień, późniejszy wpis.
HIRED_AFTER_ACCEPTANCE = timedelta(minutes=1)

# (kandydat, rekrutacja, kontrakt) — stan produkcji z 18.11.2026.
TARGETS: tuple[tuple[int, int, int], ...] = (
    (111481, 484836, 669),
    (34783, 493163, 668),
    (18880, 4235, 672),
    (12858, 404749, 716),
)


async def _hire_one(
    db: AsyncSession, candidate_id: int, job_id: int, contract_id: int
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "candidate_id": candidate_id,
        "job_id": job_id,
        "skipped": None,
    }
    contract = await db.get(Contract, contract_id)
    if contract is None:
        result["skipped"] = "contract_missing"
        return result
    if contract.candidate_id != candidate_id or contract.job_id != job_id:
        result["skipped"] = "identity_mismatch"
        return result
    if contract.status == ContractStatus.void:
        result["skipped"] = "contract_void"
        return result
    latest = await db.scalar(
        select(CandidateStage)
        .where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == job_id,
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        .limit(1)
        .with_for_update()
    )
    if latest is None or latest.stage != PipelineStage.acceptance:
        result["skipped"] = "not_on_acceptance"
        return result
    job = await db.get(Job, job_id)
    stage_def = await _resolve_hired_stage_def(db, job)
    hired_at = latest.moved_at + HIRED_AFTER_ACCEPTANCE
    try:
        async with db.begin_nested():
            stage = await transition_process(
                db,
                candidate_id=candidate_id,
                job_id=job_id,
                stage=PipelineStage.hired,
                stage_def_id=stage_def.id if stage_def else None,
                moved_at=hired_at,
                actor_user_id=None,
                require_existing=True,
                source_authority="repair",
                notes=REPAIR_NOTE,
            )
    except PriorityWorkLocked:
        result["skipped"] = "no_open_process"
        return result
    await maybe_close_contact_opportunity(
        db,
        candidate_id=candidate_id,
        job_id=job_id,
        reason="pipeline_terminal:hired",
        occurred_at=hired_at,
    )
    db.add(
        Activity(
            entity_type="pipeline",
            entity_id=stage.id,
            action="stage_changed",
            user_id=None,
            details={
                "candidate_id": candidate_id,
                "job_id": job_id,
                "stage": PipelineStage.hired.value,
                "stage_def_id": stage.stage_def_id,
                "source": REPAIR_MARKER,
                "contract_id": contract_id,
            },
        )
    )
    result.update({"stage_id": stage.id, "hired_on": hired_at.date().isoformat()})
    return result


async def run_stale_acceptance_hired_repair(
    db: AsyncSession,
    *,
    targets: Iterable[tuple[int, int, int]] = TARGETS,
    marker: str = REPAIR_MARKER,
) -> Optional[dict[str, Any]]:
    """Wykonaj korektę; ``None`` = już wykonana. Wołający commituje."""

    await db.execute(text("SET LOCAL lock_timeout = '15s'"))
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": marker}
    )
    if await db.get(AppSetting, marker) is not None:
        return None
    rows = list(targets)
    results = [await _hire_one(db, *row) for row in rows]
    summary = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "requested": len(rows),
        "hired": sum(1 for r in results if r["skipped"] is None),
        "results": results,
    }
    db.add(AppSetting(key=marker, value=summary))
    await db.flush()
    logger.info("stale acceptance hired repair: %s/%s", summary["hired"], len(rows))
    return summary


def summarize_for_log(summary: Optional[dict[str, Any]]) -> str:
    if summary is None:
        return "already applied"
    skipped = [
        f"{r['candidate_id']}/{r['job_id']}:{r['skipped']}"
        for r in summary["results"]
        if r["skipped"] is not None
    ]
    return f"hired {summary['hired']}/{summary['requested']}" + (
        f"; skipped {', '.join(skipped)}" if skipped else ""
    )
