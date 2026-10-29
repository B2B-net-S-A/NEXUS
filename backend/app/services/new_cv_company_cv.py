"""CV do klienta z nowego CV kandydata (29.10.2026, decyzje Artura D1 = A).

Zgłoszenie: rekruter dostaje od kandydata nowe CV (LinkedIn, mail), wgrywa je
w rekrutacji, a CV do klienta dalej opisuje stary plik — trzeba było kliknąć
„Wygeneruj od nowa” i potem „Użyj nowej wersji”. Od tej daty wgranie nowego CV
w rekrutacji (`POST …/stages/{id}/cv/original/upload`) mówi, co dzieje się z CV
do klienta pary (``company_cv`` w odpowiedzi):

* ``regenerating`` — CV do klienta to szkic z generatora, którego od podpięcia
  nikt nie zmienił: nowa wersja generuje się od razu z nowego pliku, z tymi
  samymi źródłami, trybem i językiem, i po zakończeniu sama zastępuje szkic
  (poprzedni zostaje w migawce — „Cofnij” = „Wróć do poprzedniej”);
* ``ask`` — CV ktoś poprawiał, wybrał, wczytał z Worda albo zatwierdził:
  panel pyta „Generuj z nowego CV / Zostaw obecne”, bo automat skasowałby
  czyjąś pracę. „Generuj” = `POST …/cv/branded/regenerate-from-original`;
* ``confirm`` — CV do klienta jeszcze nie ma: reguła z 21.10.2026 zostaje
  (CV po trzech potwierdzeniach), nowy plik jest od razu potwierdzonym plikiem;
* ``locked`` — karta na „CV wysłane” albo dalej: klient ma już CV tej osoby;
* ``none`` — klient bierze własny formularz zamiast CV firmowego (0521).

Podmiana po generacji (`replace_after_regeneration`) dzieje się tylko wtedy,
gdy szkic ma dalej tę rewizję, którą zapisaliśmy przy zleceniu — edycja
w trakcie generacji wygrywa, a gotowa wersja zostaje na liście
(„Użyj nowej wersji” w ramce `CompanyCvStaleNotice`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Optional

from sqlalchemy import select

from app.models.activity import Activity
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.cv_generated_document import CvGeneratedDocument

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

CompanyCvPlan = Literal["regenerating", "ask", "confirm", "locked", "none"]

# Zlecenie generacji po nowym CV — jego `details` niosą rewizję szkicu, przy
# której wolno podmienić szkic gotową wersją.
INTENT_ACTION = "branded_cv_regeneration_after_new_cv"
REPLACE_ACTION = "branded_cv_replaced_after_new_cv"

# Szkic podpięty z generatora bez ręki człowieka: automat, ręczna generacja
# z karty (podpina worker) i nasza podmiana.
GENERATED_ATTACH_ACTIONS = (
    "branded_cv_attached_by_automation",
    "branded_cv_attached_after_generation",
    REPLACE_ACTION,
)


@dataclass(frozen=True)
class CompanyCvAfterNewCv:
    plan: CompanyCvPlan
    stage_id: Optional[int] = None
    status: Optional[str] = None
    generated_id: Optional[int] = None
    durable_id: Optional[int] = None


async def pair_cv_row(
    db: "AsyncSession", csv_row: CandidateStageCV
) -> CandidateStageCV:
    """Wiersz z CV do klienta pary, zablokowany — jak karta (`cvStageId`).

    Bieżący wiersz etapu, a gdy pusty — wiersz sprzed ruchu karty ze szkicem
    albo zatwierdzonym CV.
    """
    from app.api.candidate_stage_cv import _branded_cv_summary_for_pair

    target_stage_id = csv_row.candidate_stage_id
    if (csv_row.branded_status or "none") == "none":
        pair = await _branded_cv_summary_for_pair(
            db, csv_row.candidate_id, csv_row.job_id
        )
        if pair.stage_id is not None:
            target_stage_id = pair.stage_id
    return await db.scalar(
        select(CandidateStageCV)
        .where(CandidateStageCV.candidate_stage_id == target_stage_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def is_untouched_generated_draft(
    db: "AsyncSession", csv: CandidateStageCV
) -> bool:
    """Szkic z generatora, którego od podpięcia nikt nie zmienił.

    Szersze niż `client_cv_upload.is_untouched_auto_cv`: od 21.10.2026 CV
    powstaje po potwierdzeniu w karcie (`origin="manual"`), a automat nie
    generuje — samo auto-CV prawie nie występuje. Każda zmiana treści podbija
    ``edit_revision``; zgoda RODO jej nie podbija, a nowa generacja by ją
    zgubiła — wtedy pytamy.
    """
    if (
        csv.branded_status != "draft"
        or not csv.generated_document_id
        or csv.branded_consent_content is not None
    ):
        return False
    attached = await db.scalar(
        select(Activity.id)
        .where(
            Activity.entity_type == "candidate_stage_cv",
            Activity.entity_id == csv.id,
            Activity.action.in_(GENERATED_ATTACH_ACTIONS),
            Activity.details["edit_revision"].astext == str(csv.edit_revision or 0),
        )
        .limit(1)
    )
    return attached is not None


async def locked_after_send(db: "AsyncSession", csv: CandidateStageCV) -> bool:
    from app.services import integration_cv
    from app.services.candidate_claim import stage_column

    stage = await integration_cv.current_stage(
        db, candidate_id=csv.candidate_id, job_id=csv.job_id
    )
    return stage is not None and integration_cv.locked_after_send(
        await stage_column(db, stage)
    )


async def _client_takes_form(db: "AsyncSession", job_id: int) -> bool:
    from app.models.job import Job
    from app.services import client_form_status

    job = await db.get(Job, job_id)
    if job is None or job.client_id is None:
        return False
    return await client_form_status.client_takes_client_form(db, job.client_id)


async def enqueue_regeneration(
    db: "AsyncSession",
    *,
    target: CandidateStageCV,
    document_id: int,
    user_id: int,
    automatic: bool,
) -> tuple[int, int]:
    """Nowa wersja CV do klienta z pliku ``document_id`` — jak ostatnia generacja.

    Źródła AI, tryb, język i „anonimowe” bierzemy z dokumentu, z którego jest
    szkic (to rekruter je potwierdził); bez niego — domyślne generatora.
    Walidacja reguły klienta jest wspólna z kliknięciem (`enqueue_candidate_generation`),
    więc odmowa leci jako ``HTTPException`` przed naliczeniem kwoty AI.
    Bez commitu. Zwraca ``(id dokumentu, id trwałego zadania)``.
    """
    from app.api.cv_generator_b2b import (
        derived_project_ref,
        enqueue_candidate_generation,
    )
    from app.models.candidate import Candidate
    from app.models.job import Job
    from app.models.recruitment_pipeline import CandidateStage
    from app.services.cv_generator_b2b.client_rules import resolve_client_rule
    from app.services.cv_generator_b2b.prompts import DEFAULT_CONTENT_MODE

    stage = await db.get(CandidateStage, target.candidate_stage_id)
    candidate = await db.get(Candidate, target.candidate_id)
    job = await db.get(Job, target.job_id)
    previous = (
        await db.get(CvGeneratedDocument, target.generated_document_id)
        if target.generated_document_id
        else None
    )
    payload = (previous.render_payload if previous is not None else None) or {}
    sources = (
        payload.get("ai_sources")
        if isinstance(payload.get("ai_sources"), dict)
        else None
    )
    rule = await resolve_client_rule(db, job.client_id if job else None)
    generated_id, durable_id, _name = await enqueue_candidate_generation(
        db,
        user_id=user_id,
        candidate=candidate,
        stage=stage,
        client_id=job.client_id if job else None,
        cv_document_id=document_id,
        language=(previous.language if previous is not None else None)
        or target.branded_language
        or "pl",
        blind_cv=bool(previous.blind)
        if previous is not None
        else target.branded_template == "blind",
        content_mode=(previous.content_mode if previous is not None else None)
        or DEFAULT_CONTENT_MODE,
        project_ref=derived_project_ref(rule, job, ""),
        languages="one",
        attach_stage_draft=True,
        sources=sources,
    )
    db.add(
        Activity(
            entity_type="candidate_stage_cv",
            entity_id=target.id,
            action=INTENT_ACTION,
            user_id=user_id,
            details={
                "candidate_stage_id": target.candidate_stage_id,
                "generated_document_id": generated_id,
                "source_document_id": document_id,
                "edit_revision": target.edit_revision or 0,
                "prior_generated_document_id": target.generated_document_id,
                "automatic": automatic,
            },
        )
    )
    return generated_id, durable_id


async def plan_after_new_cv(
    db: "AsyncSession",
    *,
    csv_row: CandidateStageCV,
    document_id: int,
    user_id: int,
) -> CompanyCvAfterNewCv:
    """Co zrobić z CV do klienta pary po nowym CV (bez commitu).

    Wołane w transakcji wgrania, po kopii oryginału. Odmowa generacji
    (reguła klienta, brak numeru projektu) nie psuje wgrania: plik jest już
    w profilu i w rekrutacji, panel pyta jak przy CV poprawianym.
    """
    from fastapi import HTTPException

    if await _client_takes_form(db, csv_row.job_id):
        return CompanyCvAfterNewCv(plan="none")
    target = await pair_cv_row(db, csv_row)
    if target is None:
        return CompanyCvAfterNewCv(plan="confirm", stage_id=csv_row.candidate_stage_id)
    status = target.branded_status or "none"
    base = dict(stage_id=target.candidate_stage_id, status=status)
    if await locked_after_send(db, target):
        return CompanyCvAfterNewCv(plan="locked", **base)
    if status == "none":
        return CompanyCvAfterNewCv(plan="confirm", **base)
    if not await is_untouched_generated_draft(db, target):
        return CompanyCvAfterNewCv(plan="ask", **base)
    try:
        async with db.begin_nested():
            generated_id, durable_id = await enqueue_regeneration(
                db,
                target=target,
                document_id=document_id,
                user_id=user_id,
                automatic=True,
            )
    except HTTPException as exc:
        logger.info(
            "[new_cv] stage=%s regeneration refused: %s",
            target.candidate_stage_id,
            exc.status_code,
        )
        return CompanyCvAfterNewCv(plan="ask", **base)
    return CompanyCvAfterNewCv(
        plan="regenerating", generated_id=generated_id, durable_id=durable_id, **base
    )


async def _source_still_current(
    db: "AsyncSession", csv: CandidateStageCV, intent: Activity
) -> bool:
    """Plik zlecenia to dalej „Oryginał CV” pary i nie ma nowszego zlecenia.

    Przegląd kodu 29.10.2026: bramka tożsamości biegnie po wgraniu i może
    odesłać plik do kwarantanny (kopie etapu wracają do poprzedniego CV),
    a dwa szybkie wgrania dają dwa zlecenia z tą samą rewizją — bez tego
    CV do klienta mogło powstać z cudzego albo z nieaktualnego pliku.
    """
    from app.models.candidate_document import CandidateDocument

    newer = await db.scalar(
        select(Activity.id)
        .where(
            Activity.entity_type == "candidate_stage_cv",
            Activity.entity_id == csv.id,
            Activity.action == INTENT_ACTION,
            Activity.id > intent.id,
        )
        .limit(1)
    )
    if newer is not None:
        return False
    source_sha = await db.scalar(
        select(CandidateDocument.content_sha256).where(
            CandidateDocument.id == (intent.details or {}).get("source_document_id"),
            CandidateDocument.source_deleted_at.is_(None),
        )
    )
    # Najnowsza kopia „Oryginał CV” pary — ruch karty zakłada nowy wiersz etapu.
    original_sha = await db.scalar(
        select(CandidateStageCV.original_cv_sha256)
        .where(
            CandidateStageCV.candidate_id == csv.candidate_id,
            CandidateStageCV.job_id == csv.job_id,
            CandidateStageCV.original_cv_sha256.isnot(None),
        )
        .order_by(
            CandidateStageCV.original_snapshot_at.desc().nulls_last(),
            CandidateStageCV.id.desc(),
        )
        .limit(1)
    )
    return bool(source_sha) and source_sha == original_sha


async def replace_after_regeneration(
    db: "AsyncSession",
    csv: CandidateStageCV,
    generated: CvGeneratedDocument,
    *,
    user_id: int,
) -> bool:
    """Gotowa generacja po nowym CV zastępuje szkic — gdy nikt go w międzyczasie nie ruszał.

    Wołający trzyma blokadę wiersza i sprawdził, że dokument jest gotowy i tej
    samej pary. Bez commitu. ``False`` = nie było zlecenia albo szkic się
    zmienił (wtedy nowa wersja czeka na „Użyj nowej wersji”).
    """
    from app.api.candidate_stage_cv import apply_generated_to_stage_cv
    from app.services.cv_draft_snapshots import snapshot_draft

    intent = await db.scalar(
        select(Activity)
        .where(
            Activity.entity_type == "candidate_stage_cv",
            Activity.entity_id == csv.id,
            Activity.action == INTENT_ACTION,
            Activity.details["generated_document_id"].astext == str(generated.id),
        )
        .limit(1)
    )
    if intent is None:
        return False
    details = intent.details or {}
    if (
        csv.branded_status == "none"
        or details.get("edit_revision") != (csv.edit_revision or 0)
        or details.get("prior_generated_document_id") != csv.generated_document_id
        # Zgoda RODO dołączona w trakcie generacji nie podbija rewizji, a nowa
        # wersja by ją zgubiła — przy podmianie automatycznej pytamy wtedy człowieka.
        or (details.get("automatic") and csv.branded_consent_content is not None)
        or not await _source_still_current(db, csv, intent)
        or await locked_after_send(db, csv)
    ):
        return False
    snapshot_draft(db, csv, user_id=user_id, reason="replaced")
    await apply_generated_to_stage_cv(
        db, csv, generated, user_id=user_id, activity_action=REPLACE_ACTION
    )
    return True
