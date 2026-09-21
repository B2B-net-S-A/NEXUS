"""Bulk-add candidates to a job pipeline (manual search → recruitment).

Single-candidate moves use ``POST /api/pipeline/move`` (terminal validation,
verification gate, rate snapshot). For *manual search* bulk-add the user just
wants to place 1–100 candidates into the job's first non-terminal stage in
one click; this endpoint is the minimal safe variant of that.

Skipped on purpose:

* Terminal-stage validation — bulk-add never targets a terminal stage.
* Verification gate (rate vs salary_max) — only triggers on ``verified``,
  which manual search never targets.
* Rejection-reason FK — N/A for bulk-add (entry stage is non-terminal).

Returned shape lets the UI render a "Added 7, skipped 3" toast with reasons.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RecruiterPlus
from app.api.recruitment_access import ensure_job_membership
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.note import Note, NoteType
from app.models.pipeline_template import PipelineStageDef
from app.models.recruitment_pipeline import (
    CandidateStage,
    PipelineStage,
)
from app.models.recruitment_priority import PriorityChannel
from app.services.candidate_stage_cv_service import create_original_cv_snapshot
from app.services.candidate_contact_hooks import maybe_ensure_contact_opportunity
from app.services.candidate_job_eligibility import EligibilityReason
from app.services.pipeline_eligibility import (
    detail_for,
    evaluate_candidates_for_job_with_verdicts,
)
from app.services.pipeline_realtime import broadcast_pipeline_changed
from app.services.priority_work_policy import milestone_counts_scope
from app.services.recruitment_process_commands import (
    canonical_candidate_lock_order,
    open_process,
)

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)

SkipReason = Literal[
    "already_in_job",
    "blacklisted",
    "candidate_not_found",
    "rejected_by_hiring_manager",
]
# Client conflicts (blacklist / NDA / competitor) are soft warnings since
# 17.09.2026: the candidate IS added and the reason rides in ``warnings``.
WarningReason = Literal[
    "client_blacklist",
    "client_nda",
    "client_competitor",
    "current_employment",
    "excluded_by_candidate",
]
# The screen an add came from — the callers of this route. A closed
# vocabulary on purpose: it lands in the analytics table (PII policy).
# ``talent_radar`` (result card of a Radar run, which has no job) and
# ``candidate_list`` (bulk bar of /candidates) joined on 17.09.2026.
BulkAddSource = Literal[
    "full_search",
    "manual_search",
    "historical",
    "quick_add",
    "talent_radar",
    "candidate_list",
    # Jarvis (0330): dodanie zaproponowane przez asystenta i potwierdzone
    # kliknięciem człowieka na karcie akcji.
    "jarvis",
]

# Eligibility reason → bulk-add skip reason. Reasons that block assignment.
_SKIP_REASON_BY_ELIGIBILITY: dict[EligibilityReason, SkipReason] = {
    EligibilityReason.blacklisted: "blacklisted",
    EligibilityReason.already_in_job: "already_in_job",
    # Missing entry here would fall through to the `"blacklisted"` default below
    # and report a manager's rejection as a global blacklist.
    EligibilityReason.rejected_by_hiring_manager: "rejected_by_hiring_manager",
}
# Eligibility reason → non-blocking warning surfaced on added candidates.
_WARNING_REASON_BY_ELIGIBILITY: dict[EligibilityReason, WarningReason] = {
    EligibilityReason.client_blacklist: "client_blacklist",
    EligibilityReason.client_nda: "client_nda",
    EligibilityReason.client_competitor: "client_competitor",
    EligibilityReason.client_current_employment: "current_employment",
    EligibilityReason.client_excluded_by_candidate: "excluded_by_candidate",
}


class BulkProposalsRequest(BaseModel):
    candidate_ids: list[int] = Field(..., min_length=1, max_length=100)
    initial_stage_def_id: Optional[int] = Field(
        default=None,
        description=(
            "Optional pipeline stage to place candidates into. Defaults to the"
            " template's first non-terminal stage other than `posting`"
            " (or PipelineStage.new)."
        ),
    )
    initial_stage_legacy: Optional[str] = Field(
        default=None,
        description=(
            "Alternatywa dla initial_stage_def_id po legacy enumie (np."
            " 'posting' dla kandydatów z ogłoszeń) — rozwiązywana w szablonie"
            " rekrutacji; gdy szablon nie ma takiego etapu, działa domyślne."
        ),
    )
    note: Optional[str] = Field(default=None, max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    # Match telemetry only. This route is shared by manual search, the
    # historical section, quick-add and the job page's full search, so the
    # server cannot tell which ranking (if any) an add followed from. Only the
    # full-search screen knows its run and sends it; the outcome is attributed
    # to that run only when the run is this user's, for this job, and showed
    # the candidate (`emit_pipeline_additions`). Never guessed from history.
    run_id: Optional[str] = Field(default=None, max_length=64)
    source: Optional[BulkAddSource] = None


class BulkSkippedRow(BaseModel):
    candidate_id: int
    reason: SkipReason
    reason_label: Optional[str] = None


class BulkWarningRow(BaseModel):
    """A candidate that WAS added but carries a soft eligibility warning
    (a client conflict — blacklist / NDA / competitor — current employment at
    the client, or the candidate excluded them)."""

    candidate_id: int
    reason: WarningReason
    reason_label: Optional[str] = None


class BulkProposalsResponse(BaseModel):
    added: list[int]
    skipped: list[BulkSkippedRow]
    warnings: list[BulkWarningRow] = Field(default_factory=list)
    total_added: int
    total_skipped: int


class AssignableStage(BaseModel):
    """A pipeline stage a candidate can be bulk-added into (non-terminal, and
    excluding ``verified`` which needs a per-recruitment rate + DL gate)."""

    id: int
    name: str
    order: int
    legacy_enum_value: Optional[str] = None


@router.get(
    "/jobs/{job_id}/assignable-stages",
    response_model=list[AssignableStage],
    summary="Pipeline stages a candidate can be bulk-added into",
)
async def list_assignable_stages(
    job_id: int,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> list[AssignableStage]:
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    # Odczyt towarzyszący zapisowi niżej — bez tej samej bramki zamknięcie
    # `bulk_add_proposals` byłoby połowiczne: dropdown etapów wciąż zdradzałby
    # nazwy, identyfikatory i kolejność szablonu obcej rekrutacji.
    await ensure_job_membership(db, current_user, job_id)
    if not job.pipeline_template_id:
        return []
    rows = (
        (
            await db.execute(
                select(PipelineStageDef)
                .where(
                    PipelineStageDef.template_id == job.pipeline_template_id,
                    PipelineStageDef.is_terminal.is_(False),
                )
                .order_by(PipelineStageDef.order.asc())
            )
        )
        .scalars()
        .all()
    )
    return [
        AssignableStage(
            id=s.id, name=s.name, order=s.order, legacy_enum_value=s.legacy_enum_value
        )
        for s in rows
        if s.legacy_enum_value != PipelineStage.verified.value
    ]


def _legacy_enum_for(
    stage_def: Optional[PipelineStageDef],
    legacy_value: Optional[str],
    *,
    has_template: bool,
) -> PipelineStage:
    """Legacy-enum etapu zapisywany na `candidate_stages.stage`.

    Z szablonem — enum kolumny, na którą trafił kandydat. Bez szablonu
    (rekrutacje legacy, kanban z `STAGE_ORDER`) integracje mogą wskazać
    `posting`: inaczej auto-match z ogłoszeń lądował tam na „Nowi", a na
    rekrutacjach z szablonem w „Ogłoszeniach" — dwa zachowania jednej
    integracji. Tylko `posting`: to jedyny etap sprzed lejka, każdy inny
    legacy bez szablonu nadal daje „Nowi".
    """
    if stage_def is not None and stage_def.legacy_enum_value:
        try:
            return PipelineStage(stage_def.legacy_enum_value)
        except ValueError:
            return PipelineStage.new
    if not has_template and legacy_value == PipelineStage.posting.value:
        return PipelineStage.posting
    return PipelineStage.new


async def _resolve_initial_stage(
    db: AsyncSession,
    job: Job,
    override_id: Optional[int],
    legacy_value: Optional[str] = None,
) -> Optional[PipelineStageDef]:
    """First non-terminal stage from the job's template, or the override.

    Domyślnie POMIJA `posting` (Ogłoszenia): to poczekalnia dla auto-matchu z
    portali, a ręczne bulk-add ma trafiać do „Nowi" jak dotąd. Integracje
    wskazują `posting` jawnie przez ``legacy_value``.
    """
    if override_id is None and legacy_value and job.pipeline_template_id:
        by_legacy = await db.scalar(
            select(PipelineStageDef).where(
                PipelineStageDef.template_id == job.pipeline_template_id,
                PipelineStageDef.legacy_enum_value == legacy_value,
                PipelineStageDef.is_terminal.is_(False),
            )
        )
        if by_legacy is not None and legacy_value != PipelineStage.verified.value:
            return by_legacy
    if override_id is not None:
        stage_def = await db.scalar(
            select(PipelineStageDef).where(PipelineStageDef.id == override_id)
        )
        if not stage_def:
            raise HTTPException(
                status_code=422, detail="initial_stage_def_id not found"
            )
        if stage_def.template_id != job.pipeline_template_id:
            raise HTTPException(
                status_code=422,
                detail="initial_stage_def_id does not belong to this job's template",
            )
        if stage_def.is_terminal:
            raise HTTPException(
                status_code=422,
                detail="initial_stage_def_id must be a non-terminal stage",
            )
        # Stage 'verified' wymaga stawki per rekrutacja + gate'u DL (migracja
        # 0056) — bulk-add nie zbiera stawek, więc nie może tam celować.
        if stage_def.legacy_enum_value == PipelineStage.verified.value:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Etap 'verified' wymaga stawki i weryfikacji DL — użyj"
                    " POST /api/pipeline/move dla pojedynczego kandydata."
                ),
            )
        return stage_def

    if not job.pipeline_template_id:
        return None

    stage_def = await db.scalar(
        select(PipelineStageDef)
        .where(
            PipelineStageDef.template_id == job.pipeline_template_id,
            PipelineStageDef.is_terminal.is_(False),
            (PipelineStageDef.legacy_enum_value.is_(None))
            | (PipelineStageDef.legacy_enum_value != PipelineStage.posting.value),
        )
        .order_by(PipelineStageDef.order.asc())
        .limit(1)
    )
    return stage_def


def _merge_tags(existing: list, incoming: list[str]) -> list:
    """Dołóż tagi bez duplikatów, nie psując istniejących wpisów.

    ``candidate.tags`` bywa listą stringów, ale też listą słowników
    (``{"name": ...}`` z importów/enrichmentu). ``{*existing, *incoming}``
    rzucało ``TypeError: unhashable type: 'dict'`` i cały bulk-add dostawał 500.
    Istniejące wpisy zostają w oryginalnej postaci; nowe stringi są dodawane,
    gdy nie ma ich ani jako string, ani jako ``name``/``label`` słownika.
    """
    seen: set[str] = set()
    for item in existing:
        if isinstance(item, str):
            seen.add(item.strip().lower())
        elif isinstance(item, dict):
            label = item.get("name") or item.get("label") or item.get("tag")
            if isinstance(label, str):
                seen.add(label.strip().lower())
    merged = list(existing)
    for tag in incoming:
        key = tag.strip().lower()
        if key and key not in seen:
            merged.append(tag.strip())
            seen.add(key)
    return merged


@dataclass
class IntakeResult:
    added: list[int]
    skipped: list[BulkSkippedRow]
    warnings: list[BulkWarningRow]
    stage_ids: dict[int, int]


async def add_candidates_to_job(
    db: AsyncSession,
    *,
    job: Job,
    candidate_ids: list[int],
    actor_user_id: Optional[int],
    initial_stage_def_id: Optional[int] = None,
    initial_stage_legacy: Optional[str] = None,
    note: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> IntakeResult:
    """Dodaj kandydatów do pipeline'u rekrutacji — jedna logika dla trasy i automatu.

    Wyciągnięte z `bulk_add_proposals` (17.09.2026), żeby auto-dopasowanie
    (`tasks/candidate_auto_match.py`) przechodziło DOKŁADNIE przez te same bramki
    co rekruter: blacklista, konflikty i NDA klienta, weto hiring managera,
    wykluczenia kandydata, już-w-procesie. Bez commita i bez sprawdzenia
    członkostwa w zespole — to robi wołający (trasa: `ensure_job_membership`;
    automat: działa w imieniu właściciela rekrutacji).
    """
    # Kanoniczna kolejność blokad — patrz `canonical_candidate_lock_order`.
    # Pętla niżej blokuje wiersz kandydata przez `open_process`, a jedyny commit
    # jest po pętli, więc surowa lista z requestu znaczyła, że dwa nakładające
    # się bulk-addy z odwróconą kolejnością zakleszczały się o siebie.
    # Deduplikacja przy okazji kasuje zdublowane wiersze w `skipped`.
    lock_ordered_ids = canonical_candidate_lock_order(candidate_ids)

    stage_def = await _resolve_initial_stage(
        db, job, initial_stage_def_id, initial_stage_legacy
    )
    legacy_enum = _legacy_enum_for(
        stage_def,
        initial_stage_legacy,
        has_template=job.pipeline_template_id is not None,
    )

    # Pre-fetch in two batches so we don't issue 100×2 round-trips.
    # Ten sam prefetch jest fazą 1 kolejności blokad: komplet kandydatów rosnąco
    # ZANIM `open_process` weźmie w pętli blokadę oferty. Bez tego pętla
    # przeplatała kandydat→oferta→kandydat i zakleszczała się z wsadowym
    # `sync_external_observed_processes` (Traffit). `FOR UPDATE` nie dokłada
    # rundy — to nadal jedno zapytanie.
    cand_rows = (
        (
            await db.execute(
                select(Candidate)
                .where(Candidate.id.in_(lock_ordered_ids))
                .order_by(Candidate.id)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    candidates_by_id: dict[int, Candidate] = {c.id: c for c in cand_rows}

    already_in_job = (
        (
            await db.execute(
                select(CandidateStage.candidate_id).where(
                    CandidateStage.job_id == job.id,
                    CandidateStage.candidate_id.in_(lock_ordered_ids),
                )
            )
        )
        .scalars()
        .all()
    )
    already_in_job_set: set[int] = set(already_in_job)

    # One shared eligibility read (``pipeline_eligibility``): active client
    # conflicts, current employment derived from live contracts, excluded
    # clients and standing hiring-manager rejections — batched once, reusing
    # the ``FOR UPDATE`` rows above instead of a second candidate SELECT.
    now = datetime.now(timezone.utc)
    decisions, manager_verdicts = await evaluate_candidates_for_job_with_verdicts(
        db,
        job=job,
        candidate_ids=lock_ordered_ids,
        now=now,
        already_in_job_ids=already_in_job_set,
        candidates=candidates_by_id,
    )

    added: list[int] = []
    stage_ids: dict[int, int] = {}
    skipped: list[BulkSkippedRow] = []
    warnings: list[BulkWarningRow] = []

    # Jeden skan progresu assignmentu na cały batch: bez tego każda
    # iteracja powtarza pełne zapytanie KPI trzymając blokadę wiersza joba.
    with milestone_counts_scope():
        for candidate_id in lock_ordered_ids:
            candidate = candidates_by_id.get(candidate_id)
            if candidate is None:
                skipped.append(
                    BulkSkippedRow(
                        candidate_id=candidate_id, reason="candidate_not_found"
                    )
                )
                continue

            # Single eligibility policy (SEARCH-P0-04). Hard blocks: global
            # blacklist, already in job, hiring-manager veto. Client conflicts
            # are warnings since 17.09.2026.
            decision = decisions[candidate_id]
            if not decision.assignment_allowed:
                # Name the manager and the date when the veto is what blocked —
                # "hiring manager already rejected" alone sends the recruiter
                # digging through the candidate's history to find out who.
                skipped.append(
                    BulkSkippedRow(
                        candidate_id=candidate_id,
                        reason=_SKIP_REASON_BY_ELIGIBILITY.get(
                            decision.reason_code, "blacklisted"
                        ),
                        reason_label=detail_for(
                            decision, manager_verdicts.get(candidate_id)
                        ),
                    )
                )
                continue

            # Assignment allowed — surface a soft warning if one applies.
            warn_reason = _WARNING_REASON_BY_ELIGIBILITY.get(decision.reason_code)
            if warn_reason is not None:
                warnings.append(
                    BulkWarningRow(
                        candidate_id=candidate_id,
                        reason=warn_reason,
                        reason_label=decision.reason,
                    )
                )

            stage = await open_process(
                db,
                candidate_id=candidate_id,
                job_id=job.id,
                stage=legacy_enum,
                stage_def_id=stage_def.id if stage_def else None,
                actor_user_id=actor_user_id,
                work_channel=PriorityChannel.database,
            )
            # M3-ACT-01: every stage-creating entry point must snapshot the CV that
            # was current at assignment (the evidence of what was submitted) + emit
            # the `snapshot_created` audit — same invariant the single-assign path
            # (recommendations.assign_candidate_to_job) already holds. Bulk-add was
            # skipping it, so a client dispute could lack the sent CV. Idempotent +
            # fail-soft on a missing CV, so it never breaks the batch.
            await create_original_cv_snapshot(db, stage)
            # Etap pochodzi z command service (writer fence), więc okazja
            # kontaktu wisi na jego wierszu, nie na własnym `CandidateStage`.
            await maybe_ensure_contact_opportunity(
                db,
                candidate_id=candidate_id,
                job_id=job.id,
                source="pipeline",
                occurred_at=stage.moved_at,
            )

            # Optional shared note attached to every newly added candidate.
            if note:
                db.add(
                    Note(
                        content=note,
                        note_type=NoteType.general,
                        candidate_id=candidate_id,
                        job_id=job.id,
                        author_id=actor_user_id,
                    )
                )

            # Optional shared tags merged into the candidate's tags JSONB. We
            # treat candidate.tags as a list when populated and a placeholder dict
            # otherwise — same convention as the rest of the codebase.
            if tags:
                existing = candidate.tags
                if isinstance(existing, list):
                    candidate.tags = _merge_tags(existing, tags)
                elif isinstance(existing, dict) and "items" in existing:
                    candidate.tags = {
                        "items": _merge_tags(existing.get("items") or [], tags)
                    }
                else:
                    candidate.tags = _merge_tags([], tags)

            added.append(candidate_id)
            stage_ids[candidate_id] = stage.id

    return IntakeResult(
        added=added, skipped=skipped, warnings=warnings, stage_ids=stage_ids
    )


@router.post(
    "/jobs/{job_id}/proposals/bulk",
    response_model=BulkProposalsResponse,
    summary="Bulk-add candidates to job pipeline (manual search → recruitment)",
)
async def bulk_add_proposals(
    job_id: int,
    body: BulkProposalsRequest,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> BulkProposalsResponse:
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    # Ta sama bramka co na pięciu trasach shortlisty (`job_shortlist.py`).
    # Bez niej containment był niespójny w gorszą stronę: zaparkowanie
    # kandydata na shortliście dawało 403, a cięższe wpisanie go wprost do
    # pipeline'u — z tego samego ekranu, na tę samą obcą ofertę — przechodziło.
    await ensure_job_membership(db, current_user, job_id)

    result = await add_candidates_to_job(
        db,
        job=job,
        candidate_ids=body.candidate_ids,
        actor_user_id=current_user.id,
        initial_stage_def_id=body.initial_stage_def_id,
        initial_stage_legacy=body.initial_stage_legacy,
        note=body.note,
        tags=body.tags,
    )
    added, skipped, warnings = result.added, result.skipped, result.warnings

    actor_id = current_user.id
    await db.commit()
    if added:
        # Live kanban: the rest of the team re-reads the board (best-effort).
        await broadcast_pipeline_changed(db, job_id, actor_id)

    # Match telemetry (no-op unless AI_MATCH_TELEMETRY_ENABLED): one
    # `add_to_pipeline` outcome per candidate that actually entered the
    # pipeline — never for skipped ones — attributed to the run the caller
    # declared, and only if that run verifiably showed this user the candidate
    # for this job; otherwise `run_id` stays NULL. AFTER the commit and in the
    # telemetry service's own session: it cannot undo or fail the add (it never
    # raises), and it writes at most one row per id.
    if added:
        from app.services.match_telemetry_service import emit_pipeline_additions

        await emit_pipeline_additions(
            job_id=job_id,
            candidate_ids=added,
            user_id=actor_id,
            run_id=body.run_id,
            source=body.source,
        )

    return BulkProposalsResponse(
        added=added,
        skipped=skipped,
        warnings=warnings,
        total_added=len(added),
        total_skipped=len(skipped),
    )
