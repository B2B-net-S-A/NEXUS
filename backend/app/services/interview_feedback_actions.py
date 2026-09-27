"""Auto-akcje po zapisaniu InterviewFeedback.

Wywoływane z `POST /api/interview-feedback` i `PATCH /api/interview-feedback/{id}`
po udanym commicie. Wszystkie akcje są best-effort i idempotentne — żadna
nie powinna zwalić głównej ścieżki zapisu feedbacku.

Reguły v1 (MVP, bez destruktywnych operacji):
- `decision=advance`         → notyfikacja `suggest_next_step` do recruiter
- `decision=reject`          → notyfikacja `suggest_next_step` do recruiter
                               z sugestią zamknięcia pipeline'u / move-to-pool
- `interest_level=dead`      → jak wyżej (kandydat odpadł po swojej stronie)
- inne decyzje / interest_level → no-op

UWAGA v2 (nie w tym PR):
- auto-przeniesienie do talent_pool gdy reject/dead (wymaga wcześniejszej
  inspekcji `app/services/auto_cc_collaborators.py` / `talent_pool.py` —
  destruktywna operacja, blokujemy v1 za zgodą Artura)
- auto-advance stage pipeline'u gdy decision=advance (jw.)
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.interview_feedback import (
    InterestLevel,
    InterviewDecision,
    InterviewFeedback,
)
from app.models.job import Job
from app.models.notification import NotificationType
from app.services.notification_triggers import (
    _delivery_lead_targets,
    _operational_recipient,
    emit,
)

logger = logging.getLogger(__name__)


async def _load_job(db: AsyncSession, job_id: Optional[int]) -> Optional[Job]:
    if job_id is None:
        return None
    return await db.get(Job, job_id)


async def _emit_to(db: AsyncSession, recipients: list[int], **kwargs) -> int:
    sent = 0
    for user_id in recipients:
        if await emit(db, user_id=user_id, **kwargs) is not None:
            sent += 1
    return sent


async def apply_post_feedback_actions(
    db: AsyncSession, feedback: InterviewFeedback
) -> int:
    """Emit follow-up notifications based on the feedback content.

    Returns number of notifications emitted.
    """
    if (
        feedback.decision not in (InterviewDecision.advance, InterviewDecision.reject)
        and feedback.interest_level != InterestLevel.dead
    ):
        return 0
    job = await _load_job(db, feedback.job_id)
    # Runda 8 (R8-X1-1): adresat jak przy telefonie po rozmowie — prowadzący,
    # a gdy jego konta już nie ma, autor feedbacku (zastępstwo z COMPASS
    # wygrywa); bez obu DL rekrutacji albo Head of Recruitment. Do tej pory
    # nieaktywny prowadzący połykał „Klient idzie dalej / odrzucił” w `emit`.
    recipient = await _operational_recipient(
        db, [job.recruiter_id if job else None, feedback.author_id]
    )
    if recipient is not None:
        recipients = [recipient]
    elif job is not None:
        recipients = await _delivery_lead_targets(db, job)
    else:
        recipients = []
    if not recipients:
        logger.debug(
            "interview_feedback_actions: no recipient for feedback id=%s — skipping",
            feedback.id,
        )
        return 0

    emitted = 0
    # Imię i nazwisko zamiast „#12345" — numer nic rekruterowi nie mówi.
    candidate = await db.get(Candidate, feedback.candidate_id)
    full_name = (
        " ".join(p for p in (candidate.name, candidate.lastname) if p).strip()
        if candidate is not None
        else ""
    )
    who = full_name or "kandydat"
    in_job = f" w rekrutacji „{job.title}”" if job is not None and job.title else ""

    if feedback.decision == InterviewDecision.advance:
        emitted += await _emit_to(
            db,
            recipients,
            title="Klient idzie dalej — zaproponuj next step",
            message=(
                f"Klient chce iść dalej: {who}{in_job}. "
                "Zaproponuj kolejny krok — kolejną rozmowę, ofertę dla kandydata "
                "albo dopytaj klienta, co dalej."
            ),
            link=f"/candidates/{feedback.candidate_id}",
            ntype=NotificationType.suggest_next_step,
            related_entity_type="candidate",
            related_entity_id=feedback.candidate_id,
        )

    if feedback.decision == InterviewDecision.reject:
        emitted += await _emit_to(
            db,
            recipients,
            title="Klient odrzucił — zamknij proces albo przenieś do puli",
            message=(
                f"Klient nie chce kontynuować: {who}{in_job}. "
                "Przesuń kandydata na etap „Odrzucony” i rozważ dodanie do puli talentów."
            ),
            link=f"/candidates/{feedback.candidate_id}",
            ntype=NotificationType.suggest_next_step,
            related_entity_type="candidate",
            related_entity_id=feedback.candidate_id,
        )

    if feedback.interest_level == InterestLevel.dead:
        emitted += await _emit_to(
            db,
            recipients,
            title="Kandydat stracił zainteresowanie",
            message=(
                f"{full_name or 'Kandydat'}{in_job} zamknął temat po swojej stronie. "
                "Zapisz powód, zamknij proces i rozważ dodanie do puli talentów."
            ),
            link=f"/candidates/{feedback.candidate_id}",
            ntype=NotificationType.suggest_next_step,
            related_entity_type="candidate",
            related_entity_id=feedback.candidate_id,
        )

    return emitted
