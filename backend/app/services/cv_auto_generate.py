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
  ``cv_generated_documents`` (0332). Ponowny ruch na ten sam etap z tym samym CV
  nie generuje i nie nalicza drugi raz; nowe CV = nowy dokument.
* Kwota AI i autorstwo dokumentu idą na osobę, która przesunęła kartę — to jej
  lista „Wygenerowane CV" i jej decyzja uruchomiła wydatek.
* Dokument powstaje jako zwykły wiersz generatora (``origin="auto"``): do
  klienta nie wychodzi nic bez zatwierdzenia i kliknięcia człowieka.
* Tryb treści: domyślny tryb z reguły klienta, inaczej domyślny generatora;
  język: wymuszony regułą, inaczej polski; nigdy blind.
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


async def _enqueue(db, *, stage_id: int, user_id: int) -> Optional[int]:
    """Zwraca id trwałego zadania do wykonania albo None (pominięte/odmowa)."""
    from fastapi import HTTPException

    from app.api.candidate_access import CANDIDATE_WRITE_ROLES
    from app.api.cv_generator_b2b import enqueue_candidate_generation
    from app.models.candidate import Candidate
    from app.models.cv_generated_document import CvGeneratedDocument
    from app.models.job import Job
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage
    from app.models.user import User
    from app.services.auto_match_outbox import candidate_revision
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

    rule = snapshot_rule(await resolve_client_rule(db, job.client_id))
    if rule is not None and getattr(rule, "requires_rodo_consent_block", False):
        # Zrzut zgody wgrywa człowiek — automat nie ma skąd go wziąć.
        await _record(
            db, action=ACTION_SKIPPED, reason="consent_screenshot_required", **base
        )
        return None
    language = (rule.cv_language if rule is not None else None) or "pl"
    content_mode = (
        rule.content_mode if rule is not None else None
    ) or DEFAULT_CONTENT_MODE
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
    return durable_id


async def generate_after_verified(*, stage_id: int, user_id: int) -> None:
    """Zadanie w tle po commicie ruchu. Nigdy nie rzuca."""
    if not enabled():
        return
    from app.core.database import AsyncSessionLocal

    durable_id: Optional[int] = None
    try:
        async with AsyncSessionLocal() as db:
            try:
                durable_id = await _enqueue(db, stage_id=stage_id, user_id=user_id)
            except IntegrityError:
                await db.rollback()
            except Exception as exc:  # noqa: BLE001
                await db.rollback()
                logger.warning(
                    "[cv_auto] stage=%s enqueue failed: %s",
                    stage_id,
                    type(exc).__name__,
                )
                await _record_failure(stage_id, user_id, type(exc).__name__)
        if durable_id is not None:
            from app.services.cv_generator_b2b.durable_jobs import execute_job

            # Wynik (ready/failed) ląduje na wierszu dokumentu — jak po
            # kliknięciu. Padnięty proces podejmie `recovery_loop` generatora.
            await execute_job(durable_id)
    except Exception as exc:  # noqa: BLE001 — automat nigdy nie psuje ruchu
        logger.warning("[cv_auto] stage=%s failed: %s", stage_id, type(exc).__name__)


async def _record_failure(stage_id: int, user_id: int, code: str) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_pipeline import CandidateStage

    try:
        async with AsyncSessionLocal() as db:
            stage = await db.get(CandidateStage, stage_id)
            if stage is None:
                return
            await _record(
                db,
                action=ACTION_FAILED,
                job_id=stage.job_id,
                stage_id=stage.id,
                candidate_id=stage.candidate_id,
                user_id=user_id,
                reason=code[:80],
            )
    except Exception:  # noqa: BLE001
        logger.warning("[cv_auto] stage=%s failure not recorded", stage_id)
