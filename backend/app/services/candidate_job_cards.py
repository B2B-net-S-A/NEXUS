"""Bieżąca karta osoby w rekrutacji — jedno zapytanie dla wielu osób.

„Bieżąca” = ostatni wiersz ``candidate_stages`` pary (``moved_at``, potem
``id``), a kolumnę liczy ta sama reguła co Tablica (``board_column_for``).
Czytają to:

* bulk-add — zamknięta karta w tej rekrutacji (``proposals_bulk._closed_cards``);
* okno „Dodaj kandydatów do pipeline” — imiennik, który już ma kartę w tej
  rekrutacji, i ostatnia rekrutacja osoby u nas (``api/search.py``,
  ``docs/claude/rekrutacja-tablica/imiennicy-w-oknie-dodawania.md``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import DEFAULT_TZ
from app.models.job import Job
from app.models.pipeline_template import PipelineStageDef
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User
from app.schemas.pipeline import STAGE_LABELS


def stage_display_label(name: Optional[str], stage: Optional[str]) -> Optional[str]:
    """Nazwa etapu z szablonu, a dla wiersza bez etapu szablonu — z kodu."""
    if name and name.strip():
        return name.strip()
    try:
        return STAGE_LABELS[PipelineStage(stage)]
    except (KeyError, ValueError):
        return None


def business_day(moment: datetime) -> date:
    """Dzień ruchu w kalendarzu firmy (Europe/Warsaw)."""
    return moment.astimezone(ZoneInfo(DEFAULT_TZ)).date()


@dataclass(frozen=True)
class LatestCard:
    candidate_id: int
    job_id: int
    job_title: Optional[str]
    stage_label: Optional[str]
    column: str
    moved_at: datetime
    moved_by_name: Optional[str]


async def latest_cards(
    db: AsyncSession,
    *,
    candidate_ids: Sequence[int],
    job_id: Optional[int] = None,
    exclude_job_id: Optional[int] = None,
    scope_clause: Optional[Any] = None,
) -> dict[int, LatestCard]:
    """Ostatnia karta każdej osoby — w jednej rekrutacji albo w dowolnej.

    ``job_id`` zawęża do jednej rekrutacji; ``exclude_job_id`` pomija jedną
    (ostatnia rekrutacja „gdzie indziej”); ``scope_clause`` to zakres
    rekrutacji widocznych dla użytkownika (``job_read_scope_clause``).
    """
    from app.services.board_stage_badges import board_column_for  # noqa: PLC0415

    ids = list(dict.fromkeys(candidate_ids))
    if not ids:
        return {}
    latest = select(CandidateStage.id).where(CandidateStage.candidate_id.in_(ids))
    if job_id is not None:
        latest = latest.where(CandidateStage.job_id == job_id)
    if exclude_job_id is not None:
        latest = latest.where(CandidateStage.job_id != exclude_job_id)
    if scope_clause is not None:
        latest = latest.where(scope_clause)
    latest = latest.distinct(CandidateStage.candidate_id).order_by(
        CandidateStage.candidate_id,
        CandidateStage.moved_at.desc(),
        CandidateStage.id.desc(),
    )
    rows = (
        await db.execute(
            select(
                CandidateStage.candidate_id,
                CandidateStage.job_id,
                CandidateStage.stage,
                CandidateStage.moved_at,
                PipelineStageDef.name,
                PipelineStageDef.category,
                PipelineStageDef.terminal_type,
                User.name,
                Job.title,
            )
            .outerjoin(
                PipelineStageDef, PipelineStageDef.id == CandidateStage.stage_def_id
            )
            .outerjoin(User, User.id == CandidateStage.moved_by)
            .outerjoin(Job, Job.id == CandidateStage.job_id)
            .where(CandidateStage.id.in_(latest))
        )
    ).all()
    cards: dict[int, LatestCard] = {}
    for (
        candidate_id,
        row_job_id,
        stage,
        moved_at,
        name,
        category,
        terminal_type,
        by,
        job_title,
    ) in rows:
        code = getattr(stage, "value", stage)
        cards[candidate_id] = LatestCard(
            candidate_id=candidate_id,
            job_id=row_job_id,
            job_title=job_title,
            stage_label=stage_display_label(name, code),
            column=board_column_for(
                name,
                code,
                category=getattr(category, "value", category),
                terminal_type=getattr(terminal_type, "value", terminal_type),
            ),
            moved_at=moved_at,
            moved_by_name=by,
        )
    return cards
