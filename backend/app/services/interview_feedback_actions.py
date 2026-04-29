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

from app.models.interview_feedback import (
    InterestLevel,
    InterviewDecision,
    InterviewFeedback,
)
from app.models.job import Job
from app.models.notification import NotificationType
from app.services.notification_triggers import emit

logger = logging.getLogger(__name__)


async def _load_job(db: AsyncSession, job_id: Optional[int]) -> Optional[Job]:
    if job_id is None:
        return None
    return await db.get(Job, job_id)


async def apply_post_feedback_actions(
    db: AsyncSession, feedback: InterviewFeedback
) -> int:
    """Emit follow-up notifications based on the feedback content.

    Returns number of notifications emitted.
    """
    job = await _load_job(db, feedback.job_id)
    recruiter_id = job.recruiter_id if job else None
    if not recruiter_id:
        # Fallback: autor feedbacku (ktoś zarejestrował, więc ma relację do procesu)
        recruiter_id = feedback.author_id
    if not recruiter_id:
        logger.debug(
            "interview_feedback_actions: no recipient (no recruiter_id, no author_id) "
            "for feedback id=%s — skipping",
            feedback.id,
        )
        return 0

    emitted = 0

    if feedback.decision == InterviewDecision.advance:
        result = await emit(
            db,
            user_id=recruiter_id,
            title="Klient idzie dalej — zaproponuj next step",
            message=(
                f"Klient chce iść dalej z kandydatem #{feedback.candidate_id}. "
                "Zaproponuj: CV, drugi interview, offer, lub dopytaj co dalej."
            ),
            link=f"/candidates/{feedback.candidate_id}",
            ntype=NotificationType.suggest_next_step,
            related_entity_type="candidate",
            related_entity_id=feedback.candidate_id,
        )
        if result is not None:
            emitted += 1

    if feedback.decision == InterviewDecision.reject:
        result = await emit(
            db,
            user_id=recruiter_id,
            title="Klient odrzucił — zamknij proces / przenieś do puli",
            message=(
                f"Klient nie chce kontynuować z kandydatem #{feedback.candidate_id}. "
                "Zamknij stage jako rejected i rozważ przeniesienie do talent pool."
            ),
            link=f"/candidates/{feedback.candidate_id}",
            ntype=NotificationType.suggest_next_step,
            related_entity_type="candidate",
            related_entity_id=feedback.candidate_id,
        )
        if result is not None:
            emitted += 1

    if feedback.interest_level == InterestLevel.dead:
        result = await emit(
            db,
            user_id=recruiter_id,
            title="Kandydat stracił zainteresowanie",
            message=(
                f"Kandydat #{feedback.candidate_id} zamknął temat po swojej stronie "
                "(interest_level=dead). Zapisz reason, zamknij stage, rozważ pulę."
            ),
            link=f"/candidates/{feedback.candidate_id}",
            ntype=NotificationType.suggest_next_step,
            related_entity_type="candidate",
            related_entity_id=feedback.candidate_id,
        )
        if result is not None:
            emitted += 1

    return emitted
