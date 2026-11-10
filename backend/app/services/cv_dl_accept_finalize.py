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

Kontrola w tle (10.11.2026, decyzja Artura). Gdy treść wymaga płatnej
kontroli AI (409 `cv_review_required`), akceptacja zakłada zadanie kontroli
(`cv_approval_queue.enqueue_review`, właściciel i koszt = DL) i znacznik
`REVIEW_QUEUED_ACTION` z numerem zadania. Worker po zapisaniu wyniku woła
`finalize_after_review`. To jedyne miejsce, gdzie wynik kontroli prowadzi do
zatwierdzenia bez kliknięcia, więc krok pod blokadą wiersza CV sprawdza:
znacznik akceptacji dla TEGO zadania, szkic, wynik `verified`, tę samą
rewizję i dokument generatora. Potem idzie zwykłym `finalize_stage_cv`,
które drugi raz szuka wyniku kontroli po skrócie treści — inna treść niż
sprawdzona dostaje 409 i zostaje szkicem. Kontroli nie powtarzamy.
"""

from __future__ import annotations

import logging
from typing import Optional
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.candidate_stage_cv import CandidateStageCV

logger = logging.getLogger(__name__)

APPROVED_VIA = "dl_accept"
SKIPPED_ACTION = "branded_cv_dl_accept_not_finalized"
REVIEW_QUEUED_ACTION = "branded_cv_dl_accept_review_queued"
REVIEW_REQUIRED = "cv_review_required"


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
    extra = {}
    if reason == REVIEW_REQUIRED:
        refused = await _queue_review(db, csv_id, job_id=job_id, user_id=user_id)
        if refused is None:
            return "review_queued"
        extra["review_not_queued"] = refused
    _skipped(
        db,
        csv_id,
        stage_id=stage_id,
        job_id=job_id,
        user_id=user_id,
        reason=reason,
        **extra,
    )
    return reason


def _skipped(db, csv_id, *, stage_id, job_id, user_id, reason, **extra) -> None:
    details = {
        "candidate_stage_id": stage_id,
        "job_id": job_id,
        "reason": reason,
        **extra,
    }
    db.add(
        Activity(
            entity_type="candidate_stage_cv",
            entity_id=csv_id,
            action=SKIPPED_ACTION,
            user_id=user_id,
            details=details,
        )
    )


async def _queue_review(
    db: AsyncSession, csv_id: int, *, job_id: int, user_id: int
) -> Optional[str]:
    """Zadanie kontroli bieżącej treści szkicu na koszt DL-a. Bez commitu.

    Zadanie wejdzie do kolejki workera razem z ruchem (commit wołającego).
    ``None`` = zadanie założone; inaczej kod odmowy (brak źródła, blokada
    danych kandydata, zmiana w innej sesji).
    """
    from app.schemas.candidate_stage_cv import CVBrandedReview
    from app.services.cv_approval_queue import enqueue_review

    try:
        async with db.begin_nested():
            # SAVEPOINT z nieudanym zatwierdzeniem wygasił obiekt — czytamy go
            # od nowa, dalej pod blokadą wiersza z początku.
            csv = await db.scalar(
                select(CandidateStageCV)
                .where(CandidateStageCV.id == csv_id)
                .execution_options(populate_existing=True)
            )
            stage_id = csv.candidate_stage_id
            state = await enqueue_review(
                db,
                csv,
                CVBrandedReview(
                    expected_revision=csv.edit_revision or 0,
                    content_html=csv.branded_draft_html or "",
                    request_key=uuid4(),
                ),
                user_id,
            )
            if state.get("review_id") is None or state["status"] != "queued":
                raise HTTPException(409, {"code": f"review_{state['status']}"})
            db.add(
                Activity(
                    entity_type="candidate_stage_cv",
                    entity_id=csv_id,
                    action=REVIEW_QUEUED_ACTION,
                    user_id=user_id,
                    details={
                        "candidate_stage_id": stage_id,
                        "job_id": job_id,
                        "review_id": state["review_id"],
                        "edit_revision": csv.edit_revision or 0,
                    },
                )
            )
        return None
    except HTTPException as exc:
        refused = _reason(exc)
        logger.info(
            "[cv_dl_accept] kontrola CV %s w tle nie ruszyła: %s", csv_id, refused
        )
    except Exception:  # noqa: BLE001 — kontrola nie może cofnąć akceptacji
        refused = "error"
        logger.exception("[cv_dl_accept] kontrola CV %s w tle nie ruszyła", csv_id)
    return refused


async def finalize_after_review(session_factory, review_id: int) -> Optional[str]:
    """Po zakończonej kontroli: zatwierdź CV, które zaakceptował DL. Commituje.

    Woła worker kontroli (`cv_approval_worker`) po zapisaniu wyniku, każdego
    zakończonego. Zadanie bez znacznika akceptacji (ręczne „Zatwierdź”
    w edytorze) — nic: tam zatwierdza przeglądarka. Zwraca ``"finalized"``,
    kod powodu odmowy albo ``None``.
    """
    from app.models.cv_approval_job import CvApprovalJob
    from app.services.candidate_stage_cv_service import finalize_stage_cv

    async with session_factory() as db:
        job = await db.get(CvApprovalJob, review_id)
        if job is None or job.candidate_stage_cv_id is None:
            return None
        marker = await db.scalar(
            select(Activity)
            .where(
                Activity.entity_type == "candidate_stage_cv",
                Activity.entity_id == job.candidate_stage_cv_id,
                Activity.action == REVIEW_QUEUED_ACTION,
                Activity.details["review_id"].as_integer() == review_id,
            )
            .limit(1)
        )
        if marker is None:
            return None
        csv = await db.scalar(
            select(CandidateStageCV)
            .where(CandidateStageCV.id == job.candidate_stage_cv_id)
            .with_for_update()
        )
        if csv is None or csv.branded_status != "draft":
            # Ktoś zatwierdził ręcznie w międzyczasie — cel osiągnięty.
            return None
        csv_id, stage_id = csv.id, csv.candidate_stage_id
        job_status, expected = job.status, job.expected_revision
        user_id, pair_job_id = marker.user_id, (marker.details or {}).get("job_id")
        if job_status != "verified":
            reason = f"review_{job_status}"
        elif (
            csv.edit_revision != expected
            or csv.generated_document_id != job.generated_document_id
        ):
            reason = "draft_changed"
        else:
            try:
                async with db.begin_nested():
                    await finalize_stage_cv(
                        db,
                        csv,
                        csv.branded_draft_html or "",
                        user_id,
                        activity_details={
                            "approved_via": APPROVED_VIA,
                            "review_id": review_id,
                        },
                    )
                await db.commit()
                return "finalized"
            except HTTPException as exc:
                reason = _reason(exc)
                if reason == REVIEW_REQUIRED:
                    reason = "draft_changed"
            except Exception:  # noqa: BLE001 — szkic zostaje, worker żyje dalej
                reason = "error"
                logger.exception(
                    "[cv_dl_accept] CV etapu %s po kontroli zostaje szkicem", stage_id
                )
        logger.info(
            "[cv_dl_accept] CV etapu %s po kontroli zostaje szkicem: %s",
            stage_id,
            reason,
        )
        _skipped(
            db,
            csv_id,
            stage_id=stage_id,
            job_id=pair_job_id,
            user_id=user_id,
            reason=reason,
            review_id=review_id,
        )
        await db.commit()
        return reason


async def review_pending_stage_ids(db: AsyncSession, stage_ids: list[int]) -> set[int]:
    """Etapy, których szkic czeka na kontrolę w tle po akceptacji DL-a.

    Kolejka Cpro mówi wtedy „Sprawdzamy CV”, a nie „niezatwierdzone”: za
    chwilę ten sam przycisk da plik bez „SZKIC_”. Zadanie dla starszej
    rewizji (szkic zmieniony) już niczego nie zatwierdzi, więc się nie liczy.
    """
    from app.models.cv_approval_job import CvApprovalJob

    if not stage_ids:
        return set()
    rows = await db.scalars(
        select(CandidateStageCV.candidate_stage_id)
        .join(CvApprovalJob, CvApprovalJob.candidate_stage_cv_id == CandidateStageCV.id)
        .join(
            Activity,
            (Activity.entity_type == "candidate_stage_cv")
            & (Activity.entity_id == CandidateStageCV.id)
            & (Activity.action == REVIEW_QUEUED_ACTION)
            & (Activity.details["review_id"].as_integer() == CvApprovalJob.id),
        )
        .where(
            CandidateStageCV.candidate_stage_id.in_(stage_ids),
            CandidateStageCV.branded_status == "draft",
            CvApprovalJob.status.in_(("queued", "running")),
            CvApprovalJob.expected_revision == CandidateStageCV.edit_revision,
        )
    )
    return set(rows.all())
