"""Jednorazowe zaliczenie i odblokowanie kart, które utknęły na „Oczekuje".

Decyzja Artura 17.09.2026: bramka „Oczekuje" (stawka ponad budżet przy ruchu na
„Zweryfikowany") jest usunięta NA STAŁE — ruch nigdy nie ustawia już
`verification_status='pending'`, a kolejka akceptacji (trasy i ekrany) zniknęła.
Wiersze zapisane wcześniej jako `pending` nie miałyby kto rozstrzygnąć, więc ten
blok robi to raz, dla KAŻDEGO takiego wiersza:

* każdy wiersz → `verification_status=active` + znacznik czasu akceptacji
  (karta przestaje być zablokowana);
* wiersz etapu „Zweryfikowany" jest dodatkowo ZALICZONY tak, jak zrobiłaby to
  ręczna akceptacja — `record_accepted_verification` z weryfikatorem = osoba,
  która przesunęła kartę (liczy się do KPI i do pierwszej weryfikacji);
* wiersz innego etapu jest wyłącznie odblokowywany (to nie była weryfikacja).

Różnice wobec dawnej ręcznej akceptacji, obie świadome: `approved_by` zostaje
puste (decyzję podjęła zmiana polityki; paragon w `app_settings` mówi, kiedy
i ile) i nie wymagamy, żeby karta była aktualnym etapem procesu.

JEDEN kod dla obu kanałów: migracja `0325_pending_verification_retired` woła
`run_pending_verification_promotion` na połączeniu migracji, a `entrypoint.sh`
woła ją po starcie (prod alembic bywa osierocony). Advisory lock + znacznik →
drugi przebieg kończy się natychmiast. Paragon niesie wyłącznie liczby i ID.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.recruitment_pipeline import CandidateStage, VerificationStatus

logger = logging.getLogger(__name__)

PROMOTION_MARKER = "pending_verification_promotion_2026_09_17"


async def run_pending_verification_promotion(
    db: AsyncSession,
    *,
    only_stage_ids: Optional[set[int]] = None,
) -> Optional[dict[str, Any]]:
    """Odblokuj (i zalicz) wszystkie wiersze `pending`. ``None`` = już zrobione.

    Wołający commituje. ``only_stage_ids`` zawęża przebieg — wyłącznie dla
    testów, które nie mogą ruszać cudzych wierszy we wspólnej bazie (i wtedy
    znacznik NIE jest stawiany).
    """
    from app.services.priority_work_policy import invalidate_milestone_counts
    from app.services.recruitment_process_commands import (
        promote_legacy_pending_verification,
    )

    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": PROMOTION_MARKER},
    )
    if only_stage_ids is None and await db.get(AppSetting, PROMOTION_MARKER):
        return None

    query = (
        select(CandidateStage.id, CandidateStage.candidate_id)
        .where(CandidateStage.verification_status == VerificationStatus.pending)
        .order_by(CandidateStage.id)
    )
    if only_stage_ids is not None:
        query = query.where(CandidateStage.id.in_(only_stage_ids))
    targets = (await db.execute(query)).all()

    now = datetime.now(timezone.utc)
    unblocked: list[int] = []
    credited: list[int] = []
    failed: list[int] = []
    for stage_id, candidate_id in targets:
        try:
            async with db.begin_nested():
                # Ta sama kolejność blokad co `/move` (kandydat → etap), żeby
                # nie zakleszczyć się z żywym ruchem na tej samej karcie.
                await db.scalar(
                    select(Candidate.id)
                    .where(Candidate.id == candidate_id)
                    .with_for_update()
                )
                stage = await db.scalar(
                    select(CandidateStage)
                    .where(CandidateStage.id == stage_id)
                    .with_for_update()
                )
                if (
                    stage is None
                    or stage.verification_status != VerificationStatus.pending
                ):
                    continue
                if await promote_legacy_pending_verification(
                    db, stage=stage, accepted_at=now
                ):
                    credited.append(stage_id)
                unblocked.append(stage_id)
        except Exception:  # noqa: BLE001 — jeden zepsuty wiersz nie blokuje reszty
            logger.exception("pending verification promotion failed for %s", stage_id)
            failed.append(stage_id)
    invalidate_milestone_counts()

    summary: dict[str, Any] = {
        "executed_at": now.isoformat(),
        "found": len(targets),
        "unblocked": len(unblocked),
        "credited": len(credited),
        "failed": len(failed),
    }
    # Znacznik tylko po przebiegu BEZ błędów: wiersz, który padł, dostanie
    # kolejną próbę przy następnym starcie (odblokowane są już `active`, więc
    # ponowny przebieg ich nie dotknie).
    if only_stage_ids is None and not failed:
        db.add(
            AppSetting(
                key=PROMOTION_MARKER,
                value={
                    **summary,
                    "unblocked_stage_ids": unblocked,
                    "credited_stage_ids": credited,
                    "failed_stage_ids": failed,
                },
            )
        )
    await db.flush()
    logger.info("pending verification promotion: %s", summary)
    return summary
