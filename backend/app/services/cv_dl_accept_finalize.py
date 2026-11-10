"""Akceptacja Delivery Leada do kolejki Cpro zatwierdza CV etapu (10.11.2026).

Zgłoszenie osoby od Cpro: CV pobierane z kolejki „Do wrzucenia do Cpro” miały
w nazwie „SZKIC_”, bo nikt nie kliknął „Zatwierdź”, a przycisk „CV” robi wtedy
plik z bieżącej treści edytora (`draft_docx_filename`). Decyzja Artura
(wariant A): „Akceptuj — do Cpro” zatwierdza szkic tą samą drogą co ręczne
„Zatwierdź” (`finalize_stage_cv`), z Delivery Leadem jako zatwierdzającym.

Zatwierdzenie jest dodatkiem do ruchu: każda odmowa (kontrola treści przed
zatwierdzeniem, puste CV, błąd renderu) zostawia szkic, ruch przechodzi,
a kolejka Cpro pokazuje przy osobie „CV niezatwierdzone przez rekrutera”
(`CproQueueCv.draft`). Odmowa trafia do historii zdarzeń z kodem powodu.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.candidate_stage_cv import CandidateStageCV

logger = logging.getLogger(__name__)

APPROVED_VIA = "dl_accept"
SKIPPED_ACTION = "branded_cv_dl_accept_not_finalized"


def _reason(exc: HTTPException) -> str:
    detail = exc.detail
    if isinstance(detail, dict) and detail.get("code"):
        return str(detail["code"])
    return f"http_{exc.status_code}"


async def finalize_on_dl_accept(
    db: AsyncSession, *, candidate_id: int, job_id: int, user_id: int
) -> Optional[str]:
    """Zatwierdź szkic CV pary, który pobierze osoba od Cpro. Bez commitu.

    CV pary wybiera ta sama reguła co kolejka Cpro
    (`move_requirements.company_cv_refs`): zatwierdzone przed szkicem. Gdy
    kolejka i tak wyda wersję zatwierdzoną albo nie ma CV etapu — nic.
    Zwraca ``"finalized"``, kod powodu odmowy albo ``None``.
    """
    from app.services.candidate_stage_cv_service import finalize_stage_cv
    from app.services.move_requirements import company_cv_refs

    ref = (await company_cv_refs(db, [(candidate_id, job_id)])).get(
        (candidate_id, job_id)
    )
    if ref is None or ref["source"] != "branded_draft":
        return None
    csv = await db.scalar(
        select(CandidateStageCV)
        .where(CandidateStageCV.candidate_stage_id == ref["stage_id"])
        .with_for_update()
    )
    if csv is None or csv.branded_status != "draft":
        return None
    csv_id, stage_id = csv.id, csv.candidate_stage_id
    try:
        async with db.begin_nested():
            await finalize_stage_cv(
                db,
                csv,
                csv.branded_draft_html or "",
                user_id,
                activity_details={"approved_via": APPROVED_VIA},
            )
        return "finalized"
    except HTTPException as exc:
        reason = _reason(exc)
        logger.info("[cv_dl_accept] CV etapu %s zostaje szkicem: %s", stage_id, reason)
    except Exception:  # noqa: BLE001 — zatwierdzenie nie może cofnąć akceptacji
        reason = "error"
        logger.exception("[cv_dl_accept] CV etapu %s zostaje szkicem", stage_id)
    db.add(
        Activity(
            entity_type="candidate_stage_cv",
            entity_id=csv_id,
            action=SKIPPED_ACTION,
            user_id=user_id,
            details={
                "candidate_stage_id": stage_id,
                "job_id": job_id,
                "reason": reason,
            },
        )
    )
    return reason
