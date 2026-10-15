"""Zapis rekrutacji w API v1: dodanie osoby do rekrutacji, przesunięcie karty.

Scope ``recruitments:write``. Te same ciała co ekran, bez drugiej kopii reguł:

* **Dodanie** (``POST /recruitments/{id}/candidates``) —
  ``proposals_bulk.add_candidates_to_job`` i ``propose_candidates_for_job``
  z decyzją integracji ``split_by_application`` (ta sama co token OAuth na
  ``POST /api/jobs/{id}/proposals/bulk``): na Tablicę trafia tylko osoba,
  która zgłosiła się do TEJ rekrutacji (formularz, ogłoszenie, notatka
  z formularza aplikacji), pozostali czekają w „Do przejrzenia” jako
  propozycja. Jak każda integracja: źródło wejścia ``auto_match``, bez 12 h
  blokady, notatka systemowa (tylko przy osobach dodanych na Tablicę),
  propozycje osoby bez zmian. Kolumna wejścia wyłącznie „Nowi” albo
  „Screening”; twarde bramki (globalna czarna lista, weto hiring managera)
  dają ``blocked``, konflikty z klientem — ``warnings``. Zamknięta karta
  (odrzucony, wycofany, rezerwa) to ``closed_in_job`` z wersją procesu do
  przywrócenia ruchem — bez osoby, która kartę zamknęła.
* **Ruch** (``POST /recruitments/{id}/moves``) — ``pipeline.apply_move``
  z ``IntegrationMovePolicy`` (``services/recruitment_move_policy.py``).
  Bramki biznesowe Tablicy są te same: etap z szablonu rekrutacji,
  etapy-odznaki, QC CV, „Zweryfikowany” (arkusz screeningu i stawka —
  409 ``VERIFIED_REQUIREMENTS_MISSING``), debrief przed „Umową”, ostrzeżenie
  eligibility (409 ``ELIGIBILITY_WARNING``, przechodzi z
  ``acknowledge_eligibility``), wersja procesu (409
  ``PIPELINE_VERSION_CONFLICT``), powód zamknięcia ze słownika (422).

  Decyzje dla kluczy (Artur, 15.10.2026):

  - wolno: ruch naprzód i wstecz między kolumnami w toku (Nowi, Screening,
    Zweryfikowany, QC CV; po wysłaniu — CV wysłane, Rozmowa u klienta,
    Umowa), wejście na „Zweryfikowany” i zamknięcie (odrzucenie, rezygnacja)
    z powodem — z każdej kolumny w toku; przywrócenie zamkniętej karty to
    zwykły ruch (też przed wysłaniem do klienta);
  - 403 ``requires_screen_decision`` (``details.reason``): ``hire`` —
    „Zatrudniony”/onboarding i każdy ruch karty zatrudnionej osoby (także
    zamknięcie); ``client_send`` — karta przechodzi z kolumn przed
    „CV wysłane” na „CV wysłane” albo dalej (wysyłka do klienta i stawka
    do klienta należą do Delivery Leada); ``cpro_queue`` — etap
    Cpro Nordei i każdy ruch karty stojącej w kolejce Cpro poza zamknięciem;
    ``client_rate`` / ``candidate_rate`` — zapis stawki (trasa ich nie
    przyjmuje);
  - 409 ``not_in_recruitment`` — osoby nie ma w rekrutacji (dodanie jest
    osobną trasą z regułą zgłoszenia);
  - bez 12 h blokady; ``moved_by`` = ``null``, ``details.via`` na historii
    = stempel klucza, bez ``UserActivity`` (ranking ludzi);
  - bez maila odrzucenia (wychodzi ze skrzynki osoby, która odrzuca) i bez
    auto-CV po „Zweryfikowany” (dokument ma autora — generuje go osoba).

* **Efekty po commicie** — jak na ekranie i dopiero po zatwierdzeniu
  (``idempotent_write``): Tablica na żywo, powiadomienia o przejściu, pula
  talentów, ryzyko, QC CV po wejściu do „QC CV” (``run_move_effects``).
  Powtórka z tym samym ``Idempotency-Key`` oddaje paragon bez efektów.
* **``dry_run``** tylko przy dodaniu: werdykty eligibility i decyzja
  Tablica/propozycja, bez zapisu. Ruch go nie ma — zapisuje migawkę CV na
  dysku przed commitem (``create_original_cv_snapshot``), więc próba
  z wycofaniem zostawiałaby osierocone pliki, a przebieg „tylko bramki”
  byłby drugą kopią reguł ruchu.

Moduł NIE MOŻE mieć ``from __future__ import annotations`` (slowapi #579).
"""

from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import pipeline as pipeline_routes
from app.api import proposals_bulk
from app.api.integrations_v1.common import (
    INT4_MAX,
    IdPath,
    IntegrationRoute,
    RecruitmentsWrite,
    dry_run_response,
    idempotent_write,
    principal_of,
    principal_rate_key,
    write_rate_limit,
)
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage
from app.schemas.pipeline import StageMove
from app.services import candidate_claim
from app.services.candidate_job_cards import latest_cards
from app.services.candidate_job_eligibility import EligibilityReason
from app.services.pipeline_eligibility import (
    detail_for,
    evaluate_candidates_for_job_with_verdicts,
)
from app.services.pipeline_realtime import broadcast_pipeline_changed
from app.services.recruitment_move_policy import IntegrationMovePolicy

router = APIRouter(route_class=IntegrationRoute)

MAX_CANDIDATES_PER_ADD = 50


# ── Wejście ──────────────────────────────────────────────────────────────────


class _StrictIn(BaseModel):
    # Literówka w nazwie pola zapisu nie może przejść po cichu jako „bez zmian”.
    model_config = ConfigDict(extra="forbid")


CandidateIdIn = Annotated[int, Field(ge=1, le=INT4_MAX)]


class RecruitmentAddIn(_StrictIn):
    candidate_ids: list[CandidateIdIn] = Field(
        ...,
        min_length=1,
        max_length=MAX_CANDIDATES_PER_ADD,
        description="Osoby do dodania (powtórzenia liczą się raz).",
    )
    stage_def_id: Optional[int] = Field(
        None,
        ge=1,
        le=INT4_MAX,
        description=(
            "Kolumna wejścia: etap „Nowi” albo „Screening” z szablonu tej "
            "rekrutacji (``/recruitments/{id}/stages``). Domyślnie pierwsza "
            "kolumna szablonu."
        ),
    )
    note: Optional[str] = Field(
        None,
        min_length=1,
        max_length=2000,
        description="Notatka systemowa przy osobach dodanych na Tablicę.",
    )


class CardMoveIn(_StrictIn):
    candidate_id: int = Field(..., ge=1, le=INT4_MAX)
    to_stage_def_id: int = Field(
        ...,
        ge=1,
        le=INT4_MAX,
        description="Etap docelowy z szablonu tej rekrutacji (``stage_def_id``).",
    )
    expected_state_version: Optional[int] = Field(
        None,
        ge=0,
        le=INT4_MAX,
        description=(
            "Wersja procesu, którą widział automat (``process_state_version`` "
            "karty). Inna niż bieżąca = 409 PIPELINE_VERSION_CONFLICT."
        ),
    )
    rejection_reason_id: Optional[int] = Field(
        None,
        ge=1,
        le=INT4_MAX,
        description="Powód zamknięcia ze słownika szablonu (rezygnacja go wymaga).",
    )
    rejection_reason: Optional[str] = Field(
        None,
        min_length=1,
        max_length=500,
        description="Opis powodu odrzucenia, gdy nie ma go w słowniku.",
    )
    acknowledge_eligibility: bool = Field(
        False,
        description=(
            "Przenieś mimo ostrzeżenia (globalna czarna lista, weto hiring "
            "managera) — zostaje ślad w historii."
        ),
    )


# ── Wyjście ──────────────────────────────────────────────────────────────────

AddStatus = Literal["added", "proposed", "already_in_job", "closed_in_job", "blocked"]


class RecruitmentAddWarningOut(BaseModel):
    reason: str = Field(
        description=(
            "client_blacklist | client_nda | client_competitor | "
            "current_employment | excluded_by_candidate"
        )
    )
    reason_label: Optional[str]


class RecruitmentAddItemOut(BaseModel):
    candidate_id: int
    status: AddStatus
    reason: Optional[str] = Field(
        description=(
            "Przy ``blocked``: blacklisted | rejected_by_hiring_manager | "
            "candidate_not_found."
        )
    )
    reason_label: Optional[str]
    card_id: Optional[int] = Field(description="Karta na Tablicy (``added``).")
    stage_def_id: Optional[int] = Field(
        description="Kolumna, do której trafiła osoba (``added``)."
    )
    process_state_version: Optional[int] = Field(
        description=(
            "Przy ``closed_in_job``: ``expected_state_version`` dla ruchu, "
            "który przywraca kartę."
        )
    )
    warnings: list[RecruitmentAddWarningOut]


class RecruitmentAddOut(BaseModel):
    job_id: int
    items: list[RecruitmentAddItemOut]
    added: int
    proposed: int
    skipped: int


class CardMoveOut(BaseModel):
    card_id: int
    candidate_id: int
    job_id: int
    stage: str = Field(description="Kod etapu (``new``, ``verified``, ``rejected``…).")
    stage_def_id: Optional[int]
    stage_name: str
    column: str = Field(
        description=(
            "new | screening | verified | cv_qc | cv_sent | client_interview | "
            "contract | closed"
        )
    )
    moved_at: datetime
    process_state_version: int
    rejection_reason_id: Optional[int]
    ended_by: Optional[str] = Field(description="candidate | recruiter | client")
    eligibility_acknowledged: Optional[str] = Field(
        description="Kod ostrzeżenia przyjętego flagą ``acknowledge_eligibility``."
    )


# ── Wspólne ─────────────────────────────────────────────────────────────────


async def _job_or_404(db: AsyncSession, job_id: int) -> Job:
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if job is None:
        raise HTTPException(404, detail="Rekrutacja nie istnieje.")
    return job


def _value(raw: Any) -> Any:
    return getattr(raw, "value", raw)


def _item(candidate_id: int, status: AddStatus, **extra: Any) -> dict:
    return {
        "candidate_id": candidate_id,
        "status": status,
        "reason": None,
        "reason_label": None,
        "card_id": None,
        "stage_def_id": None,
        "process_state_version": None,
        "warnings": [],
        **extra,
    }


async def _closed_in_job(
    db: AsyncSession, *, job_id: int, candidate_ids: list[int]
) -> dict[int, dict]:
    """Osoby z kartą w „Zamkniętych” — ``closed_in_job`` zamiast „już jest”.

    Etykieta mówi etap i dzień, BEZ osoby, która kartę zamknęła (ta nie
    trafia do odpowiedzi integracji — ``dodaj-do-rekrutacji-zamknieta-karta``).
    Przywrócenie to ruch karty (``/moves``) z ``process_state_version``.
    """
    if not candidate_ids:
        return {}
    cards = await latest_cards(db, candidate_ids=candidate_ids, job_id=job_id)
    closed = [cid for cid, card in cards.items() if card.column == "closed"]
    versions = await proposals_bulk._process_versions(
        db, job_id=job_id, candidate_ids=closed
    )
    return {
        cid: {
            "reason_label": proposals_bulk._closed_card_label(
                cards[cid].stage_label or "Zamknięty", cards[cid].moved_at, None
            ),
            "process_state_version": versions.get(cid, 0),
        }
        for cid in closed
    }


# ── Dodanie do rekrutacji ────────────────────────────────────────────────────


async def _add_verdicts(
    db: AsyncSession, *, job: Job, ids: list[int], add_ids: list[int]
) -> list[dict]:
    """``dry_run``: werdykty bez zapisu — ta sama polityka eligibility co
    dodanie (``evaluate_candidates_for_job_with_verdicts``)."""
    existing = set(
        (await db.scalars(select(Candidate.id).where(Candidate.id.in_(ids)))).all()
    )
    already = set(
        (
            await db.scalars(
                select(CandidateStage.candidate_id).where(
                    CandidateStage.job_id == job.id,
                    CandidateStage.candidate_id.in_(ids),
                )
            )
        ).all()
    )
    decisions, verdicts = await evaluate_candidates_for_job_with_verdicts(
        db,
        job=job,
        candidate_ids=sorted(existing),
        now=datetime.now(timezone.utc),
        already_in_job_ids=already,
    )
    closed = await _closed_in_job(db, job_id=job.id, candidate_ids=sorted(already))
    add_set = set(add_ids)
    items: list[dict] = []
    for cid in ids:
        decision = decisions.get(cid)
        if cid not in existing or decision is None:
            items.append(_item(cid, "blocked", reason="candidate_not_found"))
            continue
        if decision.reason_code is EligibilityReason.already_in_job:
            if cid in closed:
                items.append(_item(cid, "closed_in_job", **closed[cid]))
            else:
                items.append(_item(cid, "already_in_job"))
            continue
        if not decision.assignment_allowed:
            items.append(
                _item(
                    cid,
                    "blocked",
                    reason=proposals_bulk._SKIP_REASON_BY_ELIGIBILITY.get(
                        decision.reason_code, "blacklisted"
                    ),
                    reason_label=detail_for(decision, verdicts.get(cid)),
                )
            )
            continue
        warn = proposals_bulk._WARNING_REASON_BY_ELIGIBILITY.get(decision.reason_code)
        items.append(
            _item(
                cid,
                "added" if cid in add_set else "proposed",
                warnings=(
                    [{"reason": warn, "reason_label": decision.reason}] if warn else []
                ),
            )
        )
    return items


async def _add_items(
    db: AsyncSession,
    *,
    job: Job,
    ids: list[int],
    proposal: Optional[proposals_bulk.ProposeResult],
    intake: Optional[proposals_bulk.IntakeResult],
) -> list[dict]:
    """Wynik ciał ekranu → wiersz na osobę, w kolejności z żądania."""
    by_id: dict[int, dict] = {}
    skipped = [
        *(proposal.skipped if proposal else []),
        *(intake.skipped if intake else []),
    ]
    warnings = [
        *(proposal.warnings if proposal else []),
        *(intake.warnings if intake else []),
    ]
    stage_defs: dict[int, Optional[int]] = {}
    if intake is not None and intake.stage_ids:
        rows = await db.execute(
            select(CandidateStage.id, CandidateStage.stage_def_id).where(
                CandidateStage.id.in_(list(intake.stage_ids.values()))
            )
        )
        stage_defs = {row.id: row.stage_def_id for row in rows.all()}
        for cid, stage_id in intake.stage_ids.items():
            by_id[cid] = _item(
                cid, "added", card_id=stage_id, stage_def_id=stage_defs.get(stage_id)
            )
    for cid in proposal.proposed if proposal else []:
        by_id[cid] = _item(cid, "proposed")
    already = [row.candidate_id for row in skipped if row.reason == "already_in_job"]
    closed = await _closed_in_job(db, job_id=job.id, candidate_ids=already)
    for row in skipped:
        cid = row.candidate_id
        if row.reason in ("already_in_job", "closed_in_job"):
            if cid in closed:
                by_id[cid] = _item(cid, "closed_in_job", **closed[cid])
            else:
                by_id[cid] = _item(cid, "already_in_job")
        else:
            by_id[cid] = _item(
                cid, "blocked", reason=row.reason, reason_label=row.reason_label
            )
    for row in warnings:
        if row.candidate_id in by_id:
            by_id[row.candidate_id]["warnings"].append(
                {"reason": row.reason, "reason_label": row.reason_label}
            )
    return [by_id[cid] for cid in ids if cid in by_id]


def _add_body(job_id: int, items: list[dict]) -> dict:
    added = sum(1 for item in items if item["status"] == "added")
    proposed = sum(1 for item in items if item["status"] == "proposed")
    return {
        "job_id": job_id,
        "items": items,
        "added": added,
        "proposed": proposed,
        "skipped": len(items) - added - proposed,
    }


@router.post(
    "/recruitments/{job_id}/candidates",
    response_model=RecruitmentAddOut,
    summary="Dodaj osoby do rekrutacji",
)
@limiter.limit(write_rate_limit, key_func=principal_rate_key)
async def add_recruitment_candidates(
    request: Request,
    job_id: IdPath,
    body: RecruitmentAddIn,
    caller: RecruitmentsWrite,
    db: AsyncSession = Depends(get_db),
    dry_run: bool = Query(
        False, description="Tylko werdykty (Tablica / propozycja / odmowa)."
    ),
) -> Response:
    """Osoba, która zgłosiła się do tej rekrutacji, trafia na Tablicę
    (``added``); pozostałe — do „Do przejrzenia” jako propozycja
    (``proposed``), jak przy każdej integracji. Osoba już w rekrutacji:
    ``already_in_job``, z kartą w „Zamkniętych”: ``closed_in_job`` (przywraca
    się ją ruchem karty). Globalna czarna lista i weto hiring managera:
    ``blocked`` z powodem; konflikty z klientem nie blokują (``warnings``)."""
    ids = list(dict.fromkeys(body.candidate_ids))
    added_ids: list[int] = []

    async def run():
        job = await _job_or_404(db, job_id)
        if body.stage_def_id is not None:
            # Ta sama walidacja co dodanie (szablon, kolumna wejścia) — także
            # gdy nikt nie trafi na Tablicę, a w próbie bez zapisu.
            await proposals_bulk._resolve_initial_stage(db, job, body.stage_def_id)
        add_ids, propose_ids = await proposals_bulk.split_by_application(
            db, job_id=job.id, candidate_ids=ids
        )
        if dry_run:
            items = await _add_verdicts(db, job=job, ids=ids, add_ids=add_ids)
            return 200, _add_body(job.id, items)
        proposal = (
            await proposals_bulk.propose_candidates_for_job(
                db, job=job, candidate_ids=propose_ids, entry_meta=None
            )
            if propose_ids
            else None
        )
        intake = (
            await proposals_bulk.add_candidates_to_job(
                db,
                job=job,
                candidate_ids=add_ids,
                actor_user_id=None,
                initial_stage_def_id=body.stage_def_id,
                note=body.note,
                entry_source=candidate_claim.ENTRY_AUTO_MATCH,
                claim=False,
                mark_proposals=False,
            )
            if add_ids
            else None
        )
        if intake is not None:
            added_ids.extend(intake.added)
        items = await _add_items(db, job=job, ids=ids, proposal=proposal, intake=intake)
        return 200, _add_body(job.id, items)

    if dry_run:
        return await dry_run_response(db, run)
    response = await idempotent_write(
        request,
        db,
        caller,
        payload={"job_id": job_id, **body.model_dump(mode="json")},
        run=run,
    )
    if added_ids:
        await _after_add(db, job_id=job_id, added=added_ids)
    return response


async def _after_add(db: AsyncSession, *, job_id: int, added: list[int]) -> None:
    """Po commicie, jak ``proposals/bulk``: Tablica na żywo i telemetria
    dopasowań (źródło ``integration``). Oba nigdy nie rzucają."""
    from app.services.match_telemetry_service import (
        emit_pipeline_additions,
        latest_process_ids,
    )

    await broadcast_pipeline_changed(db, job_id, None)
    await emit_pipeline_additions(
        job_id=job_id,
        candidate_ids=added,
        user_id=None,
        run_id=None,
        source="integration",
        process_ids=await latest_process_ids(db, job_id, added),
    )


# ── Ruch karty ───────────────────────────────────────────────────────────────


async def _move_out(db: AsyncSession, outcome: pipeline_routes.MoveApplied) -> dict:
    # Zapisy ruchu (wersja procesu) do bazy przed odczytem kolumn — sesja nie
    # robi autoflush.
    await db.flush()
    stage = outcome.stage
    versions = await pipeline_routes._process_state_versions(
        db, job_id=outcome.job_id, candidate_ids=[outcome.candidate_id]
    )
    return {
        "card_id": stage.id,
        "candidate_id": outcome.candidate_id,
        "job_id": outcome.job_id,
        "stage": _value(stage.stage),
        "stage_def_id": stage.stage_def_id,
        "stage_name": outcome.stage_display_name,
        "column": outcome.target_column,
        "moved_at": stage.moved_at,
        "process_state_version": versions.get(outcome.candidate_id, 0),
        "rejection_reason_id": stage.rejection_reason_id,
        "ended_by": stage.ended_by,
        "eligibility_acknowledged": _value(outcome.eligibility_acknowledged),
    }


@router.post(
    "/recruitments/{job_id}/moves",
    response_model=CardMoveOut,
    summary="Przesuń kartę osoby w rekrutacji",
)
@limiter.limit(write_rate_limit, key_func=principal_rate_key)
async def move_recruitment_card(
    request: Request,
    job_id: IdPath,
    body: CardMoveIn,
    caller: RecruitmentsWrite,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Ten sam ruch co na Tablicy, z jej bramkami. Klucz nie zatrudnia, nie
    wysyła kandydata do klienta i nie prowadzi kolejki Cpro (403
    ``requires_screen_decision``); zamyka kartę z powodem, bez maila do
    kandydata. Osoba spoza rekrutacji: 409 ``not_in_recruitment``."""
    applied: list[pipeline_routes.MoveApplied] = []

    async def run():
        await _job_or_404(db, job_id)
        if (
            await db.scalar(
                select(Candidate.id).where(Candidate.id == body.candidate_id)
            )
            is None
        ):
            raise HTTPException(404, detail="Kandydat nie istnieje.")
        outcome = await pipeline_routes.apply_move(
            db,
            StageMove(
                candidate_id=body.candidate_id,
                job_id=job_id,
                stage_def_id=body.to_stage_def_id,
                expected_state_version=body.expected_state_version,
                rejection_reason_id=body.rejection_reason_id,
                rejection_reason=body.rejection_reason,
                acknowledge_eligibility=body.acknowledge_eligibility,
                send_rejection_email=False,
                work_mode_save_to_profile=False,
            ),
            policy=IntegrationMovePolicy(principal_of(caller), db),
            request=request,
        )
        if not isinstance(outcome, pipeline_routes.MoveApplied):  # pragma: no cover
            # Propozycję (osoba spoza rekrutacji) i powtórkę „Zatrudniony”
            # polityka API odrzuca wcześniej; tu tylko nie udajemy ruchu.
            raise HTTPException(409, detail="Ruch nie został zapisany.")
        applied.append(outcome)
        return 200, await _move_out(db, outcome)

    response = await idempotent_write(
        request,
        db,
        caller,
        payload={"job_id": job_id, **body.model_dump(mode="json")},
        run=run,
    )
    # Po commicie (powtórka z paragonu nie woła `run` — efektów drugi raz nie
    # ma): to samo co Tablica, bez osoby w powiadomieniach.
    for outcome in applied:
        await pipeline_routes.run_move_effects(db, outcome, mover=None)
        pipeline_routes._spawn_cv_qc_after_move(
            outcome.target_column, outcome.stage.id, None
        )
    return response
