"""Auto-CV w szablonie firmowym po ruchu na „Zweryfikowany" (21.09.2026).

21.10.2026: generacja po ruchu jest WYŁĄCZONA (`CV_AUTO_GENERATE_WITHOUT_CONFIRMATION`,
domyślnie False). Zespół: CV powstawało, zanim rekruter dopisał notatkę do CV,
z pliku wybranego przez system, bez cofnięcia. Teraz rekruter potwierdza w karcie
„CV do klienta” plik, odpowiedzi i dodatkowe notatki. Po ruchu zostaje tylko QC
istniejącego CV pary. Reguły niżej dotyczą trybu z flagą True.

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
  dostaje ten sam stempel ``central_policy`` co po kliknięciu.
* Generator v3 (23.09.2026), auto-CV dla PKO BP pod centralnymi regułami:
  brak zrzutu zgody NIE jest już powodem pominięcia — dokument powstaje,
  a jego POBRANIE blokuje ``cv_consent_gate`` do czasu dołączenia zgody
  (``POST /generated/{id}/consent``). Numer projektu wynika z rekrutacji
  (``cv_packages.pko_job_reference``, numer ZOB); pominięcie zostaje tylko
  wtedy, gdy reguła go wymaga, a rekrutacja go nie niesie (Energa, Orlen).
  Bez centralnych reguł zrzut zgody jest wymogiem GENERACJI (422) — automat
  pomija jak dotąd.
* Rekruter nie czeka w ciemno (14.10.2026): po podpięciu szkicu automat liczy
  QC, zamawia poprawki AI i dzwoni ``cv_ready`` („CV gotowe do sprawdzenia”)
  do osoby, która przesunęła kartę. Pominięcie albo awaria, przy których
  rekruter musi zadziałać sam (``NOT_DONE_REASONS``), też dzwonią („Automat
  nie zrobił CV”). CV pary, które już jest (``pair_cv_exists``), dostaje QC
  i poprawki AI bez dzwonka.
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
# Wpis szkicu podpiętego przez automat; ręczna generacja z etapem podaje
# własny (`branded_cv_attached_after_generation`) i dzwonka nie dostaje.
ATTACH_ACTION = "branded_cv_attached_by_automation"

TITLE_READY = "CV gotowe do sprawdzenia:"
TITLE_NOT_DONE = "Automat nie zrobił CV:"
# Pominięcia i awarie, przy których rekruter musi zrobić CV sam — lustro
# `SKIP_REASON_PL` w `frontend/src/lib/job-background-events.ts`. Bez dzwonka:
# `pair_cv_exists` i `already_generated` (CV jest), `no_permission` (osoba
# i tak nie może generować) i ciche wyjścia bez wpisu.
NOT_DONE_REASONS: dict[str, str] = {
    "no_client": "rekrutacja nie ma przypisanego klienta",
    "no_cv_document": "kandydat nie ma w profilu pliku CV",
    "consent_screenshot_required": "reguła klienta wymaga zrzutu zgody RODO",
    "client_rule_inputs_missing": (
        "reguła klienta wymaga danych, których automat nie ma"
    ),
    "generation_unavailable": "generator CV był niedostępny",
    "generation_failed": "generacja CV zakończyła się błędem",
}


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
    if user_id is not None and (
        action == ACTION_FAILED
        or (action == ACTION_SKIPPED and reason in NOT_DONE_REASONS)
    ):
        await _bell(
            db,
            user_id=user_id,
            stage_id=stage_id,
            job_id=job_id,
            candidate_id=candidate_id,
            title=TITLE_NOT_DONE,
            tail=not_done_reason(reason, detail),
        )


def not_done_reason(reason: Optional[str], detail: Optional[str] = None) -> str:
    """Polski powód „Automat nie zrobił CV” (lustro `autoCvSkipReason`).

    Awaria spoza listy (klasa wyjątku) to dla rekrutera ta sama sytuacja co
    nieudana generacja — CV nie powstało i trzeba je zrobić ręcznie.
    """

    known = NOT_DONE_REASONS.get(reason or "") or NOT_DONE_REASONS["generation_failed"]
    extra = (detail or "").strip().rstrip(". ")
    if extra and reason == "client_rule_inputs_missing":
        # Walidacja generatora mówi DOKŁADNIE, czego brakuje.
        return f"{known} ({extra})"
    return known


async def _bell(
    db,
    *,
    user_id: int,
    stage_id: int,
    job_id: int,
    candidate_id: int,
    title: str,
    tail: Optional[str],
) -> None:
    """Dzwonek ``cv_ready`` do osoby, która przesunęła kartę. Nigdy nie rzuca.

    Encja = wiersz etapu, więc ten sam etap dzwoni najwyżej raz dziennie
    (`ix_notif_dedup_daily`); link otwiera panel osoby na sekcji CV.
    """

    from app.models.candidate import Candidate
    from app.models.job import Job
    from app.models.notification import NotificationType
    from app.services.notification_triggers import emit

    try:
        person = (
            await db.execute(
                select(Candidate.name, Candidate.lastname).where(
                    Candidate.id == candidate_id
                )
            )
        ).first()
        job_title = await db.scalar(select(Job.title).where(Job.id == job_id))
        name = (
            " ".join(p for p in (person.name, person.lastname) if p)
            if person is not None
            else ""
        ) or "Kandydat"
        message = " · ".join(p for p in ((job_title or "").strip(), tail) if p)
        await emit(
            db,
            user_id=user_id,
            title=f"{title} {name}"[:255],
            message=(message or "Rekrutacja")[:500],
            ntype=NotificationType.cv_ready,
            related_entity_type="candidate_stage",
            related_entity_id=stage_id,
            link=f"/jobs/{job_id}?candidate={candidate_id}&panel=cv",
        )
        await db.commit()
    except Exception as exc:  # noqa: BLE001 — dzwonek nie psuje automatu
        await db.rollback()
        logger.warning(
            "[cv_auto] stage=%s bell not sent: %s", stage_id, type(exc).__name__
        )


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
    from app.models.candidate_stage_cv import CandidateStageCV
    from app.models.cv_generated_document import (
        CvGeneratedDocument,
        not_discarded_clause,
    )
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
    # 21.10.2026: CV powstaje po potwierdzeniu w karcie, nie po ruchu. Wtedy
    # automat tylko liczy QC istniejącego CV pary — bez wpisów w „Pracy w tle”
    # i bez dzwonka „Automat nie zrobił CV” (nikt go nie prosił o CV).
    generates = bool(getattr(settings, "CV_AUTO_GENERATE_WITHOUT_CONFIRMATION", False))
    if generates and job.client_id is None:
        await _record(db, action=ACTION_SKIPPED, reason="no_client", **base)
        return None
    if not user.has_any_role(*CANDIDATE_WRITE_ROLES):
        if generates:
            await _record(db, action=ACTION_SKIPPED, reason="no_permission", **base)
        return None
    # 09.10.2026: para ma już CV firmowe (wybrane z profilu w screeningu albo
    # wygenerowane ręcznie na wcześniejszym etapie). Nowy dokument podpięty do
    # tego wiersza etapu przykryłby je jako „CV pary” (nowszy etap wygrywa),
    # a generacja byłaby płatna drugi raz. Sprawdzane PRZED plikiem CV
    # w profilu (14.10.2026): osoba z CV pary bez pliku w profilu dostawała
    # pominięcie „brak pliku CV”, a od dziś ono dzwoni.
    pair_cv_stage_id = await db.scalar(
        select(CandidateStageCV.candidate_stage_id)
        .where(
            CandidateStageCV.candidate_id == candidate.id,
            CandidateStageCV.job_id == job.id,
            CandidateStageCV.branded_status.in_(("draft", "finalized")),
        )
        .limit(1)
    )
    if pair_cv_stage_id is not None:
        if generates:
            await _record(db, action=ACTION_SKIPPED, reason="pair_cv_exists", **base)
        # 14.10.2026: istniejące CV pary dostaje to samo co szkic automatu —
        # QC i poprawki AI od razu, bez dzwonka (CV nikt teraz nie robił).
        await qc_after_attach(pair_cv_stage_id, user_id)
        return None
    if not generates:
        return None
    # 0521 (26.10.2026, decyzja D2): klient bierze formularz CV z Plików
    # rekrutacji — CV firmowe nie powstaje samo (rekruter może je zrobić ręcznie).
    from app.services import client_form_status

    if await client_form_status.client_takes_client_form(db, job.client_id):
        await _record(db, action=ACTION_SKIPPED, reason="client_form", **base)
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
    # Odrzucony w karcie „CV do klienta” (audyt 22.10, F64) też się nie liczy:
    # nie wraca jako szkic, automat robi CV od nowa.
    earlier = (
        await db.execute(
            select(CvGeneratedDocument.id, CvGeneratedDocument.status)
            .where(
                CvGeneratedDocument.origin == "auto",
                CvGeneratedDocument.candidate_id == candidate.id,
                CvGeneratedDocument.job_id == job.id,
                CvGeneratedDocument.source_cv_revision == revision,
                CvGeneratedDocument.status != "failed",
                not_discarded_clause(),
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
    if (
        not central_policies.enabled()
        and rule is not None
        and getattr(rule, "requires_rodo_consent_block", False)
    ):
        # Bez centralnych reguł zrzut zgody jest wymogiem generacji (422),
        # a automat nie ma skąd go wziąć. Pod centralnymi regułami dokument
        # powstaje, a pobranie blokuje `cv_consent_gate` (generator v3).
        await _record(
            db, action=ACTION_SKIPPED, reason="consent_screenshot_required", **base
        )
        return None
    managed = getattr(resolved_rule, "managed_policy", None)
    from app.api.cv_generator_b2b import derived_project_ref

    project_ref = derived_project_ref(resolved_rule, job, "")
    if (
        central_policies.enabled()
        and isinstance(managed, dict)
        and managed.get("require_project_ref")
        and not project_ref
    ):
        # Centralne reguły (0331) przenoszą wymóg numeru projektu z walidacji
        # generacji do gotowości PAKIETU: numer jest stemplowany na dokumencie
        # przy generacji i nie da się go potem uzupełnić. Gdy rekrutacja go
        # nie niesie (numer ZOB u PKO BP), automat go nie zna, więc dokument
        # byłby na zawsze nieudostępnialnym szkicem, za który naliczono AI.
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
            project_ref=project_ref,
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
        durable_id, _generated_id = queued
        from app.services.cv_generator_b2b.durable_jobs import execute_job

        # Wynik (ready/failed) ląduje na wierszu dokumentu — jak po kliknięciu.
        # Podpięcie szkicu i księgowanie sukcesu/porażki robi proces, który
        # FAKTYCZNIE wykonał zadanie (`after_job_finished`, wołane z
        # `execute_job`) — runda 7 (R7-N6-1): gdy sloty są zajęte albo zadanie
        # przejmie `recovery_loop`, ten proces wraca od razu i nie wie, jak
        # zadanie się skończyło.
        await execute_job(durable_id)
    except Exception as exc:  # noqa: BLE001 — automat nigdy nie psuje ruchu
        logger.warning("[cv_auto] stage=%s failed: %s", stage_id, type(exc).__name__)
        await failures.record_failure(failures.KIND_AUTO_CV, type(exc).__name__)


async def after_job_finished(generated_id: int) -> None:
    """Hak `durable_jobs.execute_job` po zakończeniu zadania generacji.

    Dotyczy WYŁĄCZNIE dokumentów automatu (``origin="auto"``) — ręczna generacja
    podpina szkic w workerze (``attach_stage_draft``). Nigdy nie rzuca.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.cv_generated_document import CvGeneratedDocument

    try:
        async with AsyncSessionLocal() as db:
            row = (
                await db.execute(
                    select(
                        CvGeneratedDocument.origin,
                        CvGeneratedDocument.stage_id,
                        CvGeneratedDocument.created_by,
                    ).where(CvGeneratedDocument.id == generated_id)
                )
            ).first()
        if row is None or row.origin != "auto" or row.stage_id is None:
            return
        if row.created_by is None:
            return
        await _after_generation(
            stage_id=row.stage_id, user_id=row.created_by, generated_id=generated_id
        )
    except Exception as exc:  # noqa: BLE001 — hak nie psuje zadania
        logger.warning(
            "[cv_auto] generated=%s not accounted: %s", generated_id, type(exc).__name__
        )


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
    # `processing` = zadanie jeszcze trwa u innego wykonawcy — on zawoła ten
    # hak po zakończeniu (`after_job_finished`).


async def attach_as_stage_draft(
    *,
    stage_id: int,
    user_id: int,
    generated_id: int,
    activity_action: str = ATTACH_ACTION,
) -> bool:
    """Podepnij gotowe auto-CV jako SZKIC brandowanego CV etapu — tylko gdy etap
    nie ma jeszcze żadnego szkicu (``branded_status == "none"``). Wyjątek od
    29.10.2026: generacja zlecona po nowym CV kandydata zastępuje nietknięty
    szkic (`new_cv_company_cv.replace_after_regeneration`).

    To ta sama operacja co „Zastąp szkic i otwórz edytor" w warsztacie wysyłki
    CV (`apply_generated_to_stage_cv`): wynik to ``draft``, NIGDY zatwierdzenie —
    zatwierdza człowiek przez `finalize`. Tą samą drogą idzie ręczna generacja
    z etapem (generator v3, ``activity_action`` inny niż automatu). Istniejącego szkicu (także domyślnego,
    którego ktoś mógł już edytować) automat nie nadpisuje; dokument zostaje
    wtedy pierwszy na liście „wybór z wygenerowanych" z ``needs_review``.
    Nigdy nie rzuca.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.candidate_stage_cv import CandidateStageCV
    from app.models.cv_generated_document import CvGeneratedDocument

    attached = False
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
                csv is not None
                and generated is not None
                and csv.branded_status != "none"
                and generated.status == "ready"
                and generated.render_payload
                and generated.candidate_id == csv.candidate_id
                and generated.job_id == csv.job_id
            ):
                # 29.10.2026: generacja po nowym CV kandydata zastępuje szkic,
                # którego od zlecenia nikt nie ruszał (`new_cv_company_cv`).
                from app.services.new_cv_company_cv import replace_after_regeneration

                if not await replace_after_regeneration(
                    db, csv, generated, user_id=user_id
                ):
                    return False
                await db.commit()
                attached = True
            elif (
                csv is None
                or generated is None
                or csv.branded_status != "none"
                or generated.status != "ready"
                or not generated.render_payload
                or generated.candidate_id != csv.candidate_id
                or generated.job_id != csv.job_id
            ):
                return False
            else:
                await apply_generated_to_stage_cv(
                    db,
                    csv,
                    generated,
                    user_id=user_id,
                    activity_action=activity_action,
                )
                await db.commit()
                attached = True
    except Exception as exc:  # noqa: BLE001 — dokument i tak jest na liście
        logger.warning(
            "[cv_auto] stage=%s draft not attached: %s", stage_id, type(exc).__name__
        )
        return False
    if attached:
        await qc_after_attach(
            stage_id, user_id, notify_ready=activity_action == ATTACH_ACTION
        )
    return attached


async def qc_after_attach(
    stage_id: int, user_id: int, *, notify_ready: bool = False
) -> None:
    """QC zaraz po podpięciu CV do etapu (13.10.2026): karta „CV do klienta”
    i Tablica pokazują liczbę rzeczy do sprawdzenia bez otwierania okna QC.
    Nigdy nie rzuca (`cv_qc.run_after_move`).

    14.10.2026: gdy QC ma uwagi, a karta stoi na „Zweryfikowanym” albo dalej,
    poprawki AI liczą się od razu (`_prefetch_fixes`) — edytor otwiera je
    z pamięci zamiast kazać czekać na model. ``notify_ready`` (tylko szkic
    automatu) = dzwonek ``cv_ready`` z wynikiem QC na końcu.
    """
    from app.core.config import settings

    result: Optional[dict] = None
    if settings.CV_QC_GATE_ENABLED:
        from app.services import cv_qc

        result = await cv_qc.run_after_move(stage_id, user_id)
        if result is not None:
            await _prefetch_fixes(stage_id, user_id, result)
    if notify_ready:
        await _bell_ready(stage_id, user_id, result)


_FIXES_FROM_COLUMN = "verified"


async def _card_from_verified_on(db, *, candidate_id: int, job_id: int) -> bool:
    """Czy karta pary stoi na „Zweryfikowanym” albo dalej (bez „Zamkniętych”).

    Na „Nowych” i „Screeningu” CV dopiero się wybiera — poprawki AI byłyby
    wydatkiem na wersję, której rekruter może nie użyć.
    """
    from app.models.recruitment_pipeline import CandidateStage
    from app.services.board_stage_badges import BOARD_COLUMN_ORDER
    from app.services.candidate_claim import stage_column

    latest = await db.scalar(
        select(CandidateStage)
        .where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == job_id,
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        .limit(1)
    )
    if latest is None:
        return False
    column = await stage_column(db, latest)
    return column in BOARD_COLUMN_ORDER and BOARD_COLUMN_ORDER.index(
        column
    ) >= BOARD_COLUMN_ORDER.index(_FIXES_FROM_COLUMN)


async def _prefetch_fixes(stage_id: int, user_id: int, result: dict) -> None:
    """Poprawki AI QC raz, z góry (`cv_qc.generate_fixes`, pamięć
    `dz_review_hints`). Nigdy nie rzuca.

    Klucz pamięci to wiersz etapu, na którym leży CV (`QcResponse.cv.stage_id`)
    — ten sam, na którym otwiera się edytor (`useStageBrandedCv.cvStageId`).
    Przebieg bez uwag i CV z pliku (nieedytowalne) nie wołają modelu.
    """
    if not (result.get("blocking_failed") or result.get("warnings_count")):
        return
    cv = result.get("cv") or {}
    if not cv.get("editable"):
        return
    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_pipeline import CandidateStage
    from app.services import cv_qc

    fix_stage_id = cv.get("stage_id") or stage_id
    try:
        async with AsyncSessionLocal() as db:
            if not await _card_from_verified_on(
                db, candidate_id=result["candidate_id"], job_id=result["job_id"]
            ):
                return
            stage = await db.get(CandidateStage, fix_stage_id)
            if stage is None:
                return
            await cv_qc.generate_fixes(db, stage, user_id=user_id)
    except Exception as exc:  # noqa: BLE001 — podpowiedź, nigdy awaria automatu
        logger.warning(
            "[cv_auto] stage=%s fixes not prefetched: %s",
            fix_stage_id,
            type(exc).__name__,
        )


async def _bell_ready(stage_id: int, user_id: int, result: Optional[dict]) -> None:
    """„CV gotowe do sprawdzenia: …” z wynikiem QC (bez QC — sam tytuł
    rekrutacji). Nigdy nie rzuca."""
    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_pipeline import CandidateStage

    tail = None
    if result is not None:
        from app.services.cv_qc import findings_text

        tail = findings_text(result["blocking_failed"], result["warnings_count"])
    try:
        async with AsyncSessionLocal() as db:
            stage = await db.get(CandidateStage, stage_id)
            if stage is None:
                return
            await _bell(
                db,
                user_id=user_id,
                stage_id=stage.id,
                job_id=stage.job_id,
                candidate_id=stage.candidate_id,
                title=TITLE_READY,
                tail=tail,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[cv_auto] stage=%s ready bell not sent: %s", stage_id, type(exc).__name__
        )


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
