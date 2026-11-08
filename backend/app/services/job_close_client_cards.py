"""Zamknięcie rekrutacji kończy pary u klienta (B5, decyzja Artura 08.11.2026).

Od 13.10.2026 zamknięcie nie ruszało kart. Audyt 08.11: 360 par stało „u klienta”
w 108 rekrutacjach zamkniętych od 12.10, a przy przegranej powód odpadnięcia osoby
ginął. Przy powodzie „Wybrali konkurencję” albo „Brak budżetu” (także z maila CPro)
pary w „CV wysłane” i „Rozmowie u klienta” kończą się „przez klienta”, z powodem
i bez maila do kandydata. Pary wewnętrzne i „Umowa” zostają.

Karty idą po commicie zamknięcia, każda we własnej transakcji: ``transition_process``
bierze kandydata, a potem rekrutację, a trasa trzyma już blokadę rekrutacji; ta sama
kolejność w jednej transakcji dawałaby zakleszczenie z ręcznym ruchem karty.

Reguła: ``docs/claude/rekrutacja-tablica/zamkniecie-rekrutacji-osoby-w-toku.md``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.job import Job, JobCloseReason
from app.models.pipeline_template import PipelineStageDef, RejectionReason, TerminalType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.services.board_stage_badges import board_column_for
from app.services.job_opening import in_opening
from app.services.rejection_reason_labels import (
    CLIENT_CHOSE_OTHER,
    REQUEST_CLOSED,
    rejection_reason_label,
)

logger = logging.getLogger(__name__)

#: Powód zamknięcia rekrutacji → klucz powodu końca pary.
REASON_FOR_CLOSE: dict[JobCloseReason, str] = {
    JobCloseReason.competitor: CLIENT_CHOSE_OTHER,
    JobCloseReason.budget: REQUEST_CLOSED,
}
#: „U klienta”: czeka na jego decyzję. „Umowa” zostaje, bo tam klient już powiedział tak.
CLIENT_SIDE_COLUMNS: tuple[str, ...] = ("cv_sent", "client_interview")

ENDED_BY_CLIENT = "client"


def reason_key_for(reason: Any) -> Optional[str]:
    """Klucz powodu końca pary albo ``None``, gdy ten powód zamknięcia nie rusza kart."""
    try:
        return REASON_FOR_CLOSE.get(JobCloseReason(getattr(reason, "value", reason)))
    except ValueError:
        return None


def _pair_people(count: int) -> str:
    if count == 1:
        return "1 osoba jest u klienta"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return f"{count} osoby są u klienta"
    return f"{count} osób jest u klienta"


def preview_payload(columns: dict[int, str], reason: Any) -> Optional[dict[str, Any]]:
    """Część odpowiedzi 409: ile par zakończy zamknięcie. ``None`` = nic."""
    key = reason_key_for(reason)
    if key is None or not columns:
        return None
    counts: dict[str, int] = {}
    for column in columns.values():
        counts[column] = counts.get(column, 0) + 1
    label = rejection_reason_label(key)
    return {
        "reason": getattr(reason, "value", reason),
        "reason_label": label,
        "people": len(columns),
        "columns": {c: counts[c] for c in CLIENT_SIDE_COLUMNS if c in counts},
        "message": (
            f"{_pair_people(len(columns))}. Możesz zakończyć ich procesy jako „przez "
            f"klienta” z powodem „{label}”. Kandydaci nie dostaną maila."
        ),
    }


async def client_side_cards(db: AsyncSession, job: Job) -> dict[int, str]:
    """{kandydat: kolumna} par u klienta w bieżącym otwarciu rekrutacji."""
    rows = (
        await db.execute(
            select(
                CandidateStage.candidate_id,
                CandidateStage.stage,
                CandidateStage.moved_at,
                PipelineStageDef.name,
                PipelineStageDef.category,
                PipelineStageDef.terminal_type,
            )
            .outerjoin(
                PipelineStageDef, PipelineStageDef.id == CandidateStage.stage_def_id
            )
            .where(CandidateStage.job_id == job.id)
            .order_by(CandidateStage.moved_at, CandidateStage.id)
        )
    ).all()
    latest: dict[int, Any] = {}
    for row in rows:
        latest[row.candidate_id] = row
    cards: dict[int, str] = {}
    for candidate_id, row in latest.items():
        if not in_opening(row.moved_at, job.cycle_started_at):
            continue
        column = board_column_for(
            row.name,
            getattr(row.stage, "value", row.stage),
            category=getattr(row.category, "value", row.category),
            terminal_type=getattr(row.terminal_type, "value", row.terminal_type),
        )
        if column in CLIENT_SIDE_COLUMNS:
            cards[candidate_id] = column
    return cards


async def _reason_id(
    db: AsyncSession, template_id: Optional[int], key: str
) -> Optional[int]:
    if template_id is None:
        return None
    return await db.scalar(
        select(RejectionReason.id)
        .where(
            RejectionReason.template_id == template_id,
            RejectionReason.name == key,
            RejectionReason.category == TerminalType.rejected,
        )
        .limit(1)
    )


async def end_card(
    db: AsyncSession,
    job: Job,
    candidate_id: int,
    *,
    reason_key: str,
    actor_id: Optional[int],
    note: str,
    source: str,
    ended_by: str = ENDED_BY_CLIENT,
    moved_at: Optional[datetime] = None,
) -> Optional[CandidateStage]:
    """Jedna para do „Zamknięci”, bez commitu i bez maila do kandydata.

    ``None`` = para zamknięta w międzyczasie albo szablon bez powodu.
    """
    from app.services.candidate_contact_hooks import (  # noqa: PLC0415
        maybe_close_contact_opportunity,
    )
    from app.services.pipeline_auto_move import (  # noqa: PLC0415
        _target_stage_def,
        _template_id,
        is_closed,
    )
    from app.services.recruitment_process_commands import (  # noqa: PLC0415
        transition_process,
    )

    await db.scalar(
        select(Candidate.id).where(Candidate.id == candidate_id).with_for_update()
    )
    latest = await db.scalar(
        select(CandidateStage)
        .where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == job.id,
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        .limit(1)
    )
    if latest is None:
        return None
    latest_def = (
        await db.get(PipelineStageDef, latest.stage_def_id)
        if latest.stage_def_id is not None
        else None
    )
    if is_closed(latest.stage, latest_def):
        return None
    template_id = await _template_id(db, job)
    reason_id = await _reason_id(db, template_id, reason_key)
    if reason_id is None:
        logger.warning(
            "job_close_client_cards: brak powodu %s w szablonie %s (job_id=%s)",
            reason_key,
            template_id,
            job.id,
        )
        return None
    target_def = await _target_stage_def(db, template_id, PipelineStage.rejected)
    stage = await transition_process(
        db,
        candidate_id=candidate_id,
        job_id=job.id,
        stage=PipelineStage.rejected,
        stage_def_id=target_def.id if target_def is not None else None,
        rejection_reason_id=reason_id,
        moved_at=moved_at or datetime.now(timezone.utc),
        actor_user_id=actor_id,
        require_existing=True,
        notes=note,
        ended_by=ended_by,
    )
    await maybe_close_contact_opportunity(
        db,
        candidate_id=candidate_id,
        job_id=job.id,
        actor_user_id=actor_id,
        reason="pipeline_terminal:rejected",
        occurred_at=stage.moved_at,
    )
    db.add(
        Activity(
            entity_type="pipeline",
            entity_id=stage.id,
            action="stage_changed",
            user_id=actor_id,
            details={
                "candidate_id": candidate_id,
                "job_id": job.id,
                "from_stage": getattr(latest.stage, "value", latest.stage),
                "from_stage_def_id": latest.stage_def_id,
                "stage": PipelineStage.rejected.value,
                "stage_def_id": stage.stage_def_id,
                "source": source,
            },
        )
    )
    return stage


async def end_client_cards_after_close(
    job_id: int,
    *,
    reason: Any,
    actor_id: Optional[int],
    source: str = "job_close",
    session_factory: Any = None,
) -> dict[str, int]:
    """Kończy pary u klienta po zamknięciu; błąd jednej pary nie zatrzymuje reszty."""
    from app.core.database import AsyncSessionLocal  # noqa: PLC0415
    from app.services.pipeline_auto_move import run_after_commit  # noqa: PLC0415
    from app.services.pipeline_realtime import (  # noqa: PLC0415
        broadcast_pipeline_changed,
    )
    from app.services.priority_work_policy import PriorityWorkLocked  # noqa: PLC0415

    key = reason_key_for(reason)
    if key is None:
        return {"ended": 0, "skipped": 0}
    label = rejection_reason_label(key)
    factory = session_factory or AsyncSessionLocal
    ended = skipped = 0
    async with factory() as db:
        job = await db.get(Job, job_id)
        if job is None:
            return {"ended": 0, "skipped": 0}
        cards = await client_side_cards(db, job)
        await db.commit()
        for candidate_id in sorted(cards):
            try:
                stage = await end_card(
                    db,
                    job,
                    candidate_id,
                    reason_key=key,
                    actor_id=actor_id,
                    note=f"Rekrutacja zamknięta: {label}",
                    source=source,
                )
                await db.commit()
            except PriorityWorkLocked:
                await db.rollback()
                job = await db.get(Job, job_id)
                skipped += 1
                continue
            except Exception:  # noqa: BLE001 — jedna para nie zatrzymuje reszty
                logger.exception(
                    "job_close_client_cards: para job_id=%s candidate_id=%s",
                    job_id,
                    candidate_id,
                )
                await db.rollback()
                job = await db.get(Job, job_id)
                skipped += 1
                continue
            if stage is None:
                skipped += 1
                continue
            ended += 1
            await run_after_commit(db, stage_id=stage.id, mover=None)
            await db.commit()
        if ended:
            await broadcast_pipeline_changed(db, job_id, None)
        db.add(
            Activity(
                entity_type="job",
                entity_id=job_id,
                action="client_cards_ended_on_close",
                user_id=actor_id,
                details={
                    "reason": getattr(reason, "value", reason),
                    "ended": ended,
                    "skipped": skipped,
                },
            )
        )
        await db.commit()
    return {"ended": ended, "skipped": skipped}
