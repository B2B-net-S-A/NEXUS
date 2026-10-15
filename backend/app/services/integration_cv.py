"""CV dla klienta przez API v1 — para, ustawienia jak karta, stan generacji.

Trasy (``api/integrations_v1/cv.py``) generują CV tą samą ścieżką co karta
„CV do klienta” (``cv_generator_b2b.enqueue_candidate_generation``). Karta
wysyła ustawienia wyliczone w przeglądarce (``useCvGenerator``); klucz API
ich nie wybiera, więc ten moduł liczy je na serwerze tą samą regułą:

* plik CV — główny plik kandydata (``list_candidate_cv_sources``, główny
  pierwszy), jak oryginał w „Z czego powstało”;
* język — wymuszony regułą klienta, a gdy klient chce obu wersji — „Obie”;
  inaczej polski (``defaultLanguageChoice`` + ``languagePayload``);
* tryb — „Pod rekrutację”, gdy rekrutacja ma Championa, inaczej Redakcja;
  „basic”, gdy polityka centralna daje go domyślnie (sufit klienta). Resztę
  (sufit, brak kompletnego Championa) rozstrzyga wspólna ścieżka;
* stanowisko — tytuł rekrutacji; numer projektu — jak ``GET /policy``;
* źródła dla AI — wybór bieżącej wersji CV etapu (``last_used``), inaczej
  domyślne serwera.

CV pary to CV wiersza bieżącej karty, a gdy go nie ma — CV pary z innego
wiersza (``_branded_cv_summary_for_pair``: zatwierdzone przed szkicem), jak
panel osoby (``useStageBrandedCv``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate_stage_cv import CandidateStageCV
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.cv_generation_job import CvGenerationJob
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage
from app.services.board_stage_badges import BOARD_COLUMN_ORDER

# Od „CV wysłane” karta nie generuje i nie podmienia CV (`lockedAfterSend`,
# `isAtClientColumn` we froncie): CV jest już u klienta.
LOCKED_FROM_COLUMN = "cv_sent"
MAX_GENERATIONS = 5
NO_CV_FILE_MESSAGE = (
    "Kandydat nie ma w profilu pliku CV — wgraj CV, zanim wygenerujesz CV dla klienta."
)

OverallStatus = Literal["none", "processing", "ready", "failed"]


def locked_after_send(column: Optional[str]) -> bool:
    """Karta stoi na „CV wysłane” albo dalej (bez „Zamkniętych”)."""
    if column not in BOARD_COLUMN_ORDER:
        return False
    return BOARD_COLUMN_ORDER.index(column) >= BOARD_COLUMN_ORDER.index(
        LOCKED_FROM_COLUMN
    )


def language_request(
    forced: Optional[str], requires_both: bool
) -> tuple[Literal["pl", "en"], Literal["one", "both"]]:
    """``(language, languages)`` żądania — domyślny wybór formularza."""
    if forced in ("pl", "en"):
        return forced, "one"  # type: ignore[return-value]
    if requires_both:
        return "pl", "both"
    return "pl", "one"


def requested_content_mode(has_champion: bool, policy_default: Optional[str]) -> str:
    """Tryb, o który prosi formularz: Champion → „Pod rekrutację”, bez niego
    Redakcja; „basic” z polityki centralnej wygrywa (``capBasic``)."""
    if policy_default == "basic":
        return "basic"
    return "tailored" if has_champion else "polished"


def overall_status(
    cv_state: str, latest_generation_status: Optional[str]
) -> OverallStatus:
    """Jedno słowo dla integracji: generacja w toku, CV jest, porażka, nic."""
    if latest_generation_status == "processing":
        return "processing"
    if cv_state in ("draft", "finalized"):
        return "ready"
    if latest_generation_status == "failed":
        return "failed"
    return "none"


@dataclass(frozen=True)
class GenerationSettings:
    cv_document_id: int
    language: Literal["pl", "en"]
    languages: Literal["one", "both"]
    content_mode: str
    project_ref: str
    position: str
    sources: Optional[dict[str, bool]]


async def current_stage(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> Optional[CandidateStage]:
    """Bieżący wiersz karty pary (``moved_at``, potem ``id`` — jak Tablica)."""
    return await db.scalar(
        select(CandidateStage)
        .where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == job_id,
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        .limit(1)
    )


async def pair_stage_cv(
    db: AsyncSession, *, candidate_id: int, job_id: int, current_stage_id: int
) -> Optional[CandidateStageCV]:
    """CV firmowe pary: wiersza bieżącej karty, a bez niego — z innego wiersza."""
    from app.api.candidate_stage_cv import _branded_cv_summary_for_pair

    own = await db.scalar(
        select(CandidateStageCV).where(
            CandidateStageCV.candidate_stage_id == current_stage_id
        )
    )
    if own is not None and own.branded_status in ("draft", "finalized"):
        return own
    pair = await _branded_cv_summary_for_pair(db, candidate_id, job_id)
    if pair.stage_id is None:
        return None
    return await db.scalar(
        select(CandidateStageCV).where(
            CandidateStageCV.candidate_stage_id == pair.stage_id
        )
    )


async def last_used_sources(
    db: AsyncSession, stage_id: int
) -> Optional[dict[str, bool]]:
    """Źródła dla AI bieżącej wersji CV etapu — jak ``last_used`` w
    ``GET …/cv/ai-sources``; ``None`` = domyślne serwera."""
    from app.services.cv_generator_b2b.standalone_service import AI_SOURCE_DEFAULTS

    payload = await db.scalar(
        select(CvGeneratedDocument.render_payload)
        .join(
            CandidateStageCV,
            CandidateStageCV.generated_document_id == CvGeneratedDocument.id,
        )
        .where(CandidateStageCV.candidate_stage_id == stage_id)
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("ai_sources"), dict):
        return None
    return {
        key: bool(payload["ai_sources"].get(key, default))
        for key, default in AI_SOURCE_DEFAULTS.items()
    }


async def generation_settings(
    db: AsyncSession, *, job: Job, stage: CandidateStage
) -> GenerationSettings:
    """Ustawienia, które formularz karty „CV do klienta” zaznacza sam."""
    from app.api.cv_generator_b2b import policy_project_ref
    from app.models.client import Client
    from app.services.cv_generator_b2b import central_policies
    from app.services.cv_generator_b2b.client_rules import (
        resolve_client_rule,
        snapshot_rule,
    )
    from app.services.cv_generator_b2b.standalone_service import (
        StandaloneGenerationError,
        champion_present,
        list_candidate_cv_sources,
    )

    try:
        documents = await list_candidate_cv_sources(db, stage.candidate_id)
    except StandaloneGenerationError as err:
        raise HTTPException(404, detail="Kandydat nie istnieje.") from err
    if not documents:
        raise HTTPException(
            422, detail={"error": "no_cv_file", "message": NO_CV_FILE_MESSAGE}
        )
    rule = await resolve_client_rule(db, job.client_id)
    snapshot = snapshot_rule(rule)
    language, languages = language_request(
        getattr(snapshot, "cv_language", None),
        bool(getattr(snapshot, "requires_en_copy", False)),
    )
    policy_default: Optional[str] = None
    project_ref = ""
    if central_policies.enabled() and rule is not None:
        client = await db.get(Client, job.client_id)
        policy_default, _notice = central_policies.automatic_mode_decision(
            job,
            getattr(client, "cv_content_mode_cap", None),
            policy=rule.managed_policy,
        )
        project_ref = policy_project_ref(rule, job) or ""
    return GenerationSettings(
        cv_document_id=documents[0]["id"],
        language=language,
        languages=languages,
        content_mode=requested_content_mode(champion_present(job), policy_default),
        project_ref=project_ref,
        position=(job.title or "").strip(),
        sources=await last_used_sources(db, stage.id),
    )


async def generation_in_progress(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> bool:
    """Generacja CV pary czeka w kolejce albo trwa (zadanie ``queued``/``running``).

    Wiersz „processing” bez żywego zadania (przerwany deployem) nie blokuje.
    """
    found = await db.scalar(
        select(CvGeneratedDocument.id)
        .join(CvGenerationJob, CvGenerationJob.generated_id == CvGeneratedDocument.id)
        .where(
            CvGeneratedDocument.candidate_id == candidate_id,
            CvGeneratedDocument.job_id == job_id,
            CvGeneratedDocument.status == "processing",
            CvGenerationJob.status.in_(("queued", "running")),
        )
        .limit(1)
    )
    return found is not None


async def pair_generations(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> list[dict[str, Any]]:
    """Ostatnie generacje CV pary (od najnowszej) — stan, język, podpięcie.

    Bez komunikatu błędu: niesie surowy tekst wyjątku dostawcy. Zamiast niego
    kod diagnostyczny zadania (``[a-z_]``, ``_finalize_failure``).
    """
    rows = (
        await db.execute(
            select(
                CvGeneratedDocument.id,
                CvGeneratedDocument.status,
                CvGeneratedDocument.language,
                CvGeneratedDocument.content_mode,
                CvGeneratedDocument.origin,
                CvGeneratedDocument.created_at,
            )
            .where(
                CvGeneratedDocument.candidate_id == candidate_id,
                CvGeneratedDocument.job_id == job_id,
                CvGeneratedDocument.mode == "new",
            )
            .order_by(CvGeneratedDocument.id.desc())
            .limit(MAX_GENERATIONS)
        )
    ).all()
    ids = [row.id for row in rows]
    if not ids:
        return []
    attached = set(
        (
            await db.scalars(
                select(CandidateStageCV.generated_document_id).where(
                    CandidateStageCV.generated_document_id.in_(ids),
                    CandidateStageCV.branded_status.in_(("draft", "finalized")),
                )
            )
        ).all()
    )
    codes: dict[int, Optional[str]] = {}
    for generated_id, second_id, code in (
        await db.execute(
            select(
                CvGenerationJob.generated_id,
                CvGenerationJob.second_generated_id,
                CvGenerationJob.error_code,
            ).where(
                (CvGenerationJob.generated_id.in_(ids))
                | (CvGenerationJob.second_generated_id.in_(ids))
            )
        )
    ).all():
        for owned in (generated_id, second_id):
            if owned is not None:
                codes[owned] = code
    return [
        {
            "id": row.id,
            "status": row.status,
            "language": row.language,
            "content_mode": row.content_mode,
            "origin": row.origin,
            "created_at": row.created_at,
            "attached": row.id in attached,
            "error_code": codes.get(row.id) if row.status == "failed" else None,
        }
        for row in rows
    ]
