"""Kto dostaje dzwonek, gdy karta przechodzi z rąk do rąk (02.10.2026).

Reguły etapów (`stage_notification_rules`, 0066) są przypięte do wiersza
definicji etapu i zasiane raz, w kwietniu: etap „QC CV” (0361) nie ma żadnej,
a „CV wysłane” zna tylko prowadzącego z pola rekrutacji. Zgłoszenie z testów
(02.10.2026): rekruter przekazał CV do QC, Delivery Lead wysłał je do klienta
i żadna z dwóch osób nie dostała powiadomienia — dzwonek trafił do osoby
z `jobs.recruiter_id`, która tego kandydata nie prowadziła.

Trzy przekazania wynikają z samego przepływu, więc nie zależą od tego, czy
ktoś dopisał regułę do etapu:

* „QC CV” poza Nordeą → Delivery Lead rekrutacji (ta sama reguła co kolejka
  „Czeka na Twój przegląd”, `board_tasks._sees_dl_review`);
* kolejka Cpro u Nordei → osoba od Cpro (`board_tasks`: firmowa, bez niej
  zapasowa z rekrutacji);
* „CV wysłane” → rekruter, który prowadzi kandydata w tej rekrutacji
  (`interview_slots.default_recruiter_id`: właściciel procesu → pierwszy
  weryfikator → prowadzący rekrutację).

Osoba, która sama przesunęła kartę, jest odsiewana w resolverze.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job
from app.models.pipeline_template import PipelineStageDef
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.services import cpro_sender
from app.services.board_stage_badges import (
    CV_QC_COLUMN,
    board_column_for,
    cpro_enabled_for_client,
    stage_badge_kind,
)

REASON_DL_REVIEW = "dl_review"
REASON_CPRO_QUEUE = "cpro_queue"
REASON_CV_SENT = "cv_sent"

CV_SENT_COLUMN = "cv_sent"


def _value(raw: object) -> Optional[str]:
    """Wartość enuma albo napis — definicja etapu niesie oba kształty."""

    if raw is None:
        return None
    return str(getattr(raw, "value", raw))


def handoff_kind(
    stage_def: PipelineStageDef,
    *,
    client_id: Optional[int],
    stage_code: Optional[str] = None,
) -> Optional[str]:
    """Które przekazanie oznacza wejście na ten etap (albo żadne).

    ``stage_code`` to kod zapisany w wierszu ruchu — ten sam, z którego ruch
    liczy kolumnę docelową; bez niego kod definicji etapu.
    """

    category = _value(stage_def.category)
    column = board_column_for(
        stage_def.name,
        stage_code or stage_def.legacy_enum_value,
        category=category,
        terminal_type=_value(stage_def.terminal_type),
    )
    nordea = cpro_enabled_for_client(client_id)
    if column == CV_QC_COLUMN:
        if stage_badge_kind(stage_def.name) == "cpro":
            return REASON_CPRO_QUEUE if nordea else None
        # U Nordei QC CV poprawia rekruter, a dalej idzie kolejka Cpro.
        return None if nordea else REASON_DL_REVIEW
    if column == CV_SENT_COLUMN:
        return REASON_CV_SENT
    return None


async def _dl_reviewers(db: AsyncSession, job: Job) -> list[int]:
    """Delivery Lead rekrutacji; bez niego (albo z martwym kontem) — DL-e
    z portfelem klienta."""

    is_dl = or_(
        User.role == UserRole.delivery_lead,
        User.roles.contains([UserRole.delivery_lead.value]),
    )
    if job.delivery_lead_id is not None:
        lead = await db.execute(
            select(User.id, is_dl).where(
                User.id == job.delivery_lead_id, User.is_active.is_(True)
            )
        )
        row = lead.first()
        if row is not None:
            # Aktywny DL wpisany w rekrutacji wygrywa. Bez roli DL kolejka
            # przeglądu nikomu tego zadania nie pokazuje — dzwonek też nie.
            return [row[0]] if row[1] else []
    if job.client_id is None:
        return []
    rows = await db.scalars(
        select(User.id)
        .join(
            DeliveryLeadClientAssignment,
            DeliveryLeadClientAssignment.delivery_lead_user_id == User.id,
        )
        .where(
            DeliveryLeadClientAssignment.client_id == job.client_id,
            User.is_active.is_(True),
            is_dl,
        )
    )
    return sorted(set(rows.all()))


async def _cpro_senders(db: AsyncSession, job: Job) -> list[int]:
    firm = (await cpro_sender.effective_sender(db)).user_id
    if firm is not None:
        return [firm]
    if job.cpro_sender_id is None:
        return []
    return sorted(await cpro_sender.active_user_ids(db, [job.cpro_sender_id]))


async def pair_recruiter_id(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> Optional[int]:
    """Rekruter prowadzący kandydata w tej rekrutacji."""

    from app.services.interview_slots import (  # noqa: PLC0415 — cykl importu
        default_recruiter_id,
    )

    return await default_recruiter_id(db, candidate_id=candidate_id, job_id=job_id)


async def handoff_recipients(
    db: AsyncSession,
    *,
    stage_def: PipelineStageDef,
    job: Job,
    candidate_id: int,
    stage_code: Optional[str] = None,
) -> tuple[Optional[str], list[int]]:
    """``(powód, odbiorcy)`` przekazania; ``(None, [])``, gdy etap nim nie jest."""

    kind = handoff_kind(stage_def, client_id=job.client_id, stage_code=stage_code)
    if kind == REASON_DL_REVIEW:
        return kind, await _dl_reviewers(db, job)
    if kind == REASON_CPRO_QUEUE:
        return kind, await _cpro_senders(db, job)
    if kind == REASON_CV_SENT:
        recruiter = await pair_recruiter_id(
            db, candidate_id=candidate_id, job_id=job.id
        )
        return kind, [recruiter] if recruiter is not None else []
    return None, []


__all__ = [
    "REASON_CPRO_QUEUE",
    "REASON_CV_SENT",
    "REASON_DL_REVIEW",
    "handoff_kind",
    "handoff_recipients",
    "pair_recruiter_id",
]
