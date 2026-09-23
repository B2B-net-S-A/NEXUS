"""Auto-CV w szablonie firmowym po ruchu na „Zweryfikowany" (21.09.2026).

Po COMMICIE pojedynczego ruchu kandydata na etap „Zweryfikowany" endpoint ruchu
odpala :func:`generate_after_verified` jako zadanie w tle (własna sesja bazy).
Zadanie nigdy nie zmienia statusu ani czasu odpowiedzi ruchu i nigdy nie rzuca.

Reguły, które łatwo cofnąć „przy okazji":

* JEDNA ścieżka walidacji z kliknięciem rekrutera
  (``api.cv_generator_b2b.enqueue_candidate_generation``): automat NIE omija
  zatwierdzonej reguły klienta. Wymagany zrzut zgody RODO (PKO BP), notatki,
  numer projektu albo Champion, których nie ma = POMINIĘCIE z
  ``Activity(cv_auto_generate_skipped, reason=…)`` — nigdy dokument łamiący
  regułę i nigdy naliczona kwota AI za coś, czego nie da się wysłać.
* Idempotencja: (etap, wersja CV kandydata) — częściowy UNIQUE na
  ``cv_generated_documents`` (0335). Ponowny ruch na ten sam etap z tym samym CV
  nie generuje i nie nalicza drugi raz; nowe CV = nowy dokument. Od audytu
  22.09 r2 (AI-06) także (kandydat, rekrutacja, wersja CV): powrót karty na
  „Zweryfikowany" (nowy wiersz etapu) daje pominięcie ``already_generated``
  i podpięcie istniejącego gotowego dokumentu jako szkicu nowego etapu.
* Kwota AI i autorstwo dokumentu idą na osobę, która przesunęła kartę — to jej
  lista „Wygenerowane CV" i jej decyzja uruchomiła wydatek.
* Dokument powstaje jako zwykły wiersz generatora (``origin="auto"``): do
  klienta nie wychodzi nic bez zatwierdzenia i kliknięcia człowieka.
* Tryb treści: domyślny tryb z reguły klienta, inaczej domyślny generatora;
  język: wymuszony regułą, inaczej polski; nigdy blind.
* Centralne reguły CV (``CV_CENTRAL_POLICIES_ENABLED``, 0331): język ustala
  wspólna ścieżka (język polityki); tryb od #1647 serwer bierze z żądania, więc
  automat prosi o tryb z katalogu polityk („Pod rekrutację"), a bez Championa
  ``central_policies.resolve_mode`` schodzi do Redakcji z komunikatem. Wiersz
  dostaje ten sam stempel ``central_policy`` co po kliknięciu. Wymogi,
  które centralny przepływ sprawdza dopiero przy gotowości PAKIETU, a które
  zapadają przy generacji (zrzut zgody, numer projektu), automat traktuje jak
  brak wejścia: pominięcie z powodem, nie dokument nie do udostępnienia.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings

logger = logging.getLogger(__name__)

ACTIVITY_ENTITY = "job_automation"
ACTION_STARTED = "cv_auto_generate_started"
ACTION_SKIPPED = "cv_auto_generate_skipped"
ACTION_FAILED = "cv_auto_generate_failed"


def enabled() -> bool:
    return bool(getattr(settings, "CV_AUTO_GENERATE_ON_VERIFIED", False))


async def _record(
    db,
    *,
    action: str,
    job_id: int,
    stage_id: int,
    candidate_id: int,
    user_id: Optional[int],
    reason: Optional[str] = None,
    detail: Optional[str] = None,
    generated_id: Optional[int] = None,
    message: Optional[str] = None,
) -> None:
    from app.models.activity import Activity

    details = {"stage_id": stage_id, "candidate_id": candidate_id}
    if reason:
        details["reason"] = reason
    if detail:
        # Komunikat walidacji generatora (po polsku, bez danych kandydata).
        details["detail"] = detail[:300]
    if generated_id is not None:
        details["generated_id"] = generated_id
    if message:
        details["message"] = message
    db.add(
        Activity(
            entity_type=ACTIVITY_ENTITY,
            entity_id=job_id,
            action=action,
            user_id=user_id,
            details=details,
        )
    )
    await db.commit()


def _detail_text(detail) -> str:
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict):
        return str(detail.get("reason") or detail.get("message") or "")
    return ""


async def _enqueue(db, *, stage_id: int, user_id: int) -> Optional[tuple[int, int]]:
    """Zwraca ``(id trwałego zadania, id dokumentu)`` albo None (pominięte/odmowa)."""
    from fastapi import HTTPException

    from app.api.candidate_access import CANDIDATE_WRITE_ROLES
    from app.api.cv_generator_b2b import enqueue_candidate_generation
    from app.models.candidate import Candidate
    from app.models.cv_generated_document import CvGeneratedDocument
    from app.models.job import Job
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage
    from app.models.user import User
    from app.services.auto_match_outbox import candidate_revision
    from app.services.cv_generator_b2b import central_policies
    from app.services.cv_generator_b2b.client_rules import (
        resolve_client_rule,
        snapshot_rule,
    )
    from app.services.cv_generator_b2b.prompts import DEFAULT_CONTENT_MODE
    from app.services.cv_generator_b2b.standalone_service import (
        list_candidate_cv_sources,
    )

    stage = await db.get(CandidateStage, stage_id)
    if stage is None or stage.stage != PipelineStage.verified:
        return None
    job = await db.get(Job, stage.job_id)
    candidate = await db.get(Candidate, stage.candidate_id)
    user = await db.get(User, user_id)
    if job is None or candidate is None or user is None:
        return None
    base = dict(
        job_id=job.id, stage_id=stage.id, candidate_id=candidate.id, user_id=user_id
    )
    if job.client_id is None:
        await _record(db, action=ACTION_SKIPPED, reason="no_client", **base)
        return None
    if not user.has_any_role(*CANDIDATE_WRITE_ROLES):
        await _record(db, action=ACTION_SKIPPED, reason="no_permission", **base)
        return None
    sources = await list_candidate_cv_sources(db, candidate.id)
    if not sources:
        await _record(db, action=ACTION_SKIPPED, reason="no_cv_document", **base)
        return None

    revision = candidate_revision(candidate)
    already = await db.scalar(
        select(CvGeneratedDocument.id)
        .where(
            CvGeneratedDocument.origin == "auto",
            CvGeneratedDocument.stage_id == stage.id,
            CvGeneratedDocument.source_cv_revision == revision,
        )
        .limit(1)
    )
    if already is not None:
        return None
    # audyt 22.09 r2 (AI-06): ponowny ruch tej samej karty na „Zweryfikowany"
    # (np. cofnięcie i powrót) tworzy NOWY wiersz etapu, więc klucz (etap,
    # wersja CV) go nie łapał i automat płacił drugi raz za ten sam dokument.
    # Dokument dla tej samej osoby, rekrutacji i wersji CV (nieudany się nie
    # liczy) = pominięcie; gotowy podpinamy jako szkic nowego etapu.
    earlier = (
        await db.execute(
            select(CvGeneratedDocument.id, CvGeneratedDocument.status)
            .where(
                CvGeneratedDocument.origin == "auto",
                CvGeneratedDocument.candidate_id == candidate.id,
                CvGeneratedDocument.job_id == job.id,
                CvGeneratedDocument.source_cv_revision == revision,
                CvGeneratedDocument.status != "failed",
            )
            .order_by(CvGeneratedDocument.id.desc())
            .limit(1)
        )
    ).first()
    if earlier is not None:
        await _record(
            db,
            action=ACTION_SKIPPED,
            reason="already_generated",
            generated_id=earlier.id,
            **base,
        )
        if earlier.status == "ready":
            await attach_as_stage_draft(
                stage_id=stage.id, user_id=user_id, generated_id=earlier.id
            )
        return None

    try:
        resolved_rule = await resolve_client_rule(db, job.client_id)
    except HTTPException as exc:
        # Centralna polityka klienta czeka na synchronizację (503): to samo
        # usłyszałby rekruter po kliknięciu — pominięcie, nie „awaria automatu".
        await db.rollback()
        await _record(
            db,
            action=ACTION_SKIPPED,
            reason="generation_unavailable",
            detail=_detail_text(exc.detail),
            **base,
        )
        return None
    rule = snapshot_rule(resolved_rule)
    if rule is not None and getattr(rule, "requires_rodo_consent_block", False):
        # Zrzut zgody wgrywa człowiek — automat nie ma skąd go wziąć.
        await _record(
            db, action=ACTION_SKIPPED, reason="consent_screenshot_required", **base
        )
        return None
    managed = getattr(resolved_rule, "managed_policy", None)
    if (
        central_policies.enabled()
        and isinstance(managed, dict)
        and managed.get("require_project_ref")
    ):
        # Centralne reguły (0331) przenoszą wymóg numeru projektu z walidacji
        # generacji do gotowości PAKIETU: numer jest stemplowany na dokumencie
        # przy generacji i nie da się go potem uzupełnić. Automat numeru nie
        # zna, więc dokument byłby na zawsze nieudostępnialnym szkicem
        # („Brak numeru projektu / zapytania"), za który naliczono już AI.
        await _record(
            db,
            action=ACTION_SKIPPED,
            reason="client_rule_inputs_missing",
            detail="Reguła klienta wymaga numeru projektu / zapytania.",
            **base,
        )
        return None
    language = (rule.cv_language if rule is not None else None) or "pl"
    content_mode = (
        rule.content_mode if rule is not None else None
    ) or DEFAULT_CONTENT_MODE
    if central_policies.enabled():
        # Od #1647 serwer honoruje tryb z żądania zamiast liczyć go sam, więc
        # automat prosi o ten sam tryb, który formularz zaznacza domyślnie
        # (katalog polityk: „Pod rekrutację"). Bez kompletnego Championa
        # wspólna ścieżka i tak schodzi do Redakcji z komunikatem.
        content_mode = central_policies.policy_content_mode(
            managed if isinstance(managed, dict) else None
        )
    try:
        generated_id, durable_id, _name = await enqueue_candidate_generation(
            db,
            user_id=user_id,
            candidate=candidate,
            stage=stage,
            client_id=job.client_id,
            cv_document_id=sources[0]["id"],
            language=language,
            blind_cv=False,
            content_mode=content_mode,
            project_ref="",
            origin="auto",
            source_cv_revision=revision,
            # Decyzja właściciela (21.09.2026): automat robi JEDNĄ wersję
            # językową — główną wg reguły klienta; drugą dorabia rekruter
            # jednym kliknięciem (ponowienie pakietu), więc jeden ruch karty
            # to jedna kwota AI także u klientów dwujęzycznych.
            languages="primary_only",
            # Nazwa pliku wg centralnej polityki bierze stanowisko z treści CV;
            # gdy CV go nie daje, automat (i tylko on) podstawia tytuł rekrutacji.
            # (`Candidate` nie ma kolumny `current_position` — o tym, czy stanowisko
            # jest, rozstrzyga dopiero potok generacji, więc fallback jedzie zawsze.)
            position_fallback=(job.title or "").strip() or None,
        )
    except HTTPException as exc:
        await db.rollback()
        reason = (
            "client_rule_inputs_missing"
            if exc.status_code == 422
            else "generation_unavailable"
        )
        await _record(
            db,
            action=ACTION_SKIPPED,
            reason=reason,
            detail=_detail_text(exc.detail),
            **base,
        )
        return None
    try:
        await _record(db, action=ACTION_STARTED, generated_id=generated_id, **base)
    except IntegrityError:
        # Równoległy ruch tej samej karty wygrał wyścig o klucz idempotencji.
        await db.rollback()
        return None
    return durable_id, generated_id


async def generate_after_verified(*, stage_id: int, user_id: int) -> None:
    """Zadanie w tle po commicie ruchu. Nigdy nie rzuca."""
    if not enabled():
        return
    from app.core.database import AsyncSessionLocal
    from app.services import automation_failures as failures

    queued: Optional[tuple[int, int]] = None
    try:
        async with AsyncSessionLocal() as db:
            try:
                queued = await _enqueue(db, stage_id=stage_id, user_id=user_id)
            except IntegrityError:
                await db.rollback()
            except Exception as exc:  # noqa: BLE001
                await db.rollback()
                await _record_failure(stage_id, user_id, type(exc).__name__)
        if queued is None:
            return
        durable_id, generated_id = queued
        from app.services.cv_generator_b2b.durable_jobs import execute_job

        # Wynik (ready/failed) ląduje na wierszu dokumentu — jak po kliknięciu.
        # Padnięty proces podejmie `recovery_loop` generatora.
        await execute_job(durable_id)
        await _after_generation(
            stage_id=stage_id, user_id=user_id, generated_id=generated_id
        )
    except Exception as exc:  # noqa: BLE001 — automat nigdy nie psuje ruchu
        logger.warning("[cv_auto] stage=%s failed: %s", stage_id, type(exc).__name__)
        await failures.record_failure(failures.KIND_AUTO_CV, type(exc).__name__)


async def _after_generation(*, stage_id: int, user_id: int, generated_id: int) -> None:
    """Gotowy dokument → szkic brandowanego CV etapu; porażka → wpis i licznik."""
    from app.core.database import AsyncSessionLocal
    from app.models.cv_generated_document import CvGeneratedDocument
    from app.services import automation_failures as failures

    async with AsyncSessionLocal() as db:
        status = await db.scalar(
            select(CvGeneratedDocument.status).where(
                CvGeneratedDocument.id == generated_id
            )
        )
    if status == "ready":
        await failures.record_success(failures.KIND_AUTO_CV)
        await attach_as_stage_draft(
            stage_id=stage_id, user_id=user_id, generated_id=generated_id
        )
    elif status == "failed":
        await _record_failure(
            stage_id, user_id, "generation_failed", generated_id=generated_id
        )
    # `processing` = zadanie przejął inny worker / proces padł; dokończy je
    # `recovery_loop`, a dokument i tak jest widoczny na liście z flagą auto.


async def attach_as_stage_draft(
    *, stage_id: int, user_id: int, generated_id: int
) -> bool:
    """Podepnij gotowe auto-CV jako SZKIC brandowanego CV etapu — tylko gdy etap
    nie ma jeszcze żadnego szkicu (``branded_status == "none"``).

    To ta sama operacja co „Zastąp szkic i otwórz edytor" w warsztacie wysyłki
    CV (`apply_generated_to_stage_cv`): wynik to ``draft``, NIGDY zatwierdzenie —
    zatwierdza człowiek przez `finalize`. Istniejącego szkicu (także domyślnego,
    którego ktoś mógł już edytować) automat nie nadpisuje; dokument zostaje
    wtedy pierwszy na liście „wybór z wygenerowanych" z ``needs_review``.
    Nigdy nie rzuca.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.candidate_stage_cv import CandidateStageCV
    from app.models.cv_generated_document import CvGeneratedDocument

    try:
        from app.api.candidate_stage_cv import apply_generated_to_stage_cv

        async with AsyncSessionLocal() as db:
            csv = await db.scalar(
                select(CandidateStageCV)
                .where(CandidateStageCV.candidate_stage_id == stage_id)
                .with_for_update()
            )
            generated = await db.get(CvGeneratedDocument, generated_id)
            if (
                csv is None
                or generated is None
                or csv.branded_status != "none"
                or generated.status != "ready"
                or not generated.render_payload
                or generated.candidate_id != csv.candidate_id
                or generated.job_id != csv.job_id
            ):
                return False
            await apply_generated_to_stage_cv(
                db,
                csv,
                generated,
                user_id=user_id,
                activity_action="branded_cv_attached_by_automation",
            )
            await db.commit()
            return True
    except Exception as exc:  # noqa: BLE001 — dokument i tak jest na liście
        logger.warning(
            "[cv_auto] stage=%s draft not attached: %s", stage_id, type(exc).__name__
        )
        return False


async def _record_failure(
    stage_id: int, user_id: int, code: str, *, generated_id: Optional[int] = None
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_pipeline import CandidateStage
    from app.services import automation_failures as failures

    job_id = None
    try:
        async with AsyncSessionLocal() as db:
            stage = await db.get(CandidateStage, stage_id)
            if stage is not None:
                job_id = stage.job_id
                await _record(
                    db,
                    action=ACTION_FAILED,
                    job_id=stage.job_id,
                    stage_id=stage.id,
                    candidate_id=stage.candidate_id,
                    user_id=user_id,
                    reason=code[:80],
                    message=failures.reason_pl(code),
                    generated_id=generated_id,
                )
    except Exception:  # noqa: BLE001
        logger.warning("[cv_auto] stage=%s failure not recorded", stage_id)
    await failures.record_failure(failures.KIND_AUTO_CV, code, job_id=job_id)
