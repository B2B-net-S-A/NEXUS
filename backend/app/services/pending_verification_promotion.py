"""Jednorazowe zaliczenie weryfikacji, które utknęły w stanie „Pending".

Decyzja Artura 17.09.2026: bramka „Pending" (stawka ponad budżet przy ruchu na
„Zweryfikowany") jest wyłączona (`PENDING_VERIFICATION_ENABLED=False`), a UI
akceptacji zostało usunięte. Karty zapisane wcześniej jako `pending` tablica
pokazuje jak aktywne, ale w bazie zostawały `pending` — więc nie liczyły się do
KPI weryfikacji i nikt nie dostawał zaliczenia pierwszego weryfikatora.

Blok robi dla każdej takiej karty dokładnie to, co robiła ręczna akceptacja
(`accept_pending_verification`): `verification_status=active`, znacznik czasu
akceptacji i `record_accepted_verification` z weryfikatorem = osoba, która
przesunęła kartę. Różnice wobec akceptacji ręcznej, obie świadome:

* `approved_by` zostaje puste — nikt tej decyzji nie podjął, podjęła ją zmiana
  polityki; paragon w `app_settings` mówi, kiedy i ile;
* nie wymagamy, żeby karta była aktualnym etapem procesu — karta przesunięta
  dalej (możliwe od wyłączenia bramki) też powinna się liczyć jako weryfikacja.

Uruchamiane raz z `entrypoint.sh` (alembic na prodzie bywa osierocony, a logika
jest ORM-owa). Advisory lock + znacznik → drugi start kończy się natychmiast.
Przy WŁĄCZONEJ bramce blok nic nie robi i nie stawia znacznika: wtedy `pending`
ma znaczenie i akceptuje go człowiek. Paragon niesie wyłącznie liczby i ID.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.recruitment_pipeline import (
    CandidateStage,
    PipelineStage,
    VerificationStatus,
)

logger = logging.getLogger(__name__)

PROMOTION_MARKER = "pending_verification_promotion_2026_09_17"


async def run_pending_verification_promotion(
    db: AsyncSession,
    *,
    only_stage_ids: Optional[set[int]] = None,
) -> Optional[dict[str, Any]]:
    """Zalicz wszystkie weryfikacje `pending`. ``None`` = nic do zrobienia.

    Wołający commituje. ``only_stage_ids`` zawęża przebieg — wyłącznie dla
    testów, które nie mogą ruszać cudzych wierszy we wspólnej bazie (i wtedy
    znacznik NIE jest stawiany).
    """
    from app.services.priority_work_policy import invalidate_milestone_counts
    from app.services.recruitment_process_commands import (
        promote_legacy_pending_verification,
    )

    if settings.PENDING_VERIFICATION_ENABLED:
        return None
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": PROMOTION_MARKER},
    )
    if only_stage_ids is None and await db.get(AppSetting, PROMOTION_MARKER):
        return None

    query = (
        select(CandidateStage.id, CandidateStage.candidate_id)
        .where(
            CandidateStage.stage == PipelineStage.verified,
            CandidateStage.verification_status == VerificationStatus.pending,
        )
        .order_by(CandidateStage.id)
    )
    if only_stage_ids is not None:
        query = query.where(CandidateStage.id.in_(only_stage_ids))
    targets = (await db.execute(query)).all()

    now = datetime.now(timezone.utc)
    promoted: list[int] = []
    credited: list[int] = []
    failed: list[int] = []
    for stage_id, candidate_id in targets:
        try:
            async with db.begin_nested():
                # Ta sama kolejność blokad co akceptacja ręczna i `/move`
                # (kandydat → etap), żeby nie zakleszczyć się z żywym ruchem.
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
                promoted.append(stage_id)
        except Exception:  # noqa: BLE001 — jeden zepsuty wiersz nie blokuje reszty
            logger.exception("pending verification promotion failed for %s", stage_id)
            failed.append(stage_id)
    invalidate_milestone_counts()

    summary: dict[str, Any] = {
        "executed_at": now.isoformat(),
        "found": len(targets),
        "promoted": len(promoted),
        "credited": len(credited),
        "failed": len(failed),
    }
    # Znacznik tylko po przebiegu BEZ błędów: wiersz, który padł, dostanie
    # kolejną próbę przy następnym starcie (zaliczone już są `active`, więc
    # ponowny przebieg ich nie dotknie).
    if only_stage_ids is None and not failed:
        db.add(
            AppSetting(
                key=PROMOTION_MARKER,
                value={
                    **summary,
                    "promoted_stage_ids": promoted,
                    "failed_stage_ids": failed,
                },
            )
        )
    await db.flush()
    logger.info("pending verification promotion: %s", summary)
    return summary
