"""Zapis raportu kompetencji przy zgłoszeniu i przydział opiekuna.

Decyzje Artura 25.11.2026: raport powstaje razem ze zgłoszeniem ze strony
(``report=1``), w stanie ``waiting_cv``. Pętla w tle składa go po odczycie CV
i wysyła najpóźniej o ``send_due_at`` (zgłoszenie + 23 h, godzina zapasu
przed obietnicą 24 h ze strony). Opiekun idzie po kolei między rekruterów
z listy admina (``competence_report_owners``): najdawniej przypisany, remis
po ``position``. Pusta lista = raport bez opiekuna (przejmuje każdy z kolejki).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application_submission import ApplicationSubmission
from app.models.candidate import Candidate
from app.models.competence_report import CompetenceReport, CompetenceReportOwner
from app.models.user import User
from app.services.competence_report_schema import ReportConditions

#: Termin wysyłki liczony od zgłoszenia (strona obiecuje 24 h).
SEND_DUE_AFTER = timedelta(hours=23)


async def assign_owner(
    db: AsyncSession, *, now: Optional[datetime] = None
) -> Optional[int]:
    """Następny opiekun z listy albo ``None``, gdy lista jest pusta. Bez commitu.

    ``SKIP LOCKED``: dwa równoczesne zgłoszenia nie dostają tej samej osoby,
    tylko kolejne dwie z listy. Konto wyłączone w NEXUSIE jest pomijane.
    """
    row = await db.scalar(
        select(CompetenceReportOwner)
        .join(User, User.id == CompetenceReportOwner.user_id)
        .where(CompetenceReportOwner.active.is_(True), User.is_active.is_(True))
        .order_by(
            CompetenceReportOwner.last_assigned_at.asc().nulls_first(),
            CompetenceReportOwner.position.asc(),
            CompetenceReportOwner.user_id.asc(),
        )
        .limit(1)
        .with_for_update(of=CompetenceReportOwner, skip_locked=True)
    )
    if row is None:
        return None
    row.last_assigned_at = now or datetime.now(timezone.utc)
    return row.user_id


async def create_report_for_application(
    db: AsyncSession,
    candidate: Candidate,
    submission: Optional[ApplicationSubmission],
    conditions: ReportConditions,
    email: str,
    *,
    now: Optional[datetime] = None,
) -> CompetenceReport:
    """Raport ``waiting_cv`` z terminem i opiekunem. Bez commitu."""
    created = now or datetime.now(timezone.utc)
    report = CompetenceReport(
        candidate_id=candidate.id,
        submission_id=submission.id if submission is not None else None,
        email=email,
        status="waiting_cv",
        conditions=conditions.model_dump(mode="json"),
        owner_user_id=await assign_owner(db, now=created),
        created_at=created,
        send_due_at=created + SEND_DUE_AFTER,
    )
    db.add(report)
    await db.flush()
    return report
