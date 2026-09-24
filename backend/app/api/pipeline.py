import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from pydantic import BaseModel, Field
from collections.abc import Iterable, Mapping, Sequence
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.recruitment_pipeline import (
    CandidateStage,
    PipelineStage,
    STAGE_CATEGORY,
    STAGE_ORDER,
    VerificationStatus,
)
from app.models.recruitment_priority import PriorityChannel
from app.models.recruitment_process import RecruitmentProcess
from app.models.activity import Activity
from app.models.user_activity import UserActivity, UserActionType
from app.models.notification import Notification, NotificationType
from app.services import board_tasks as board_tasks_svc
from app.services import candidate_audit, candidate_claim, pipeline_move_rules
from app.models.contract import RateUnit
from app.services.board_stage_badges import (
    board_column_for,
    ensure_badge_stage_allowed,
    foreign_stage_target,
    is_cpro_stage,
)
from app.services import champion_view
from app.services.candidate_stage_cv_service import (
    create_original_cv_snapshot,
)
from app.services.candidate_contact_hooks import (
    load_contact_case_summaries,
    maybe_close_contact_opportunity,
    maybe_ensure_contact_opportunity,
)
from app.services.b2b_contract_automation import ensure_b2b_employment_draft
from app.models.job import Job, JobStatus
from app.models.pipeline_template import (
    PipelineStageDef,
    PipelineTemplate,
    RejectionReason,
    TerminalType,
)
from app.models.user import User
from app.schemas.pipeline import (
    CandidateStageResponse,
    HiringManagerVetoBrief,
    KanbanColumn,
    KanbanView,
    MyNextStepsJob,
    MyNextStepsResponse,
    OffTemplateColumn,
    StageMove,
    StageInfo,
    STAGE_LABELS,
)
from app.api.candidate_access import (
    CandidatePIIAccess,
    resolve_client_rate_write,
    user_can_view_client_rate,
    user_has_candidate_read,
)
from app.api.deps import CurrentUser, OperationalUser, RecruiterPlus
from app.api.recruitment_access import (
    ensure_job_read_access,
    ensure_job_membership,
    user_can_edit_rates,
    user_can_terminal_transition,
)
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.services.hiring_manager_verdicts import (
    puts_candidate_before_client,
    veto_for_candidate_stage,
)
from app.services.pipeline_eligibility import (
    assert_candidates_move_eligible,
    check_candidate_move_eligibility,
    evaluate_candidates_for_job_with_verdicts,
)
from app.services.pipeline_next_action import (
    StageColumn,
    group_keys_for_columns,
    next_action_for,
)
from app.services.rate_normalization import (
    POLICY_VERSION as RATE_POLICY_VERSION,
    normalize_rate_to_monthly,
)
from app.services.recruitment_process_commands import (
    canonical_candidate_lock_order,
    lock_candidates_stmt,
    transition_process,
)
from app.services.delivery_alert_recipients import load_delivery_alert_recipient_scope
from app.services.pipeline_realtime import broadcast_pipeline_changed
from app.core.scheduling import business_today

# Terminal wynikający wprost z legacy enuma — używane w gałęzi bez szablonu
# pipeline'u, żeby `KanbanColumn.terminal_type` był wypełniany tak samo jak
# w gałęzi z szablonem.
_LEGACY_TERMINAL_TYPE: dict[
    PipelineStage, Literal["hired", "rejected", "withdrawn"]
] = {
    PipelineStage.hired: "hired",
    PipelineStage.rejected: "rejected",
    PipelineStage.withdrawn: "withdrawn",
}

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)
logger = logging.getLogger(__name__)


# Referencje zadań w tle (fire-and-forget ``create_task`` gubi je pod GC —
# pętla zdarzeń trzyma tylko słabą referencję). Wzorzec z app/api/cortex.py,
# rozszerzony o log: powiadomienie Teams padłe w zadaniu nie ma czytelnika,
# więc bez done_callbacku znika bez śladu.
_bg_tasks: set[asyncio.Task] = set()


def _spawn(coro, label: str) -> None:
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)

    def _done(finished: asyncio.Task) -> None:
        _bg_tasks.discard(finished)
        if finished.cancelled():
            logger.warning("pipeline background task cancelled: %s", label)
            return
        exc = finished.exception()
        if exc is not None:
            logger.exception("pipeline background task failed: %s", label, exc_info=exc)

    task.add_done_callback(_done)


# ── Helpers to bridge legacy enum ↔ new stage_def FK ────────────────────────


async def _default_template_id(db: AsyncSession) -> Optional[int]:
    """Return id of the is_default=true template (or None if unseeded)."""
    return await db.scalar(
        select(PipelineTemplate.id).where(PipelineTemplate.is_default.is_(True))
    )


async def _resolve_stage_def(
    db: AsyncSession,
    job: Optional[Job],
    *,
    stage_def_id: Optional[int] = None,
    legacy_stage: Optional[PipelineStage] = None,
) -> Optional[PipelineStageDef]:
    """Resolve a StageDef from either explicit id or legacy enum (via template)."""
    if stage_def_id:
        return await db.scalar(
            select(PipelineStageDef).where(PipelineStageDef.id == stage_def_id)
        )
    if legacy_stage is None:
        return None

    template_id = (
        job.pipeline_template_id if job else None
    ) or await _default_template_id(db)
    if not template_id:
        return None
    return await db.scalar(
        select(PipelineStageDef).where(
            PipelineStageDef.template_id == template_id,
            PipelineStageDef.legacy_enum_value == legacy_stage.value,
        )
    )


def _days_in_stage(moved_at: datetime) -> int:
    """Calculate days a candidate has been in the current stage."""
    now = datetime.now(timezone.utc)
    if moved_at.tzinfo is None:
        from datetime import timezone as tz

        moved_at = moved_at.replace(tzinfo=tz.utc)
    return max(0, (now - moved_at).days)


def _budget_exceeded(stage: CandidateStage) -> bool:
    """Czy stawka zapisana przy ruchu przekracza budżet zamrożony na etapie.

    Liczone w jednej jednostce (miesięcznej), jak dawna bramka „Pending".
    Stawka w walucie/jednostce, której nie da się przeliczyć, NIE daje
    odznaki — „ponad budżet" ma być stwierdzeniem faktu, nie domysłem.
    """
    if stage.expected_rate_value is None or stage.budget_max_at_move is None:
        return False
    normalized, _note = normalize_rate_to_monthly(
        Decimal(stage.expected_rate_value),
        stage.expected_rate_unit,
        stage.expected_rate_currency,
    )
    return normalized is not None and normalized > Decimal(stage.budget_max_at_move)


def _reported_verification_status(stage: CandidateStage) -> VerificationStatus:
    """Status weryfikacji widziany przez klienta — `pending` czytany jako aktywny.

    Bramka „Oczekuje" została usunięta (17.09.2026), więc żaden writer nie
    zapisuje już `pending`. Wartość zostaje w enumie bazy dla wierszy
    historycznych (`ALTER TYPE … DROP VALUE` w Postgresie nie istnieje), a te
    nie mogą wyglądać na kartę czekającą na decyzję, której nikt nie podejmie.
    """
    if stage.verification_status == VerificationStatus.pending:
        return VerificationStatus.active
    return stage.verification_status


def _http_detail_text(detail: object) -> str:
    """Tekst z `HTTPException.detail` — string albo dict z `message`.

    `ensure_b2b_employment_draft` rzuca oba kształty (`_conflict_detail` daje
    dict z `message` i listą kontraktów).
    """
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict) and isinstance(detail.get("message"), str):
        return detail["message"]
    return str(detail)


def _sheet_filled(payload: object) -> bool:
    """Czy arkusz JSONB (screening / scorecard) ma treść.

    `ScreeningAnswers` zapisuje domyślnie `{"answers": [], ...}` — sam
    `bool(dict)` dałby fałszywe „wypełniony" i odznaka „do uzupełnienia"
    znikałaby z karty, na której nikt niczego nie wpisał.
    """
    if not isinstance(payload, dict) or not payload:
        return False
    answers = payload.get("answers")
    if isinstance(answers, (list, dict)):
        return len(answers) > 0
    return any(value not in (None, "", [], {}) for value in payload.values())


def _stage_response(
    stage: CandidateStage,
    *,
    candidate_name: Optional[str] = None,
    candidate_lastname: Optional[str] = None,
    added_to_job_by_name: Optional[str] = None,
    added_to_job_at: Optional[datetime] = None,
    candidate_expected_rate_hourly: Optional[Decimal] = None,
    # Bez wartości domyślnej: każdy wołający decyduje jawnie
    # (`user_can_view_client_rate`) — zapomniany argument nie może odsłonić
    # stawki do klienta rekruterowi.
    show_client_rate: bool,
) -> dict:
    """Convert a CandidateStage to response dict with days_in_stage.

    Candidate name/lastname are optional — populated by the Kanban endpoint
    so the frontend can render card titles without an extra round-trip.

    ``added_to_job_by_name`` / ``added_to_job_at`` describe WHO assigned the
    candidate to the recruitment and WHEN — i.e. the mover on the *earliest*
    stage of this candidate/job pair, not the current-stage mover. Also
    populated by the Kanban endpoint (NULL elsewhere).
    """
    return {
        "id": stage.id,
        "candidate_id": stage.candidate_id,
        "job_id": stage.job_id,
        "stage": stage.stage,
        "stage_def_id": stage.stage_def_id,
        "rejection_reason_id": stage.rejection_reason_id,
        "moved_at": stage.moved_at,
        "moved_by": stage.moved_by,
        "notes": stage.notes,
        "rating": stage.rating,
        "created_at": stage.created_at,
        "days_in_stage": _days_in_stage(stage.moved_at),
        # Snapshot stawki i budżetu (migracja 0056). `pending` zapisany przed
        # 17.09.2026 nie jest stanem, na który ktokolwiek może zareagować —
        # raportujemy `active`, żeby żadna karta nie renderowała „oczekuje
        # na akceptację".
        "verification_status": _reported_verification_status(stage),
        "expected_rate_value": stage.expected_rate_value,
        "expected_rate_unit": stage.expected_rate_unit,
        "expected_rate_currency": stage.expected_rate_currency,
        "budget_max_at_move": stage.budget_max_at_move,
        # Informacja, nie bramka (decyzja 17.09.2026): stawka zapisana przy
        # ruchu przekracza zamrożony budżet rekrutacji. Karta pokazuje odznakę.
        "budget_exceeded": _budget_exceeded(stage),
        "approved_by": stage.approved_by,
        "approved_at": stage.approved_at,
        "rejected_by": stage.rejected_by,
        "rejected_at": stage.rejected_at,
        "rejection_note": stage.rejection_note,
        # Reakcja kandydata na ofertę (migracja 0066). Zapisywana od dawna
        # (modal wycofania po akceptacji), ale do 09.2026 NIGDZIE nie odczytywana
        # przez UI — „Przyjął / Odrzucił / Oczekuje" dawało się zobaczyć wyłącznie
        # w bazie. Krok 07 „Rozmowy i decyzja" pokazuje ją przy ofercie; `None`
        # znaczy „nie zapisano", a nie „oczekuje" (to osobna, jawna wartość).
        "candidate_offer_response": stage.candidate_offer_response,
        "name": candidate_name,
        "lastname": candidate_lastname,
        "added_to_job_by_name": added_to_job_by_name,
        "added_to_job_at": added_to_job_at,
        # Odznaki karty (17.09.2026) — patrz `CandidateStageResponse`.
        "screening_done": _sheet_filled(stage.screening_answers),
        "scorecard_done": _sheet_filled(stage.scorecard_answers),
        "candidate_expected_rate_hourly": candidate_expected_rate_hourly,
        "task_assignee_id": stage.task_assignee_id,
        # Pipeline v4 (0352).
        "ended_by": stage.ended_by,
        # Stawki do klienta nie widzą rekruter, sourcer i TAC (23.09.2026).
        "client_rate_value": stage.client_rate_value if show_client_rate else None,
        "client_rate_unit": stage.client_rate_unit if show_client_rate else None,
        "client_rate_currency": (
            stage.client_rate_currency if show_client_rate else None
        ),
    }


async def _process_state_versions(
    db: AsyncSession, *, job_id: int, candidate_ids: Iterable[int]
) -> dict[int, int]:
    """Wersja najnowszego procesu każdej pary (kandydat, ta rekrutacja).

    F05: klient odsyła ją jako ``expected_state_version`` przy ruchu, a
    ``transition_process`` porównuje ją z ``state_version`` procesu wskazanego
    tym samym porządkiem (``attempt_no`` malejąco, potem ``id``). Jedno
    zapytanie hurtowe dla całej tablicy — bez N+1. Para bez procesu nie trafia
    do słownika; wołający traktuje brak jako 0 (lustro backendu).
    """
    ids = sorted(set(candidate_ids))
    if not ids:
        return {}
    rows = await db.execute(
        select(RecruitmentProcess.candidate_id, RecruitmentProcess.state_version)
        .where(
            RecruitmentProcess.job_id == job_id,
            RecruitmentProcess.candidate_id.in_(ids),
        )
        .order_by(
            RecruitmentProcess.candidate_id,
            RecruitmentProcess.attempt_no.desc(),
            RecruitmentProcess.id.desc(),
        )
        .distinct(RecruitmentProcess.candidate_id)
    )
    return {cid: int(version or 0) for cid, version in rows.all()}


async def _process_v4_cards(
    db: AsyncSession, *, job_id: int, candidate_ids: Iterable[int]
) -> dict[int, RecruitmentProcess]:
    """Najnowszy proces każdej pary — pola Pipeline v4 (blokada, źródło).

    Osobne od :func:`_process_cards`, bo tamto zwraca krotki czytane w kilku
    miejscach. Jedno zapytanie dla całej tablicy.
    """
    ids = sorted(set(candidate_ids))
    if not ids:
        return {}
    rows = await db.execute(
        select(RecruitmentProcess)
        .where(
            RecruitmentProcess.job_id == job_id,
            RecruitmentProcess.candidate_id.in_(ids),
        )
        .order_by(
            RecruitmentProcess.candidate_id,
            RecruitmentProcess.attempt_no.desc(),
            RecruitmentProcess.id.desc(),
        )
        .distinct(RecruitmentProcess.candidate_id)
    )
    return {p.candidate_id: p for p in rows.scalars().all()}


async def _process_cards(
    db: AsyncSession, *, job_id: int, candidate_ids: Iterable[int]
) -> dict[int, tuple[int, Optional[int]]]:
    """``(state_version, owner_user_id)`` najnowszego procesu każdej pary.

    Ten sam porządek co :func:`_process_state_versions` (jedno zapytanie dla
    całej tablicy); dokłada właściciela procesu dla pola ``recruiter_id`` karty.
    """
    ids = sorted(set(candidate_ids))
    if not ids:
        return {}
    rows = await db.execute(
        select(
            RecruitmentProcess.candidate_id,
            RecruitmentProcess.state_version,
            RecruitmentProcess.owner_user_id,
        )
        .where(
            RecruitmentProcess.job_id == job_id,
            RecruitmentProcess.candidate_id.in_(ids),
        )
        .order_by(
            RecruitmentProcess.candidate_id,
            RecruitmentProcess.attempt_no.desc(),
            RecruitmentProcess.id.desc(),
        )
        .distinct(RecruitmentProcess.candidate_id)
    )
    return {cid: (int(version or 0), owner) for cid, version, owner in rows.all()}


@router.get("/stages", response_model=List[StageInfo])
async def list_stages(
    current_user: CurrentUser,
    job_id: Optional[int] = Query(
        None, description="If provided, return stages of this job's template."
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Return pipeline stages.

    - With `job_id`: stages of the template attached to that job.
    - Without: stages of the default template.

    Fallback: if no templates exist yet (e.g. during migration), returns the
    legacy hardcoded enum stages so the UI keeps rendering.
    """
    # Resolve template id
    template_id: Optional[int] = None
    if job_id is not None:
        job = await db.scalar(select(Job).where(Job.id == job_id))
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        template_id = job.pipeline_template_id
    if template_id is None:
        template_id = await _default_template_id(db)

    if template_id is not None:
        rows = (
            (
                await db.execute(
                    select(PipelineStageDef)
                    .where(PipelineStageDef.template_id == template_id)
                    .order_by(PipelineStageDef.order)
                )
            )
            .scalars()
            .all()
        )
        result: list[StageInfo] = []
        for sd in rows:
            # Map new category enum → legacy StageCategory for BC
            legacy_enum = None
            if sd.legacy_enum_value:
                try:
                    legacy_enum = PipelineStage(sd.legacy_enum_value)
                except ValueError:
                    legacy_enum = None
            result.append(
                StageInfo(
                    stage=legacy_enum
                    or PipelineStage.new,  # fallback for custom stages
                    category=sd.category,
                    label=sd.name,
                    order=sd.order,
                    stage_def_id=sd.id,
                    is_terminal=sd.is_terminal,
                )
            )
        return result

    # Legacy fallback — pre-seed / no template world
    result = []
    for i, stage in enumerate(STAGE_ORDER):
        result.append(
            StageInfo(
                stage=stage,
                category=STAGE_CATEGORY[stage],
                label=STAGE_LABELS[stage],
                order=i,
                is_terminal=False,
            )
        )
    for stage in [PipelineStage.rejected, PipelineStage.withdrawn]:
        result.append(
            StageInfo(
                stage=stage,
                category=STAGE_CATEGORY[stage],
                label=STAGE_LABELS[stage],
                order=99,
                is_terminal=True,
            )
        )
    return result


async def _assert_cv_qc_gate(
    db: AsyncSession,
    user: User,
    *,
    candidate_id: int,
    job_id: int,
    stage_def: Optional[PipelineStageDef],
    legacy_value: Optional[str],
    client_id: Optional[int],
) -> None:
    """Rekrutacja v5 (0361): QC CV — twarda bramka przed „CV wysłane”/Cpro.

    Ruch pary z kolumn Nowi/Screening/Zweryfikowany/QC CV na „CV wysłane”
    albo na etap Cpro liczy QC CV firmowego; nieprzechodzące QC bez obejścia
    Delivery Leada/admina = 409 `CV_QC_FAILED`. Wołać PRZED zapisami ruchu —
    przy odmowie przebieg QC zostaje zapisany (okno QC pokaże ten sam wynik).
    """

    from app.core.config import settings
    from app.services import cv_qc

    if not settings.CV_QC_GATE_ENABLED:
        return
    if stage_def is not None and stage_def.is_terminal:
        return
    target_column = board_column_for(
        stage_def.name if stage_def else None,
        (stage_def.legacy_enum_value if stage_def else None) or legacy_value,
        category=(
            stage_def.category.value if stage_def and stage_def.category else None
        ),
        terminal_type=(
            stage_def.terminal_type.value
            if stage_def and stage_def.terminal_type
            else None
        ),
    )
    target_is_cpro = stage_def is not None and is_cpro_stage(stage_def.name)
    if target_column != "cv_sent" and not target_is_cpro:
        return
    current = await db.scalar(
        select(CandidateStage)
        .where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == job_id,
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        .limit(1)
    )
    if current is None:
        return
    current_column = await candidate_claim.stage_column(db, current)
    if not cv_qc.gate_applies(current_column, target_column, target_is_cpro):
        return
    # U Nordei „CV wysłane" = „Wysłane do Cpro": wrzuca osoba od Cpro
    # wyznaczona dla całej firmy (albo admin / DL / HoR). Rekruter po QC
    # przekazuje kartę do kolejki Cpro, nie wysyła jej sam.
    from app.services.board_stage_badges import cpro_enabled_for_client

    if target_column == "cv_sent" and cpro_enabled_for_client(client_id):
        from app.services import cpro_sender

        if not await cpro_sender.can_send_to_cpro(db, user):
            sender = await cpro_sender.effective_sender(db)
            names = await cpro_sender.user_names(db, {sender.user_id})
            who = names.get(sender.user_id) or "osoba wyznaczona do Cpro"
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Do Cpro wrzuca {who}. Po QC użyj „Przekaż do Cpro” — "
                    "osoba trafi do kolejki na pulpicie."
                ),
            )
    # Osoba już w kolejce Cpro przeszła bramkę przy wejściu do niej (albo —
    # sprzed 24.09.2026 — ręczny przegląd DZ). „✓ Wrzucone” nie liczy QC
    # drugi raz: CV Nordei to zwykle pliki Word spoza NEXUSA, a obejście ma
    # tylko DL/admin, więc osoba od Cpro dostawałaby odmowę na zaakceptowanych.
    if target_column == "cv_sent" and current.stage_def_id is not None:
        current_name = await db.scalar(
            select(PipelineStageDef.name).where(
                PipelineStageDef.id == current.stage_def_id
            )
        )
        if is_cpro_stage(current_name):
            return
    await cv_qc.assert_qc_passed(
        db, candidate_id=candidate_id, job_id=job_id, user=user, stage=current
    )


@router.post("/move", response_model=CandidateStageResponse)
async def move_candidate(
    data: StageMove,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    """Move a candidate to a new pipeline stage for a given job.

    Accepts either `stage` (legacy enum) or `stage_def_id` (new FK). For
    custom stages introduced via templates, the legacy enum is set to
    `PipelineStage.new` as a placeholder — the real identifier is stage_def_id.
    """
    if data.stage is None and data.stage_def_id is None:
        raise HTTPException(
            status_code=422,
            detail="Either `stage` (legacy enum) or `stage_def_id` must be provided",
        )

    job = await db.scalar(select(Job).where(Job.id == data.job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # ── P1-PIPE-01: resource scope ── a caller may only touch the pipeline of
    # a job they belong to (owner/DL/TAC/collaborator) or oversee (admin/HoR).
    # Runs before any target/capability work so a non-member learns nothing
    # about the requested move.
    await ensure_job_membership(db, current_user, job.id)

    stage_def = await _resolve_stage_def(
        db, job, stage_def_id=data.stage_def_id, legacy_stage=data.stage
    )

    # ── M4 PR-02: integrity walidacja TARGETU ruchu (audyt P1.1) ───────────
    # Walidujemy WYŁĄCZNIE target — baseline PR-00 pokazał 79k istniejących
    # latest rows ze stage_def spoza template'u joba (import Traffit); ruch
    # Z takiego stanu musi pozostać legalny, ruch NA obcy etap — nie.
    if data.stage_def_id and stage_def is None:
        raise HTTPException(
            status_code=422,
            detail=f"stage_def_id={data.stage_def_id} nie istnieje",
        )
    effective_template_id = job.pipeline_template_id or await _default_template_id(db)
    if (
        stage_def is not None
        and effective_template_id is not None
        and stage_def.template_id != effective_template_id
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Etap '{stage_def.name}' należy do innego template'u niż "
                "template tej rekrutacji."
            ),
        )
    if (
        data.stage is not None
        and stage_def is not None
        and stage_def.legacy_enum_value
        and stage_def.legacy_enum_value != data.stage.value
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Sprzeczne `stage`={data.stage.value} i `stage_def_id` "
                f"(etap '{stage_def.name}' mapuje się na "
                f"'{stage_def.legacy_enum_value}')."
            ),
        )

    # Etapy-odznaki Tablicy (22.09.2026): „DZ ✓" ustawia DL / Head of
    # Recruitment, „Gotowy do Cpro" istnieje tylko u Nordei.
    if stage_def is not None:
        ensure_badge_stage_allowed(
            current_user, stage_name=stage_def.name, client_id=job.client_id
        )
    # Rekrutacja v5 (0361): QC CV przed „CV wysłane”/Cpro. Tu, przed
    # pierwszym zapisem ruchu — odmowa zapisuje przebieg QC i nic więcej.
    await _assert_cv_qc_gate(
        db,
        current_user,
        candidate_id=data.candidate_id,
        job_id=job.id,
        stage_def=stage_def,
        legacy_value=data.stage.value if data.stage is not None else None,
        client_id=job.client_id,
    )
    # 0348/0353: osoba, która wysyła do Cpro — od 23.09.2026 JEDNA na całą
    # rekrutację (`jobs.cpro_sender_id`); pole przy ruchu ustawia ją dla
    # rekrutacji. Na każdym innym etapie pole nie ma znaczenia, więc 422.
    cpro_assignee: Optional[User] = None
    cpro_assignee_added_to_team = False
    if data.task_assignee_id is not None:
        if stage_def is None or not is_cpro_stage(stage_def.name):
            raise HTTPException(
                status_code=422,
                detail=(
                    "Osobę wysyłającą wybiera się tylko przy oznaczeniu "
                    "„Gotowy do Cpro”."
                ),
            )
        cpro_assignee = await board_tasks_svc.load_assignee(db, data.task_assignee_id)
        # Przed ruchem: odmowa (osoba spoza zespołu, a typuje ktoś bez prawa
        # zmiany zespołu) ma zatrzymać ruch, zanim cokolwiek się zapisze.
        cpro_assignee_added_to_team = await board_tasks_svc.ensure_assignee_can_move(
            db, job_id=job.id, assignee=cpro_assignee, actor=current_user
        )

    # Use the same first lock as the signed-contract automation. Besides
    # serializing two pipeline moves, this prevents the inverse
    # CandidateStage-FK → Candidate-FOR-UPDATE lock order that could deadlock
    # with a concurrent signature confirmation.
    locked_candidate_id = await db.scalar(
        select(Candidate.id).where(Candidate.id == data.candidate_id).with_for_update()
    )
    if locked_candidate_id is None:
        raise HTTPException(status_code=404, detail="Candidate not found")

    # Pipeline v4 (0352): osoba w „Nowych" zarezerwowana przez kogoś innego
    # (12 h) — ruch tylko dla admina, DL i Head of Recruitment.
    await candidate_claim.assert_can_act(
        db,
        process=await candidate_claim.load_process(
            db, candidate_id=data.candidate_id, job_id=data.job_id
        ),
        user=current_user,
    )

    # Current row pary — kanoniczny tiebreaker (moved_at DESC, id DESC).
    # Reużywany niżej: cancel maili przy restore, notyfikacje. Wiersz
    # historyczny `pending` NIE blokuje kolejnego ruchu — bramka „Oczekuje"
    # została usunięta i nie ma approvera, który mógłby ją odblokować.
    previous_stage_row = await db.scalar(
        select(CandidateStage)
        .where(
            CandidateStage.candidate_id == data.candidate_id,
            CandidateStage.job_id == data.job_id,
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        .limit(1)
    )

    # Derive effective legacy-enum value for backward-compat column
    legacy_enum: PipelineStage = data.stage or PipelineStage.new
    if stage_def and stage_def.legacy_enum_value:
        try:
            legacy_enum = PipelineStage(stage_def.legacy_enum_value)
        except ValueError:
            legacy_enum = data.stage or PipelineStage.new
    elif stage_def and stage_def.is_terminal and legacy_enum == PipelineStage.new:
        # M4-P0.2: a CUSTOM terminal stage carries no legacy_enum_value (the
        # StageDef schema has no such field and clone_template doesn't copy it),
        # so it would fall through as `new` — a custom "Zatrudniony" would never
        # trigger the auto-draft Contract (line ~700 keys on `hired`) and a
        # custom "Odrzucony" would never fire the rejection mail. Derive the
        # hire/reject/withdraw signal from terminal_type so those side effects
        # fire. list_stages also can't return `hired` for custom stages, so the
        # FE can't supply it either — this is the only place it can be inferred.
        _terminal_to_legacy = {
            TerminalType.hired: PipelineStage.hired,
            TerminalType.rejected: PipelineStage.rejected,
            TerminalType.withdrawn: PipelineStage.withdrawn,
        }
        mapped = _terminal_to_legacy.get(stage_def.terminal_type)
        if mapped is not None:
            legacy_enum = mapped

    # ── M4 PR-01: capability guard na ruchy terminalne i rate-bearing ──────
    # Terminal (po stage_def LUB legacy enum): sourcer nie zamyka rekrutacji
    # (audyt P0.3 — RecruiterPlus obejmuje sourcera, a terminal nie miał
    # osobnego guardu). Ruch na `verified` niesie stawkę kandydata
    # (expected_rate_*), więc wymaga capability edycji stawek.
    is_terminal_target = bool(stage_def and stage_def.is_terminal) or legacy_enum in (
        PipelineStage.hired,
        PipelineStage.rejected,
        PipelineStage.withdrawn,
    )
    if is_terminal_target and not user_can_terminal_transition(current_user):
        raise HTTPException(
            status_code=403,
            detail=(
                "Ruch na etap terminalny (hired/rejected/withdrawn) wymaga roli "
                "admin, delivery_lead, talent_community_manager, tac, recruiter "
                "lub finance."
            ),
        )
    # A concurrent confirm or pipeline move may have completed while this
    # request waited for the candidate lock. Treat an identical hired move as
    # an idempotent replay instead of appending a second terminal stage.
    if (
        legacy_enum == PipelineStage.hired
        and previous_stage_row is not None
        and previous_stage_row.stage == PipelineStage.hired
    ):
        resp = _stage_response(
            previous_stage_row,
            show_client_rate=user_can_view_client_rate(current_user),
        )
        resp["scheduled_rejection_email_id"] = None
        await db.commit()
        return CandidateStageResponse(**resp)

    if legacy_enum == PipelineStage.verified and not user_can_edit_rates(current_user):
        raise HTTPException(
            status_code=403,
            detail=(
                "Ruch na etap 'Zweryfikowany' może nieść stawkę kandydata i wymaga "
                "roli admin, delivery_lead, tac, recruiter lub finance."
            ),
        )

    # Pipeline v4 (23.09.2026): wejście do „Umowy"/„Zatrudnionego" wymaga
    # debriefu po rozmowie u klienta (pytania klienta albo „klient nie zadawał
    # pytań") — pytania zasilają prep i profil Championa.
    target_column = board_column_for(
        stage_def.name if stage_def else None,
        legacy_enum.value,
        category=(
            stage_def.category.value if stage_def and stage_def.category else None
        ),
        terminal_type=(
            stage_def.terminal_type.value
            if stage_def and stage_def.terminal_type
            else None
        ),
    )
    await pipeline_move_rules.assert_debrief_before_contract(
        db,
        candidate_id=data.candidate_id,
        job_id=data.job_id,
        target_column=target_column,
    )

    # Pipeline v4 (23.09.2026): „CV wysłane" poza Nordeą wysyła Delivery Lead
    # i wpisuje stawkę do klienta. Stawka zapisana wcześniej w tej rekrutacji
    # (powrót na etap) wystarcza — nie trzeba jej przepisywać.
    client_rate_value = data.client_rate_value
    client_rate_unit = data.client_rate_unit
    client_rate_currency = (data.client_rate_currency or "PLN")[:3].upper()
    if pipeline_move_rules.requires_dl_client_rate(legacy_enum, job.client_id):
        known_rate = client_rate_value
        if known_rate is None:
            known_rate = await db.scalar(
                select(CandidateStage.client_rate_value)
                .where(
                    CandidateStage.candidate_id == data.candidate_id,
                    CandidateStage.job_id == data.job_id,
                    CandidateStage.client_rate_value.isnot(None),
                )
                .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
                .limit(1)
            )
        pipeline_move_rules.assert_client_send_allowed(current_user, known_rate)
    elif client_rate_value is not None and not await resolve_client_rate_write(
        db, current_user, job
    ):
        # Stawka do klienta w ruchu = ta sama bramka co `PATCH …/client-rate`.
        raise HTTPException(
            status_code=403,
            detail=("Stawkę do klienta zapisuje Delivery Lead albo admin."),
        )

    # ── P1-PIPE-01: eligibility gate ── same hard block the assign ingresses
    # enforce (global blacklist / hiring-manager veto) → 409 with the Polish
    # reason. Client conflicts (blacklist / NDA / competitor) are warnings
    # since 17.09.2026 and never block a move. Skipped for terminal REMOVAL
    # moves so a blacklisted/vetoed candidate can always be closed OUT
    # (rejected / withdrawn); a forward or `hired` move of such a candidate
    # is blocked.
    is_removal_move = legacy_enum in (
        PipelineStage.rejected,
        PipelineStage.withdrawn,
    ) or bool(
        stage_def
        and stage_def.is_terminal
        and stage_def.terminal_type
        and stage_def.terminal_type.value in ("rejected", "withdrawn")
    )
    # 17.09.2026 (decyzja „żadna bramka nie blokuje przepływu"): ten sam
    # powód jest OSTRZEŻENIEM — bez `acknowledge_eligibility` 409
    # `ELIGIBILITY_WARNING`, z flagą ruch przechodzi i zostaje `Activity`.
    eligibility_block = None
    if not is_removal_move:
        eligibility_block = await check_candidate_move_eligibility(
            db,
            candidate_id=data.candidate_id,
            job=job,
            now=datetime.now(timezone.utc),
            enforce_manager_verdict=puts_candidate_before_client(legacy_enum),
            acknowledged=data.acknowledge_eligibility,
        )

    # Terminal-move validation: require rejection_reason_id
    is_terminal_move_stagedef = bool(
        stage_def
        and stage_def.is_terminal
        and stage_def.terminal_type
        and stage_def.terminal_type.value in ("rejected", "withdrawn")
    )
    # Phase 17 (migracja 0068): legacy enum path — pilnujemy WYŁĄCZNIE
    # `withdrawn`, bo to ma CHECK constraint na DB. Reszta legacy paths
    # zachowuje wcześniejsze zachowanie (BC-friendly).
    is_terminal_move_legacy_withdrawn = legacy_enum == PipelineStage.withdrawn
    # M4 PR-02: withdrawn (stagedef LUB legacy) ZAWSZE wymaga powodu ze
    # słownika — DB CHECK ck_candidate_stages_withdrawn_requires_reason i tak
    # odrzuci NULL, więc free-text dawał 500 zamiast czytelnego 422.
    is_withdrawn_target = is_terminal_move_legacy_withdrawn or bool(
        stage_def
        and stage_def.is_terminal
        and stage_def.terminal_type
        and stage_def.terminal_type.value == "withdrawn"
    )
    ended_by: Optional[str] = None
    if is_removal_move:
        ended_by = pipeline_move_rules.resolve_ended_by(
            data.ended_by, withdrawn=is_withdrawn_target, user=current_user
        )
    elif data.ended_by is not None:
        raise HTTPException(
            status_code=422,
            detail="„Kto zakończył” podaje się tylko przy zamknięciu procesu.",
        )
    if is_withdrawn_target and not data.rejection_reason_id:
        raise HTTPException(
            status_code=422,
            detail=(
                "Etap 'withdrawn' wymaga powodu ze słownika "
                "(rejection_reason_id) — sam opis tekstowy nie wystarcza."
            ),
        )
    if is_terminal_move_stagedef or is_terminal_move_legacy_withdrawn:
        if not data.rejection_reason_id and not data.rejection_reason:
            terminal_label = (
                stage_def.terminal_type.value
                if is_terminal_move_stagedef
                else legacy_enum.value
            )
            raise HTTPException(
                status_code=422,
                detail=f"Terminal stage ({terminal_label}) requires rejection_reason_id",
            )
    # M4 PR-02 (audyt P1.1): walidacja powodu ZAWSZE gdy podany — dotąd
    # legacy `rejected` zapisywał dowolny FK bez sprawdzenia template'u,
    # kategorii i stage-bindingu.
    if data.rejection_reason_id:
        reason = await db.scalar(
            select(RejectionReason).where(
                RejectionReason.id == data.rejection_reason_id
            )
        )
        if not reason or not reason.active:
            raise HTTPException(
                status_code=422,
                detail="rejection_reason_id not found or inactive",
            )
        if not (
            is_terminal_move_stagedef
            or legacy_enum
            in (
                PipelineStage.rejected,
                PipelineStage.withdrawn,
            )
        ):
            raise HTTPException(
                status_code=422,
                detail="rejection_reason_id dozwolony tylko dla ruchu terminalnego",
            )
        if (
            effective_template_id is not None
            and reason.template_id != effective_template_id
        ):
            raise HTTPException(
                status_code=422,
                detail="Powód odrzucenia należy do innego template'u niż rekrutacja.",
            )
        expected_category = (
            stage_def.terminal_type.value
            if is_terminal_move_stagedef
            else legacy_enum.value
        )
        if reason.category.value != expected_category:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Powód ma kategorię '{reason.category.value}', "
                    f"a ruch jest '{expected_category}'."
                ),
            )
        if (
            reason.stage_def_id is not None
            and stage_def is not None
            and reason.stage_def_id != stage_def.id
        ):
            raise HTTPException(
                status_code=422,
                detail="Powód jest przypisany do innego etapu.",
            )

    # ── Stawka przy ruchu na `verified` (0056; bramka zdjęta 17.09.2026) ──
    # Stawka jest OPCJONALNA i NIGDY nie ustawia `pending` (decyzja właściciela:
    # żadna bramka nie zatrzymuje przepływu; „ponad budżet" to odznaka na
    # karcie). Snapshot budżetu miesięcznego zostaje dla audytu i doku karty.
    verification_status = VerificationStatus.active
    expected_rate_value = data.expected_rate_value
    expected_rate_unit = data.expected_rate_unit
    expected_rate_currency = data.expected_rate_currency or "PLN"
    budget_max_snapshot: Optional[int] = None
    budget_exceeded = False
    normalization_note: Optional[str] = None

    if legacy_enum == PipelineStage.verified:
        # Stawka jest OPCJONALNA (17.09.2026) — brak stawki to 200, nie 422.
        if job.salary_max is not None:
            budget_max_snapshot = int(job.salary_max)
        if job.salary_max is not None and expected_rate_value is not None:
            # M4 PR-02 (audyt P0.5): porównanie w JEDNEJ jednostce. Dotąd
            # surowe 150 (PLN/h) < 25000 (PLN/mc) przechodziło jako "w
            # budżecie". Normalizacja: hourly×168, daily×21; waluta ≠ PLN
            # lub nieznana jednostka → fail-closed do manual review.
            normalized_monthly, normalization_note = normalize_rate_to_monthly(
                Decimal(expected_rate_value),
                expected_rate_unit.value if expected_rate_unit else None,
                expected_rate_currency,
            )
            if normalized_monthly is None or normalized_monthly > Decimal(
                job.salary_max
            ):
                # Decyzja 17.09.2026: żadna bramka nie zatrzymuje ruchu —
                # stawka zostaje zapisana, a przekroczenie budżetu jedzie na
                # kartę wyłącznie jako informacja (`budget_exceeded`). Stawka
                # nieporównywalna (inna waluta, nieznana jednostka) NIE jest
                # „ponad budżetem" — to brak porównania, nie jego wynik.
                budget_exceeded = normalized_monthly is not None

    # M4 PR-02 (audyt P1.1): free-text reason był przyjmowany, "zaliczał"
    # walidację terminalną i znikał (nie ma kolumny). Utrwalamy go w notes,
    # żeby audyt widział podany powód.
    effective_notes = data.notes
    if data.rejection_reason and not data.rejection_reason_id:
        prefix = f"Powód ({legacy_enum.value}): {data.rejection_reason.strip()}"
        effective_notes = f"{prefix}\n{data.notes}" if data.notes else prefix

    stage = await transition_process(
        db,
        candidate_id=data.candidate_id,
        job_id=data.job_id,
        stage=legacy_enum,
        stage_def_id=stage_def.id if stage_def else None,
        rejection_reason_id=data.rejection_reason_id,
        moved_at=datetime.now(timezone.utc),
        actor_user_id=current_user.id,
        work_channel=PriorityChannel.database,
        notes=effective_notes,
        rating=data.rating,
        verification_status=verification_status,
        expected_rate_value=expected_rate_value,
        expected_rate_unit=(expected_rate_unit.value if expected_rate_unit else None),
        expected_rate_currency=(
            expected_rate_currency if expected_rate_value is not None else None
        ),
        budget_max_at_move=budget_max_snapshot,
        # Phase 17 (migracja 0068) — kandydata reakcja na ofertę po akcepcie.
        candidate_offer_response=data.candidate_offer_response,
        # F05: wersja procesu widziana przez klienta — rozjazd = 409.
        expected_state_version=data.expected_state_version,
        ended_by=ended_by,
        client_rate_value=client_rate_value,
        client_rate_unit=(
            (client_rate_unit or RateUnit.hourly).value
            if client_rate_value is not None
            else None
        ),
        client_rate_currency=(
            client_rate_currency if client_rate_value is not None else None
        ),
    )
    if client_rate_value is not None:
        candidate_audit.record_candidate_audit(
            db,
            action=candidate_audit.CLIENT_RATE_CHANGED,
            user_id=current_user.id,
            entity_id=data.candidate_id,
            details={
                "job_id": data.job_id,
                "stage_id": stage.id,
                "new_client_rate": float(client_rate_value),
                "new_client_rate_unit": stage.client_rate_unit,
                "new_client_rate_currency": stage.client_rate_currency,
                "source": "pipeline_move",
            },
        )
    await create_original_cv_snapshot(db, stage)
    if cpro_assignee is not None:
        stage.task_assignee_id = cpro_assignee.id
        job.cpro_sender_id = cpro_assignee.id
    if is_terminal_target:
        await maybe_close_contact_opportunity(
            db,
            candidate_id=data.candidate_id,
            job_id=data.job_id,
            actor_user_id=current_user.id,
            reason=f"pipeline_terminal:{legacy_enum.value}",
            occurred_at=stage.moved_at,
        )
    else:
        await maybe_ensure_contact_opportunity(
            db,
            candidate_id=data.candidate_id,
            job_id=data.job_id,
            source="pipeline",
            occurred_at=stage.moved_at,
        )

    stage_display_name = (
        stage_def.name
        if stage_def
        else STAGE_LABELS.get(legacy_enum, legacy_enum.value)
    )

    # Activity log
    activity_details: dict = {
        "candidate_id": data.candidate_id,
        "job_id": data.job_id,
        "stage": legacy_enum.value,
        "stage_def_id": stage_def.id if stage_def else None,
        "stage_name": stage_display_name,
    }
    if legacy_enum == PipelineStage.verified and budget_max_snapshot is not None:
        # M4 PR-02: audyt decyzji gate'u — z jakiej normalizacji wynikła.
        activity_details["rate_gate"] = {
            "policy": RATE_POLICY_VERSION,
            "note": normalization_note,
            "budget_exceeded": budget_exceeded,
            "budget_max": budget_max_snapshot,
        }
    db.add(
        Activity(
            entity_type="pipeline",
            entity_id=stage.id,
            action="stage_changed",
            user_id=current_user.id,
            details=activity_details,
        )
    )
    if eligibility_block is not None:
        # Przeniesiono mimo ostrzeżenia — audyt widzi, co zignorowano i kto.
        db.add(
            Activity(
                entity_type="pipeline",
                entity_id=stage.id,
                action="eligibility_acknowledged",
                user_id=current_user.id,
                details={
                    "candidate_id": data.candidate_id,
                    "job_id": data.job_id,
                    "stage": legacy_enum.value,
                    "reason_code": eligibility_block.reason_code,
                    "reason": eligibility_block.reason,
                },
            )
        )

    # M4 PR-02 (audyt P1.7): restore/ruch na etap NIEterminalny anuluje
    # niewysłane maile odrzucenia tej pary — w TEJ SAMEJ transakcji co move.
    # Dotąd przywrócony kandydat mógł dostać zaplanowane wcześniej odrzucenie.
    if not is_terminal_target:
        from app.models.rejection_email import (
            RejectionEmailStatus,
            ScheduledRejectionEmail,
        )

        pending_mails = (
            (
                await db.execute(
                    select(ScheduledRejectionEmail).where(
                        ScheduledRejectionEmail.candidate_id == data.candidate_id,
                        ScheduledRejectionEmail.job_id == data.job_id,
                        ScheduledRejectionEmail.status == RejectionEmailStatus.pending,
                    )
                )
            )
            .scalars()
            .all()
        )
        for mail_row in pending_mails:
            mail_row.status = RejectionEmailStatus.cancelled
            mail_row.cancelled_at = datetime.now(timezone.utc)
            mail_row.cancelled_by = current_user.id
            db.add(
                Activity(
                    entity_type="candidate",
                    entity_id=data.candidate_id,
                    action="rejection_email_cancelled_on_restore",
                    user_id=current_user.id,
                    details={
                        "scheduled_rejection_email_id": mail_row.id,
                        "job_id": data.job_id,
                        "restored_to_stage": legacy_enum.value,
                    },
                )
            )

    # UserActivity for leaderboard/performance tracking
    db.add(
        UserActivity(
            user_id=current_user.id,
            action_type=UserActionType.stage_changed,
            entity_type="pipeline",
            entity_id=stage.id,
            details={
                "candidate_id": data.candidate_id,
                "job_id": data.job_id,
                "stage": legacy_enum.value,
                "stage_def_id": stage_def.id if stage_def else None,
            },
        )
    )

    # M4 PR-02 (audyt P0.6): notify_stage_change (in-app + SMTP) oraz
    # talent-pool auto-add przeniesione ZA commit — patrz sekcja post-commit
    # niżej. Dotąd SMTP mógł wyjść przed commitem: mail o przejściu, którego
    # DB ostatecznie nie zatwierdziła.

    # Phase 9 A2 + DL portal refactor 2026-05-11 + „bez bramek" 17.09.2026:
    # szkic kontraktu + zamówienia przy zatrudnieniu (Delivery uzupełnia
    # stawki, daty, PDF). Od 17.09.2026 szkic NIE blokuje zatrudnienia: serwis
    # odmawia 409 na danych historycznych (dwa żywe kontrakty, kontrakt innego
    # klienta, zamknięty status…), co do tej pory cofało CAŁY ruch. Wiersz
    # etapu z `transition_process` jest zflushowany PRZED savepointem, więc
    # rollback savepointu zdejmuje tylko to, co zdążył zapisać serwis.
    if legacy_enum == PipelineStage.hired and job.client_id is not None:
        employment = None
        draft_skip_reason: Optional[str] = None
        await db.flush()
        try:
            async with db.begin_nested():
                employment = await ensure_b2b_employment_draft(
                    db,
                    candidate_id=data.candidate_id,
                    job=job,
                    actor_id=current_user.id,
                    default_start_date=business_today(),
                    ensure_order=True,
                    # The stage was inserted and flushed just above. The
                    # idempotent guard sees it as latest and never appends a
                    # duplicate.
                    ensure_hired=True,
                    require_b2b=False,
                    ensure_detail=False,
                )
        except HTTPException as exc:
            # 409/404 serwisu — zatrudnienie zostaje, szkic zakłada Delivery.
            draft_skip_reason = _http_detail_text(exc.detail)
            logger.warning(
                "hired move: contract draft skipped candidate=%s job=%s: %s",
                data.candidate_id,
                job.id,
                draft_skip_reason,
            )

        if draft_skip_reason is not None or (
            employment is not None
            and (employment.created_contract or employment.created_order)
        ):
            cand = await db.scalar(
                select(Candidate).where(Candidate.id == data.candidate_id)
            )
            cand_name = (
                f"{cand.name} {cand.lastname}".strip()
                if cand
                else f"#{data.candidate_id}"
            )
            delivery_recipients = await load_delivery_alert_recipient_scope(db)

        if employment is not None and (
            employment.created_contract or employment.created_order
        ):
            db.add(
                Activity(
                    entity_type="contract",
                    entity_id=employment.contract.id,
                    action=(
                        "auto_drafted_from_pipeline"
                        if employment.created_contract
                        else "order_auto_drafted_from_pipeline"
                    ),
                    user_id=current_user.id,
                    details={
                        "candidate_id": data.candidate_id,
                        "job_id": job.id,
                        "stage": legacy_enum.value,
                        "order_id": (employment.order.id if employment.order else None),
                    },
                )
            )
            for uid in delivery_recipients.for_client(job.client_id):
                db.add(
                    Notification(
                        user_id=uid,
                        title=(
                            "Nowy draft kontraktu + zamówienia "
                            f"#{employment.contract.id}"
                        ),
                        message=(
                            f"Kandydat {cand_name} został zatrudniony na "
                            f"rekrutację '{job.title}' (#{job.id}). Uzupełnij stawki, "
                            "daty i wgraj PDF zamówienia."
                        ),
                        link=f"/clients/{job.client_id}?tab=zamowienia",
                        notification_type=NotificationType.contract_activated,
                        related_entity_type="contract",
                        related_entity_id=employment.contract.id,
                    )
                )

        if draft_skip_reason is not None:
            from app.services.notification_triggers import emit

            db.add(
                Activity(
                    entity_type="pipeline",
                    entity_id=stage.id,
                    action="contract_draft_skipped",
                    user_id=current_user.id,
                    details={
                        "candidate_id": data.candidate_id,
                        "job_id": job.id,
                        "client_id": job.client_id,
                        "reason": draft_skip_reason,
                    },
                )
            )
            # Ci sami odbiorcy co przy udanym szkicu. `emit` = savepoint + dedup
            # dzienny, więc duplikat nie wywróci commitu zatrudnienia.
            for uid in delivery_recipients.for_client(job.client_id):
                await emit(
                    db,
                    user_id=uid,
                    title="Nie założono szkicu kontraktu",
                    message=(
                        f"Kandydat {cand_name} został zatrudniony na rekrutację "
                        f"'{job.title}' (#{job.id}), ale szkic kontraktu nie "
                        f"powstał: {draft_skip_reason} Załóż kontrakt ręcznie "
                        "w profilu klienta."
                    ),
                    ntype=NotificationType.suggest_next_step,
                    related_entity_type="candidate",
                    related_entity_id=data.candidate_id,
                    link=f"/clients/{job.client_id}?tab=zamowienia",
                )

    # Obsada kompletna → PODPOWIEDŹ zamknięcia rekrutacji, nie automat.
    #
    # Zatrudnienie nie zmieniało dotąd stanu rekrutacji: `headcount` nie był
    # dekrementowany, a `close_reason = filled_by_us` nie był ustawiany nigdzie
    # w kodzie pipeline'u — stąd 315 rekrutacji zamkniętych w 90 dni BEZ powodu
    # i raport wygranych/przegranych bez czego liczyć wygranej.
    #
    # Automatu tu nie ma świadomie (decyzja właściciela 2026-09-03): 99,6% ruchu
    # pochodzi z importu, więc automatyczne domykanie działałoby retroaktywnie
    # na tysiącach rekrutacji, o które nikt nie prosił. Powiadomienie prowadzi
    # do ISTNIEJĄCEGO `POST /api/jobs/{job_id}/close`, który zapisuje powód
    # i loguje `Activity`.
    if legacy_enum == PipelineStage.hired:
        try:
            from app.services.job_fill import is_fully_staffed, placements_by_job

            # Skrót: właśnie kogoś zatrudniliśmy, więc obsada >= 1. Przy
            # `headcount = 1` (default) wiemy to bez pytania widoku
            # `analytics_first_milestones` — a to gorąca ścieżka `/move`.
            headcount = int(job.headcount or 1)
            filled = (
                1
                if headcount <= 1
                else (await placements_by_job(db, [job.id])).get(job.id, 0)
            )
            already_hinted = await db.scalar(
                select(Notification.id)
                .where(
                    Notification.related_entity_type == "job",
                    Notification.related_entity_id == job.id,
                    Notification.notification_type
                    == NotificationType.suggest_next_step,
                )
                .limit(1)
            )
            if (
                is_fully_staffed(headcount, filled)
                and job.status != JobStatus.closed
                # Bez dedupu KAŻDE kolejne zatrudnienie na tej rekrutacji
                # rozsyłałoby ten sam komunikat do wszystkich admin/DL/TAC.
                # Podpowiedź ma być jedna — jeśli ktoś ją zignorował, powtórka
                # niczego nie doda, a nauczy ignorować powiadomienia.
                and already_hinted is None
            ):
                # Odbiorcy = zespół TEJ rekrutacji (właściciel, DL, TAC,
                # współpracownicy) + admini z `list_job_member_ids`, nie każdy
                # DL/TAC w firmie — podpowiedź o cudzej rekrutacji uczyła
                # ignorować powiadomienia.
                from app.services.job_membership import list_job_member_ids

                recipient_ids = await list_job_member_ids(db, job.id)
                from app.services.notification_triggers import emit

                title = f"Rekrutacja '{job.title}' ma komplet obsady"
                message = (
                    f"Obsadzono {filled} z {job.headcount or 1} "
                    "etatów. Jeśli to koniec — zamknij rekrutację "
                    "z powodem „Obsadzone przez nas”, żeby raport "
                    "wygranych i przegranych miał z czego liczyć."
                )
                job_id = job.id
                # `emit` zapisuje w savepoincie. `ix_notif_dedup_daily` nie zna
                # typu encji, więc powiadomienie o KANDYDACIE #N z tego dnia
                # blokowało podpowiedź dla REKRUTACJI #N — a `db.add` bez flush
                # wywracał dopiero commit zatrudnienia (500 na /move).
                for uid in recipient_ids:
                    await emit(
                        db,
                        user_id=uid,
                        title=title,
                        message=message,
                        ntype=NotificationType.suggest_next_step,
                        related_entity_type="job",
                        related_entity_id=job_id,
                        link=f"/jobs/{job_id}",
                    )
        except Exception as _exc:  # noqa: BLE001
            # Podpowiedź nie może wywrócić zatrudnienia.
            logger.warning("fully-staffed hint failed for job=%s: %s", job.id, _exc)

    # Mail odrzucenia (0045_rejection_emails) jest OPT-IN od 17.09.2026:
    # planujemy WYŁĄCZNIE gdy klient przysłał `send_rejection_email=True`
    # (checkbox w oknie odrzucenia, domyślnie odznaczony). `maybe_schedule`
    # nadal sam sprawdza kwalifikowalność (etap klienta, e-mail kandydata).
    scheduled_rejection_email_id: Optional[int] = None
    if legacy_enum == PipelineStage.rejected and data.send_rejection_email is True:
        from app.services.rejection_email_scheduler import maybe_schedule

        scheduled = await maybe_schedule(
            db,
            stage=stage,
            job=job,
            recruiter_id=job.recruiter_id,
            template_override_id=data.rejection_email_template_id,
        )
        if scheduled is not None:
            scheduled_rejection_email_id = scheduled.id

    # 0341: osoba weszła do klienta → przepnij ją do połączonych (podobnych)
    # rekrutacji jako propozycję „przepięcie". Nigdy nie rzuca.
    if legacy_enum is not None:
        from app.services.job_similarity import on_candidate_sent  # noqa: PLC0415

        await on_candidate_sent(
            db, job_id=data.job_id, candidate_id=stage.candidate_id, stage=legacy_enum
        )
        # 0371: klient zaprosił na rozmowę / zaakceptował → „Klient milczy”
        # wraca do „Szukamy kandydatów”. Nigdy nie rzuca.
        from app.services.request_work_state import (  # noqa: PLC0415
            wake_on_client_response,
        )

        await wake_on_client_response(
            db, job_id=data.job_id, stage=legacy_enum, reason="client_stage"
        )

    actor_id = current_user.id
    await db.commit()
    await db.refresh(stage)
    # Live kanban: the rest of the team re-reads the board (best-effort).
    await broadcast_pipeline_changed(db, data.job_id, actor_id)

    # ── Post-commit best-effort side effects (M4 PR-02, audyt P0.6) ────────
    # Transition jest już trwały. Nic poniżej nie może zwrócić 500 ani
    # cofnąć ruchu — każdy blok ma własny try/except + rollback, żeby błąd
    # SQL nie zostawił sesji w failed transaction (PendingRollbackError
    # → fałszywe 500 po zapisanym ruchu; scenariusz B audytu).

    # Configurable stage-transition notifications (migracja 0066) —
    # in-app + email (SMTP) per regułą; teraz wyłącznie PO commicie.
    try:
        from app.services.stage_notification_emitter import notify_stage_change

        candidate_obj = await db.scalar(
            select(Candidate).where(Candidate.id == data.candidate_id)
        )
        if candidate_obj is not None:
            await notify_stage_change(
                db,
                new_stage=stage,
                previous_stage=previous_stage_row,
                job=job,
                candidate=candidate_obj,
                mover=current_user,
                stage_display_name=stage_display_name,
            )
        await db.commit()
    except Exception as _exc:  # noqa: BLE001
        logger.warning("stage_notif top-level failure for stage=%s: %s", stage.id, _exc)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass

    # 0348/0353: dzwonek dla osoby, która wysyła do Cpro. Best-effort.
    if cpro_assignee is not None:
        try:
            await board_tasks_svc.notify_cpro_sender(
                db,
                job_id=job.id,
                job_title=job.title,
                waiting=0,
                sender_id=cpro_assignee.id,
                actor=current_user,
            )
            await db.commit()
        except Exception as _exc:  # noqa: BLE001
            logger.warning(
                "cpro assignment notice failed stage=%s: %s (added_to_team=%s)",
                stage.id,
                _exc,
                cpro_assignee_added_to_team,
            )
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001
                pass

    # Phase 10 A1: auto-add candidate to a talent pool when CV is sent to
    # the client. Best-effort — po commicie ruchu.
    if legacy_enum == PipelineStage.cv_sent:
        from app.services.talent_pool_auto_add import auto_add_on_cv_sent

        try:
            pool_candidate = await db.scalar(
                select(Candidate).where(Candidate.id == data.candidate_id)
            )
            await auto_add_on_cv_sent(
                db=db,
                candidate_id=data.candidate_id,
                job=job,
                user_id=current_user.id,
                candidate=pool_candidate,
            )
            await db.commit()
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "auto_add_on_cv_sent failed for candidate=%s job=%s: %s",
                data.candidate_id,
                job.id,
                e,
            )
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001
                pass

    # Phase 17 (migracja 0068): event-driven recompute risk profile.
    # Best-effort — błąd NIE może wywołać 500 po zapisanym transition.
    try:
        from app.services.candidate_risk import on_candidate_stage_change

        await on_candidate_stage_change(db, data.candidate_id)
        await db.commit()
    except Exception as _exc:  # noqa: BLE001
        logger.warning(
            "risk recompute failed post-move candidate=%s: %s",
            data.candidate_id,
            _exc,
        )
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass

    # Auto-CV (21.09.2026): po trwałym ruchu na „Zweryfikowany" system w tle
    # zakolejkowuje CV w szablonie firmowym. Własna sesja, fire-and-forget —
    # nie wpływa na status ani czas tej odpowiedzi; reguły klienta (zrzut zgody
    # RODO itd.) NIE są omijane. Tylko ten endpoint: `/bulk-move` nie przyjmuje
    # etapu `verified`, importy nie przechodzą tędy.
    if legacy_enum == PipelineStage.verified:
        try:
            from app.services import cv_auto_generate

            if cv_auto_generate.enabled():
                _spawn(
                    cv_auto_generate.generate_after_verified(
                        stage_id=stage.id, user_id=actor_id
                    ),
                    f"cv_auto_generate stage={stage.id}",
                )
        except Exception as _exc:  # noqa: BLE001 — automat nigdy nie psuje ruchu
            logger.warning("cv_auto_generate spawn failed stage=%s: %s", stage.id, _exc)

    # QC CV (Rekrutacja v5): po wejściu do kolumny „QC CV” QC liczy się samo,
    # żeby karta, przegląd DL i kolejka Cpro nie mówiły „nie sprawdzone”.
    # Ten sam wyłącznik co bramka (w testach wyłączony autouse-fixturą).
    if target_column == "cv_qc":
        try:
            from app.core.config import settings as _settings
            from app.services import cv_qc as _cv_qc

            if _settings.CV_QC_GATE_ENABLED:
                _spawn(
                    _cv_qc.run_after_move(stage.id, actor_id),
                    f"cv_qc stage={stage.id}",
                )
        except Exception as _exc:  # noqa: BLE001 — automat nigdy nie psuje ruchu
            logger.warning("cv_qc spawn failed stage=%s: %s", stage.id, _exc)

    resp = _stage_response(
        stage, show_client_rate=user_can_view_client_rate(current_user)
    )
    resp["scheduled_rejection_email_id"] = scheduled_rejection_email_id
    # F05: nowa wersja procesu po ruchu — karta podmienia ją od razu, żeby
    # kolejny ruch z tej samej karty (przed odświeżeniem tablicy) nie wysłał
    # wersji sprzed własnego ruchu i nie dostał 409 za samego siebie.
    versions = await _process_state_versions(
        db, job_id=data.job_id, candidate_ids=[data.candidate_id]
    )
    resp["process_state_version"] = versions.get(data.candidate_id, 0)
    return CandidateStageResponse(**resp)


def _bucket_by_stage_def(
    entries: Iterable[CandidateStage],
    stage_defs: Sequence[PipelineStageDef],
    foreign_defs: Optional[Mapping[int, PipelineStageDef]] = None,
) -> tuple[dict[int, list[CandidateStage]], list[CandidateStage]]:
    """Rozdziel karty na kolumny szablonu i kubełek „poza szablonem".

    Partycja jest **wyczerpująca i rozłączna** — każdy wpis trafia dokładnie
    w jedno miejsce. Wcześniej ta pętla miała dwie ścieżki wyjścia i brak
    trzeciej, więc karta, która nie pasowała do żadnej kolumny, po prostu
    znikała: bez kolumny, bez licznika, bez ostrzeżenia (1 633 karty na
    produkcji, pomiar 2026-09-02).

    Każda gałąź kończy się `continue`, żeby nie dało się dopisać czwartej
    ścieżki, która znowu po cichu zgubi wpis. Czysta funkcja — testowalna bez
    bazy i bez HTTP, więc strażnik przeżyje refaktor endpointu.
    """

    enum_to_def: dict[str, PipelineStageDef] = {
        sd.legacy_enum_value: sd for sd in stage_defs if sd.legacy_enum_value
    }
    columns_map: dict[int, list[CandidateStage]] = {sd.id: [] for sd in stage_defs}
    off_template: list[CandidateStage] = []

    for entry in entries:
        # `None not in columns_map` — klucze to int-y, więc wiersz bez
        # `stage_def_id` (produkuje go dziś `/bulk-move` i `open_process`)
        # poprawnie spada do fallbacku po legacy enumie.
        if entry.stage_def_id in columns_map:
            columns_map[entry.stage_def_id].append(entry)
            continue
        foreign = (
            foreign_defs.get(entry.stage_def_id)
            if foreign_defs is not None and entry.stage_def_id is not None
            else None
        )
        if foreign is not None:
            # Etap innego szablonu (import Traffita na rekrutacji bez własnego
            # szablonu): najpierw nazwa, potem kod — `foreign_stage_target`.
            target = foreign_stage_target(
                foreign.name, foreign.legacy_enum_value, stage_defs
            )
            if target is not None:
                columns_map[target.id].append(entry)
            else:
                off_template.append(entry)
            continue
        mapped = enum_to_def.get(entry.stage.value) if entry.stage else None
        if mapped is not None:
            columns_map[mapped.id].append(entry)
            continue
        off_template.append(entry)

    return columns_map, off_template


# ── Jedna definicja kolumny tablicy — dla tablicy I dla listy rekrutacji ─────
#
# Do 09.2026 lista `/api/jobs?include_stage_counts` liczyła kubełki po legacy
# enumie `CandidateStage.stage`, a tablica po kolumnach szablonu. Własny etap
# szablonu bez enuma („Przepuszczony przez DZ") na tablicy stał ZA screeningiem
# (front liczył go do zweryfikowanych), a na liście niósł `stage=new` (Nowi).
# Ta sama rekrutacja: 4/1/1/2 na liście, 3/1/2/2 w szczegółach (UAT B33).
# Obie powierzchnie budują teraz kolumny TYMI SAMYMI funkcjami, a front grupuje
# je jedną funkcją (`groupKanbanColumns`).


@dataclass(frozen=True)
class StageTally:
    """Zliczony wpis pipeline'u — jak `CandidateStage`, ale z wagą.

    Lista rekrutacji zlicza pary jednym `GROUP BY (job, stage_def, stage)`
    zamiast ładować wiersze; `_bucket_by_stage_def` czyta tylko `stage_def_id`
    i `stage`, więc kubełkowanie jest to samo co na tablicy.
    """

    stage_def_id: Optional[int]
    stage: Optional[PipelineStage]
    count: int = 1


def _tally_weight(entry) -> int:
    return int(getattr(entry, "count", 1) or 0)


def template_column_meta(sd: PipelineStageDef) -> dict:
    """Pola kolumny wynikające z definicji etapu szablonu (bez kart i liczby)."""
    legacy = None
    if sd.legacy_enum_value:
        try:
            legacy = PipelineStage(sd.legacy_enum_value)
        except ValueError:
            legacy = PipelineStage.new
    return {
        "stage": legacy or PipelineStage.new,
        "category": sd.category,
        "stage_def_id": sd.id,
        "name": sd.name,
        "order": sd.order,
        "terminal_type": sd.terminal_type.value if sd.terminal_type else None,
    }


def legacy_column_meta(stage: PipelineStage) -> dict:
    """Pola kolumny w gałęzi bez szablonu (kolumny SĄ legacy enumami)."""
    return {
        "stage": stage,
        "category": STAGE_CATEGORY[stage],
        "name": STAGE_LABELS[stage],
        "terminal_type": _LEGACY_TERMINAL_TYPE.get(stage),
    }


LEGACY_COLUMN_STAGES: list[PipelineStage] = list(STAGE_ORDER) + [
    PipelineStage.rejected,
    PipelineStage.withdrawn,
]


def stage_column_summaries(
    stage_defs: Sequence[PipelineStageDef],
    entries: Iterable,
    foreign_defs: Optional[Mapping[int, PipelineStageDef]] = None,
) -> tuple[list[dict], int]:
    """Kolumny szablonu z liczbami (bez kart) + liczba wpisów poza szablonem.

    Ten sam podział co `get_kanban` (`_bucket_by_stage_def` + `template_column_meta`),
    więc suma per kolumna na liście równa się `count` kolumny na tablicy.
    """
    columns_map, off_template = _bucket_by_stage_def(entries, stage_defs, foreign_defs)
    columns = [
        {
            **template_column_meta(sd),
            "count": sum(_tally_weight(e) for e in columns_map.get(sd.id, [])),
        }
        for sd in stage_defs
    ]
    return columns, sum(_tally_weight(e) for e in off_template)


def legacy_stage_column_summaries(entries: Iterable) -> tuple[list[dict], int]:
    """Lustro gałęzi `get_kanban` bez szablonu: kolumna na każdy legacy enum."""
    counts: dict[PipelineStage, int] = {s: 0 for s in LEGACY_COLUMN_STAGES}
    off_template = 0
    for entry in entries:
        if entry.stage in counts:
            counts[entry.stage] += _tally_weight(entry)
        else:
            off_template += _tally_weight(entry)
    columns = [
        {**legacy_column_meta(stage), "count": counts[stage]}
        for stage in LEGACY_COLUMN_STAGES
    ]
    return columns, off_template


async def _build_off_template(
    db: AsyncSession,
    *,
    job_id: int,
    entries: Sequence[CandidateStage],
    render,
) -> Optional[OffTemplateColumn]:
    """Zbuduj kubełek — albo `None`, gdy szablon pokrywa każdą kartę.

    Etykiety mówią, na jakich etapach te karty stoją; bez nich rekruter widzi
    kubełek, ale nie wie, dokąd kartę wyprowadzić. Zapytanie o nazwy etapów
    z obcego szablonu leci **tylko gdy kubełek jest niepusty**, więc zdrowa
    tablica nie płaci za to ani jednym round-tripem.
    """

    if not entries:
        return None

    labels: list[str] = []
    foreign_def_ids = {e.stage_def_id for e in entries if e.stage_def_id is not None}
    names_by_def_id: dict[int, str] = {}
    if foreign_def_ids:
        rows = await db.execute(
            select(PipelineStageDef.id, PipelineStageDef.name).where(
                PipelineStageDef.id.in_(foreign_def_ids)
            )
        )
        names_by_def_id = {def_id: name for def_id, name in rows.all()}

    for entry in entries:
        label = names_by_def_id.get(entry.stage_def_id) if entry.stage_def_id else None
        if label is None and entry.stage is not None:
            label = STAGE_LABELS.get(entry.stage, entry.stage.value)
        if label and label not in labels:
            labels.append(label)

    # Metryka spadku bez zmiany zachowania — sieroty powstają NADAL
    # (`/bulk-move` i `open_process` zapisują `stage_def_id=NULL`), więc ten
    # licznik ma rosnąć albo maleć, a nie zostać zapomniany.
    logger.warning(
        "kanban off-template bucket: job=%s cards=%d stages=%s",
        job_id,
        len(entries),
        labels,
    )

    return OffTemplateColumn(
        name="Poza szablonem",
        count=len(entries),
        items=[CandidateStageResponse(**render(e)) for e in entries],
        missing_stage_labels=labels,
    )


@router.get("/kanban/{job_id}", response_model=KanbanView)
async def get_kanban(
    job_id: int,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
):
    """
    Return kanban view for a job — columns driven by the job's pipeline template.

    Backward-compat: rows whose stage_def_id is NULL are bucketed by legacy enum
    via PipelineStageDef.legacy_enum_value lookup.
    """
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # P1-PIPE-01: reading a job's board is a pipeline ingress — members only.
    await ensure_job_read_access(db, current_user, job.id)
    return await build_kanban_view(db, job, viewer=current_user)


# Ostrzeżenia miękkie polityki dopuszczalności, które karta pokazuje jako kody.
# `already_in_job` nie ma tu sensu (karta JEST w rekrutacji), a weto HM ma
# własny, stały kod `hm_veto` (front zna go z pola `hm_veto`).
_CARD_WARNING_SKIP = frozenset(
    {"eligible", "already_in_job", "rejected_by_hiring_manager"}
)


def _card_warnings(stage: CandidateStage, *, decision, has_veto: bool) -> list[str]:
    """Kody ostrzeżeń karty — stała kolejność, bez duplikatów."""
    codes: list[str] = []
    if has_veto:
        codes.append("hm_veto")
    if _budget_exceeded(stage):
        codes.append("budget_exceeded")
    if decision is not None:
        for reason in (decision.reason_code, *decision.secondary_reasons):
            code = getattr(reason, "value", str(reason))
            if code not in _CARD_WARNING_SKIP and code not in codes:
                codes.append(code)
    return codes


def _with_next_action_owner(payload: dict, column: StageColumn, group: str) -> dict:
    """Dopisz `next_action_owner` — ta sama reguła co karta na froncie."""
    payload["next_action_owner"] = next_action_for(
        column,
        days_in_stage=payload.get("days_in_stage"),
        screening_done=payload.get("screening_done"),
        hm_veto=payload.get("hm_veto") is not None,
        group=group,
    ).owner
    return payload


async def build_kanban_view(
    db: AsyncSession, job: Job, *, viewer: Optional[User] = None
) -> KanbanView:
    """The board of ``job`` — shared by ``/kanban/{job_id}`` and ``/my-next-steps``.

    The caller has already checked access (``ensure_job_read_access``); this
    function only reads.

    ``recruiter_id`` / ``recruiter_name`` on a card = the explicit owner of the
    pair's latest recruitment process, and when the process has no owner, the
    person who ADDED the candidate to this job (mover on the earliest stage
    row). Deliberately not ``moved_by`` — that is whoever moved the card last
    (decision of the product owner, 21.09.2026).
    """
    job_id = job.id
    # All CandidateStage rows for this job, newest→oldest per candidate.
    # Secondary id.desc() makes the per-candidate "first" (latest) and "last"
    # (earliest) rows deterministic when two moves share a `moved_at`.
    result = await db.execute(
        select(CandidateStage)
        .where(CandidateStage.job_id == job_id)
        .order_by(
            CandidateStage.candidate_id,
            CandidateStage.moved_at.desc(),
            CandidateStage.id.desc(),
        )
    )
    all_stages = result.scalars().all()
    # First row per candidate = current (latest) stage → the card.
    # Last row per candidate = earliest stage → who assigned them to the job.
    seen: dict[int, CandidateStage] = {}
    earliest: dict[int, CandidateStage] = {}
    # Pipeline v4: screening i stawki wpisane na WCZEŚNIEJSZYM etapie należą do
    # pary (kandydat, rekrutacja) — karta w „Rozmowie u klienta" nie może udawać,
    # że screeningu nie było, a stawka kandydata z weryfikacji zniknęła.
    screened_pairs: set[int] = set()
    carried_expected_rate: dict[int, CandidateStage] = {}
    carried_client_rate: dict[int, CandidateStage] = {}
    for s in all_stages:
        if s.candidate_id not in seen:
            seen[s.candidate_id] = s
        earliest[s.candidate_id] = s  # overwritten; last write wins (oldest row)
        if _sheet_filled(s.screening_answers):
            screened_pairs.add(s.candidate_id)
        if s.expected_rate_value is not None:
            carried_expected_rate.setdefault(s.candidate_id, s)
        if s.client_rate_value is not None:
            carried_client_rate.setdefault(s.candidate_id, s)
    show_client_rate = user_can_view_client_rate(viewer)

    # Bulk-load candidate names so cards render with real names (not "Kandydat" fallback)
    candidate_ids = list(seen.keys())
    contact_case_by_candidate = await load_contact_case_summaries(db, candidate_ids)
    name_by_id: dict[int, tuple[Optional[str], Optional[str]]] = {}
    # Stawka z profilu (PLN/h) — podpowiedź w oknie „Zweryfikowany" (17.09.2026).
    profile_rate_by_id: dict[int, Optional[Decimal]] = {}
    # Dostępność z profilu (tabela rekrutacji „wersja 3") i lekkie wiersze dla
    # polityki dopuszczalności — TO SAMO zapytanie, bez ładowania całej encji.
    availability_by_id: dict[int, tuple[Optional[str], Optional[date]]] = {}
    eligibility_rows: dict[int, SimpleNamespace] = {}
    if candidate_ids:
        rows = await db.execute(
            select(
                Candidate.id,
                Candidate.name,
                Candidate.lastname,
                Candidate.expected_rate_hourly,
                Candidate.availability_status,
                Candidate.availability_date,
                Candidate.status,
                Candidate.preferences,
            ).where(Candidate.id.in_(candidate_ids))
        )
        for (
            cid,
            cname,
            clastname,
            rate_hourly,
            availability_status,
            availability_date,
            candidate_status,
            preferences,
        ) in rows.all():
            name_by_id[cid] = (cname, clastname)
            profile_rate_by_id[cid] = rate_hourly
            availability_by_id[cid] = (
                availability_status.value if availability_status else None,
                availability_date,
            )
            eligibility_rows[cid] = SimpleNamespace(
                id=cid, status=candidate_status, preferences=preferences
            )

    # Bulk-load names of the recruiters who first assigned each candidate to the
    # job (mover on the earliest stage). One query, no per-card N+1.
    added_by_user_ids = {
        e.moved_by for e in earliest.values() if e.moved_by is not None
    }
    user_name_by_id: dict[int, Optional[str]] = {}
    if added_by_user_ids:
        urows = await db.execute(
            select(User.id, User.name).where(User.id.in_(added_by_user_ids))
        )
        for uid, uname in urows.all():
            user_name_by_id[uid] = uname

    # Standing rejections by this job's hiring manager, one batched query for
    # the whole board (none at all when the job has no manager set). Lets the
    # recruiter see the block before dragging a card into it, instead of
    # discovering it as a 409 halfway through the move.
    #
    # Od 09.2026 werdykty przychodzą razem z decyzjami dopuszczalności (ta sama
    # wsadowa polityka co przy ruchu): karta niesie `warnings` — kody ostrzeżeń
    # miękkich (konflikt z klientem, NDA, obecne zatrudnienie…) — bez N+1.
    # `candidates=` podaje lekkie wiersze z zapytania wyżej, więc polityka nie
    # ładuje drugi raz pełnych encji kandydatów.
    (
        eligibility_decisions,
        manager_verdicts,
    ) = await evaluate_candidates_for_job_with_verdicts(
        db,
        job=job,
        candidate_ids=candidate_ids,
        now=datetime.now(timezone.utc),
        candidates=eligibility_rows,
    )
    # F05: wersja procesu na karcie — front odsyła ją przy ruchu
    # (`expected_state_version`). Jedno zapytanie dla całej tablicy; to samo
    # zapytanie niesie właściciela procesu (`recruiter_id` karty).
    process_cards = await _process_cards(db, job_id=job_id, candidate_ids=candidate_ids)
    process_versions = {cid: card[0] for cid, card in process_cards.items()}
    owner_ids = {card[1] for card in process_cards.values() if card[1] is not None}
    # Pipeline v4 (0352): blokada 12 h, źródło wejścia i przepięcie.
    v4_processes = await _process_v4_cards(
        db, job_id=job_id, candidate_ids=candidate_ids
    )
    owner_ids |= {
        p.claimed_by_user_id
        for p in v4_processes.values()
        if p.claimed_by_user_id is not None
    }
    reassign_job_ids = {
        p.reassign_from_job_id
        for p in v4_processes.values()
        if p.reassign_from_job_id is not None
    }
    reassign_titles: dict[int, str] = {}
    if reassign_job_ids:
        reassign_titles = dict(
            (
                await db.execute(
                    select(Job.id, Job.title).where(Job.id.in_(reassign_job_ids))
                )
            ).all()
        )
    board_now = datetime.now(timezone.utc)
    # Odznaki terminarza rozmowy u klienta i status zamówienia zatrudnionych —
    # po jednym zapytaniu hurtowym (liczone w serwisach, front tylko rysuje).
    from app.services.hired_order_status import order_status_for_pairs
    from app.services.interview_cycle import interview_badges_for_job

    interview_badges = await interview_badges_for_job(
        db, job_id=job_id, candidate_ids=candidate_ids, now=board_now
    )
    hired_ids = [
        s.candidate_id for s in seen.values() if s.stage == PipelineStage.hired
    ]
    order_statuses = (
        await order_status_for_pairs(db, [(cid, job_id) for cid in hired_ids])
        if hired_ids
        else {}
    )
    # 0348: wytypowani do wysłania do Cpro — ta sama paczka nazwisk.
    owner_ids |= {
        s.task_assignee_id for s in seen.values() if s.task_assignee_id is not None
    }
    missing_owner_names = owner_ids - set(user_name_by_id)
    if missing_owner_names:
        orows = await db.execute(
            select(User.id, User.name).where(User.id.in_(missing_owner_names))
        )
        for uid, uname in orows.all():
            user_name_by_id[uid] = uname

    # Auto-CV gotowe w tle i czekające na przegląd (21.09.2026) — JEDNO
    # zapytanie na tablicę; flaga dotyczy wiersza etapu, na którym je zakolejkowano.
    from app.services.cv_auto_review import job_stages_with_ready_auto_cv

    auto_cv_stage_ids = await job_stages_with_ready_auto_cv(db, job_id)
    # Rekrutacja v5 (0361): stan QC CV każdej karty — jedno zapytanie hurtowe
    # (najnowszy przebieg pary; obejście DL/admina = `overridden`).
    from app.services.cv_qc import pair_statuses

    qc_by_pair = await pair_statuses(db, [(cid, job_id) for cid in candidate_ids])

    def _stage_resp_with_name(e: CandidateStage) -> dict:
        n, ln = name_by_id.get(e.candidate_id, (None, None))
        first = earliest.get(e.candidate_id)
        added_by_name = (
            user_name_by_id.get(first.moved_by)
            if first is not None and first.moved_by is not None
            else None
        )
        added_at = first.moved_at if first is not None else None
        payload = _stage_response(
            e,
            show_client_rate=show_client_rate,
            candidate_name=n,
            candidate_lastname=ln,
            added_to_job_by_name=added_by_name,
            added_to_job_at=added_at,
            candidate_expected_rate_hourly=profile_rate_by_id.get(e.candidate_id),
        )
        payload["screening_done"] = e.candidate_id in screened_pairs
        if e.expected_rate_value is None:
            rate_row = carried_expected_rate.get(e.candidate_id)
            if rate_row is not None:
                payload["expected_rate_value"] = rate_row.expected_rate_value
                payload["expected_rate_unit"] = rate_row.expected_rate_unit
                payload["expected_rate_currency"] = rate_row.expected_rate_currency
        client_row = carried_client_rate.get(e.candidate_id)
        if show_client_rate and client_row is not None:
            payload["client_rate_value"] = client_row.client_rate_value
            payload["client_rate_unit"] = client_row.client_rate_unit
            payload["client_rate_currency"] = client_row.client_rate_currency
        elif not show_client_rate:
            # Decyzja 23.09.2026: rekruter nie widzi, za ile osoba poszła do klienta.
            payload["client_rate_value"] = None
            payload["client_rate_unit"] = None
            payload["client_rate_currency"] = None
        payload["contact_case"] = contact_case_by_candidate.get(e.candidate_id)
        payload["process_state_version"] = process_versions.get(e.candidate_id, 0)
        payload["auto_cv_ready"] = e.id in auto_cv_stage_ids
        payload["qc"] = qc_by_pair.get((e.candidate_id, job_id))
        # Rekruter karty: właściciel procesu (Priority Work), a gdy proces go
        # nie ma — osoba, która dodała kandydata do rekrutacji.
        process_owner = process_cards.get(e.candidate_id, (0, None))[1]
        recruiter_id = (
            process_owner
            if process_owner is not None
            else (first.moved_by if first is not None else None)
        )
        payload["recruiter_id"] = recruiter_id
        payload["recruiter_name"] = (
            user_name_by_id.get(recruiter_id) if recruiter_id is not None else None
        )
        if e.task_assignee_id is not None:
            payload["task_assignee_name"] = user_name_by_id.get(e.task_assignee_id)
        payload["interview_badge"] = interview_badges.get(e.candidate_id)
        if e.stage == PipelineStage.hired:
            payload["order_status"] = order_statuses.get((e.candidate_id, job_id))
        v4 = v4_processes.get(e.candidate_id)
        if v4 is not None:
            payload["entry_source"] = v4.entry_source
            payload["reassign_from_job_id"] = v4.reassign_from_job_id
            if v4.reassign_from_job_id is not None:
                payload["reassign_from_title"] = reassign_titles.get(
                    v4.reassign_from_job_id
                )
            claim = candidate_claim.claim_state(v4)
            if claim.active(board_now):
                payload["claim_user_id"] = claim.user_id
                payload["claim_user_name"] = user_name_by_id.get(claim.user_id)
                payload["claim_until"] = claim.until
            if viewer is not None:
                payload["can_take"] = candidate_claim.can_take(v4, viewer, board_now)
        elif viewer is not None:
            payload["can_take"] = True
        availability = availability_by_id.get(e.candidate_id, (None, None))
        payload["availability_status"] = availability[0]
        payload["availability_date"] = availability[1]
        payload["warnings"] = _card_warnings(
            e,
            decision=eligibility_decisions.get(e.candidate_id),
            has_veto=e.candidate_id in manager_verdicts,
        )
        verdict = manager_verdicts.get(e.candidate_id)
        if verdict is not None:
            payload["hm_veto"] = HiringManagerVetoBrief(
                hiring_manager_contact_id=verdict.hiring_manager_contact_id,
                hiring_manager_name=verdict.hiring_manager_name,
                source_job_id=verdict.source_job_id,
                source_job_title=verdict.source_job_title,
                rejected_at=verdict.rejected_at,
                rejection_reason_name=verdict.rejection_reason_name,
                rejection_note=verdict.rejection_note,
            )
        return payload

    # Resolve target template
    template_id = job.pipeline_template_id or await _default_template_id(db)

    if template_id is not None:
        # Template-driven columns
        stage_defs = (
            (
                await db.execute(
                    select(PipelineStageDef)
                    .where(PipelineStageDef.template_id == template_id)
                    .order_by(PipelineStageDef.order)
                )
            )
            .scalars()
            .all()
        )

        template_def_ids = {sd.id for sd in stage_defs}
        foreign_ids = {
            e.stage_def_id
            for e in seen.values()
            if e.stage_def_id is not None and e.stage_def_id not in template_def_ids
        }
        foreign_defs = (
            {
                sd.id: sd
                for sd in (
                    await db.execute(
                        select(PipelineStageDef).where(
                            PipelineStageDef.id.in_(foreign_ids)
                        )
                    )
                ).scalars()
            }
            if foreign_ids
            else {}
        )
        columns_map, off_template_entries = _bucket_by_stage_def(
            seen.values(), stage_defs, foreign_defs
        )

        columns = []
        metas = [template_column_meta(sd) for sd in stage_defs]
        rule_columns = [StageColumn.from_meta(m) for m in metas]
        groups = group_keys_for_columns(rule_columns)
        for sd, meta, rule_col, group in zip(stage_defs, metas, rule_columns, groups):
            entries = columns_map.get(sd.id, [])
            # Te same pola co `stage_columns` na liście rekrutacji
            # (`template_column_meta`) — jedna definicja kolumny.
            columns.append(
                KanbanColumn(
                    **meta,
                    count=len(entries),
                    items=[
                        CandidateStageResponse(
                            **_with_next_action_owner(
                                _stage_resp_with_name(e), rule_col, group
                            )
                        )
                        for e in entries
                    ],
                )
            )
        return KanbanView(
            job_id=job_id,
            columns=columns,
            off_template=await _build_off_template(
                db,
                job_id=job_id,
                entries=off_template_entries,
                render=_stage_resp_with_name,
            ),
        )

    # ── Legacy fallback (no template seeded yet) ──────────────────────────────
    # Ta gałąź pokrywa cały `PipelineStage`, więc dziś nic tu nie ginie. Kubełek
    # jest mimo to zbierany, żeby inwariant „suma kolumn + kubełek == liczba par"
    # trzymał na OBU ścieżkach i test regresji nie musiał się rozgałęziać.
    columns_map_legacy: dict[PipelineStage, list[CandidateStage]] = {
        s: [] for s in STAGE_ORDER
    }
    columns_map_legacy[PipelineStage.rejected] = []
    columns_map_legacy[PipelineStage.withdrawn] = []
    off_template_entries = []
    for stage_entry in seen.values():
        if stage_entry.stage in columns_map_legacy:
            columns_map_legacy[stage_entry.stage].append(stage_entry)
            continue
        off_template_entries.append(stage_entry)

    columns = []
    legacy_metas = [legacy_column_meta(stage) for stage in LEGACY_COLUMN_STAGES]
    legacy_rule_columns = [StageColumn.from_meta(m) for m in legacy_metas]
    legacy_groups = group_keys_for_columns(legacy_rule_columns)
    for stage, meta, rule_col, group in zip(
        LEGACY_COLUMN_STAGES, legacy_metas, legacy_rule_columns, legacy_groups
    ):
        entries = columns_map_legacy.get(stage, [])
        # W tej gałęzi (brak szablonu) kolumny SĄ legacy enumami, więc terminal
        # wynika wprost z nazwy etapu (`legacy_column_meta`) — te same pola co
        # wyżej i co `stage_columns` na liście rekrutacji.
        columns.append(
            KanbanColumn(
                **meta,
                count=len(entries),
                items=[
                    CandidateStageResponse(
                        **_with_next_action_owner(
                            _stage_resp_with_name(e), rule_col, group
                        )
                    )
                    for e in entries
                ],
            )
        )
    return KanbanView(
        job_id=job_id,
        columns=columns,
        off_template=await _build_off_template(
            db,
            job_id=job_id,
            entries=off_template_entries,
            render=_stage_resp_with_name,
        ),
    )


# Dashboard section "Następne kroki w moich rekrutacjach" — a bounded fan-out.
MY_NEXT_STEPS_JOB_LIMIT = 25


@router.get("/my-next-steps", response_model=MyNextStepsResponse)
async def my_next_steps(
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
) -> MyNextStepsResponse:
    """Boards of the caller's own open recruitments (owner or collaborator).

    The dashboard computes the next action per card from these boards with the
    same rules as the kanban, so the two screens never disagree. At most
    ``MY_NEXT_STEPS_JOB_LIMIT`` recruitments, nearest deadline first;
    ``truncated`` says the list was cut.
    """
    from app.api.jobs import jobs_mine_clause  # noqa: PLC0415 — import cycle

    jobs = (
        await db.scalars(
            select(Job)
            .options(selectinload(Job.client))
            .where(jobs_mine_clause(current_user), Job.status != JobStatus.closed)
            .order_by(Job.deadline.asc().nullslast(), Job.id.desc())
            # One extra row tells a full page from a cut list.
            .limit(MY_NEXT_STEPS_JOB_LIMIT + 1)
        )
    ).all()
    truncated = len(jobs) > MY_NEXT_STEPS_JOB_LIMIT
    jobs = jobs[:MY_NEXT_STEPS_JOB_LIMIT]
    out: list[MyNextStepsJob] = []
    for job in jobs:
        try:
            # `jobs_mine_clause` keeps collaborators removed from the team;
            # the board read guard is the one that decides. Widok OSOBISTY:
            # od 23.09.2026 tablicę każdej rekrutacji czyta każdy, więc
            # przypisanie liczymy jawnie (`oversight_bypass=False`).
            await ensure_job_read_access(
                db, current_user, job.id, oversight_bypass=False
            )
        except HTTPException:
            continue
        out.append(
            MyNextStepsJob(
                job_id=job.id,
                title=job.title,
                client_name=job.client.name if job.client else None,
                view=await build_kanban_view(db, job, viewer=current_user),
            )
        )
    return MyNextStepsResponse(jobs=out, truncated=truncated)


@router.get(
    "/history/{candidate_id}/{job_id}", response_model=List[CandidateStageResponse]
)
async def get_stage_history(
    candidate_id: int,
    job_id: int,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
):
    """Full stage history for a candidate in a specific job."""
    # P1-PIPE-01: stage history is a per-job pipeline read — members only
    # (same scope as the kanban board).
    await ensure_job_read_access(db, current_user, job_id)
    result = await db.execute(
        select(CandidateStage)
        .where(
            CandidateStage.candidate_id == candidate_id, CandidateStage.job_id == job_id
        )
        .order_by(CandidateStage.moved_at.asc())
    )
    stages = result.scalars().all()
    show_client_rate = user_can_view_client_rate(current_user)
    return [
        CandidateStageResponse(**_stage_response(s, show_client_rate=show_client_rate))
        for s in stages
    ]


# Dziennik ruchów CAŁEJ rekrutacji. Poprzedni etap liczy LAG po WSZYSTKICH
# wierszach pary (kandydat, rekrutacja) — dlatego okno stoi w CTE, a stronicowanie
# dopiero na zewnątrz: LIMIT w tym samym SELECT-cie ucinałby historię, z której
# LAG czyta. `COUNT(*) OVER ()` = `total` bez drugiego zapytania.
_JOB_MOVES_SQL = text(
    """
    WITH moves AS (
        SELECT cs.id,
               cs.candidate_id,
               cs.stage::text AS stage,
               sd.name AS stage_name,
               cs.moved_by,
               cs.moved_at,
               cs.external_source,
               LAG(cs.stage::text) OVER w AS prev_stage,
               LAG(sd.name) OVER w AS prev_stage_name
        FROM candidate_stages cs
        LEFT JOIN pipeline_stage_defs sd ON sd.id = cs.stage_def_id
        WHERE cs.job_id = :job_id
        WINDOW w AS (PARTITION BY cs.candidate_id ORDER BY cs.moved_at, cs.id)
    )
    SELECT m.id,
           m.candidate_id,
           c.name AS candidate_first_name,
           c.lastname AS candidate_lastname,
           m.stage,
           m.stage_name,
           m.prev_stage,
           m.prev_stage_name,
           m.moved_by,
           u.name AS moved_by_name,
           m.moved_at,
           m.external_source,
           COUNT(*) OVER () AS total
    FROM moves m
    JOIN candidates c ON c.id = m.candidate_id
    LEFT JOIN users u ON u.id = m.moved_by
    ORDER BY m.moved_at DESC, m.id DESC
    LIMIT :limit OFFSET :offset
    """
)

_JOB_MOVES_COUNT_SQL = text(
    "SELECT COUNT(*) FROM candidate_stages cs WHERE cs.job_id = :job_id"
)


def _move_stage_label(stage_name: Optional[str], stage: Optional[str]) -> Optional[str]:
    """Nazwa kolumny szablonu, a dla wierszy bez `stage_def_id` — etykieta enuma."""
    if stage_name:
        return stage_name
    if not stage:
        return None
    try:
        return STAGE_LABELS.get(PipelineStage(stage), stage)
    except ValueError:
        return stage


@router.get("/job/{job_id}/moves")
async def list_job_moves(
    job_id: int,
    current_user: OperationalUser,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Ruchy etapów całej rekrutacji, od najnowszych.

    Ta sama bramka co tablica: odczyt sekcji Pipeline (router) + zakres
    rekrutacji. Imię i nazwisko kandydata tylko dla ról z odczytem kandydatów;
    pozostali dostają `candidate_id` i `candidate_names_redacted`.
    """
    job_exists = await db.scalar(select(Job.id).where(Job.id == job_id))
    if job_exists is None:
        raise HTTPException(status_code=404, detail="Job not found")
    await ensure_job_read_access(db, current_user, job_id)

    show_names = user_has_candidate_read(current_user)
    rows = (
        await db.execute(
            _JOB_MOVES_SQL, {"job_id": job_id, "limit": limit, "offset": offset}
        )
    ).all()
    if rows:
        total = int(rows[0].total)
    elif offset:
        # Strona za końcem listy nie niesie wiersza z `total`.
        total = int(await db.scalar(_JOB_MOVES_COUNT_SQL, {"job_id": job_id}) or 0)
    else:
        total = 0
    items = [
        {
            "id": row.id,
            "candidate_id": row.candidate_id,
            "candidate_name": (
                f"{row.candidate_first_name or ''} {row.candidate_lastname or ''}".strip()
                or None
            )
            if show_names
            else None,
            "from_stage_name": _move_stage_label(row.prev_stage_name, row.prev_stage),
            "to_stage_name": _move_stage_label(row.stage_name, row.stage),
            "moved_by_id": row.moved_by,
            "moved_by_name": row.moved_by_name,
            "moved_at": row.moved_at,
            # Wiersze z importu niosą `external_source='traffit'`; ruch zrobiony
            # w NEXUSIE ma 'manual' albo NULL.
            "source": "traffit" if row.external_source == "traffit" else "nexus",
        }
        for row in rows
    ]
    return {
        "job_id": job_id,
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "next_offset": offset + limit if offset + limit < total else None,
        "candidate_names_redacted": not show_names,
    }


# ── Champion-profile screening answers (Phase 10) ───────────────────────────


@router.get("/stages/{stage_id}/screening")
async def get_stage_screening(
    stage_id: int,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
):
    """Return recruiter screening answers + the job's Champion Profile."""
    stage = await db.scalar(select(CandidateStage).where(CandidateStage.id == stage_id))
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found")
    # Odpowiedzi screeningu i profil Championa należą do rekrutacji — ten sam
    # zakres odczytu co tablica (`/kanban/{job_id}`), nie sama rola.
    await ensure_job_read_access(db, current_user, stage.job_id)
    job = await db.scalar(select(Job).where(Job.id == stage.job_id))
    from app.services.screening_suggestions import suggestions_from_notes

    candidate = await db.get(Candidate, stage.candidate_id)
    answers, source_stage_id = await _latest_filled_screening(db, stage)
    return {
        "stage_id": stage.id,
        "candidate_id": stage.candidate_id,
        "job_id": stage.job_id,
        # Podpowiedzi stawki i dostępności z notatek (21.09.2026): odczyt
        # gotowego `_notes_insights`, bez wywołania modelu i BEZ zapisu
        # gdziekolwiek — arkusz tylko je pokazuje. Stawka wyłącznie dla ról,
        # które mogą ją wpisać przy ruchu na „Zweryfikowany".
        "suggestions": suggestions_from_notes(
            candidate, include_rate=user_can_edit_rates(current_user)
        ),
        # Ten sam kontrakt co `/jobs/{id}/champion-profile`: front zna wyłącznie
        # siedem sekcji, a surowy kształt sprzed 09.2026 pokazałby mu pustkę na
        # wypełnionym profilu.
        "champion_profile": champion_view.api_response(
            job.champion_profile if job else None
        ),
        "screening_answers": answers,
        # Pipeline v4: arkusz należy do pary, nie do etapu — zapisany w „Nowych"
        # czyta się dalej na „Zweryfikowanym" (przegląd DL) i w rozmowie.
        "screening_source_stage_id": source_stage_id,
    }


async def _latest_filled_screening(
    db: AsyncSession, stage: CandidateStage
) -> tuple[Optional[dict], Optional[int]]:
    """Arkusz screeningu etapu, a gdy pusty — najnowszy wypełniony tej pary."""
    if _sheet_filled(stage.screening_answers):
        return stage.screening_answers, None
    rows = await db.execute(
        select(CandidateStage.id, CandidateStage.screening_answers)
        .where(
            CandidateStage.candidate_id == stage.candidate_id,
            CandidateStage.job_id == stage.job_id,
            CandidateStage.id != stage.id,
            CandidateStage.screening_answers.isnot(None),
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
    )
    for row_id, answers in rows.all():
        if _sheet_filled(answers):
            return answers, row_id
    return stage.screening_answers or None, None


@router.post("/stages/{stage_id}/screening")
async def submit_stage_screening(
    stage_id: int,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
    payload: dict | None = None,
):
    """Recruiter records answers to the Champion Profile screening questions.
    Also invalidates the (candidate, *) match score cache so the next
    recommendation read recomputes `champion_fit`.
    """
    from app.schemas.champion import ScreeningAnswers
    from app.services.match_score_cache import mark_stale_for_candidate

    stage = await db.scalar(select(CandidateStage).where(CandidateStage.id == stage_id))
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found")
    # Zapis screeningu to mutacja pipeline'u tej rekrutacji — ta sama bramka
    # członkostwa co `/move`; do 09.2026 wystarczała sama rola.
    await ensure_job_membership(db, current_user, stage.job_id)
    # Pipeline v4: rozmowę z osobą zarezerwowaną prowadzi jej rekruter (12 h).
    await candidate_claim.assert_can_act(
        db,
        process=await candidate_claim.load_process(
            db, candidate_id=stage.candidate_id, job_id=stage.job_id
        ),
        user=current_user,
    )

    answers = ScreeningAnswers.model_validate(payload or {})
    answers.answered_at = datetime.now(timezone.utc)
    answers.answered_by = current_user.id

    stage.screening_answers = answers.model_dump(mode="json")
    db.add(
        Activity(
            entity_type="candidate_stage",
            entity_id=stage.id,
            action="screening_answered",
            user_id=current_user.id,
            details={
                "candidate_id": stage.candidate_id,
                "job_id": stage.job_id,
                "overall_fit": answers.overall_fit,
                "match_percent": answers.match_percent(),
            },
        )
    )
    await db.commit()

    # Mark cached scores stale — champion_fit layer depends on these answers.
    # Cache nie ma TTL, więc nieudana invalidacja NIE naprawia się sama: kompozyt
    # (kandydat, oferta) serwuje przedscreeningowy `champion_fit` do czasu, aż coś
    # innego przypadkiem oznaczy tego kandydata. Milczące połknięcie czytało się
    # jak „AI nie zgadza się z moim screeningiem", więc zostawiamy ślad w logu
    # (LoggingIntegration mostkuje to do Sentry) i mówimy UI, że wynik jest stary.
    cache_invalidated = True
    try:
        await mark_stale_for_candidate(db, stage.candidate_id)
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        cache_invalidated = False
        logger.warning(
            "match-score staleness marking failed for candidate=%s stage=%s: %s",
            stage.candidate_id,
            stage.id,
            exc,
        )
        await db.rollback()

    await db.refresh(stage)
    return {
        "stage_id": stage.id,
        "match_percent": answers.match_percent(),
        "screening_answers": stage.screening_answers,
        "cache_invalidated": cache_invalidated,
    }


# ── Champion Card share tokens (Phase 12) ───────────────────────────────────


@router.post("/stages/{stage_id}/share-token")
async def create_share_token(
    stage_id: int,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
    expires_in_days: int = Query(30, ge=1, le=365),
):
    """Generate a shareable token for this CandidateStage's Champion card."""
    import hashlib
    import secrets
    from datetime import timedelta

    from app.models.champion_share import ChampionCardShareToken

    stage = await db.scalar(select(CandidateStage).where(CandidateStage.id == stage_id))
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found")

    # Resource scope: wystawienie linku dla klienta to działanie NA rekrutacji,
    # nie ogólna operacja rekrutera. Bez tego członek zespołu oferty A mógł
    # wygenerować działający, publiczny link do karty kandydata z oferty B.
    await ensure_job_membership(db, current_user, stage.job_id)

    # Same outbound gate as the CV share link — this card goes to the client too.
    verdict = await veto_for_candidate_stage(db, candidate_stage_id=stage_id)
    if verdict is not None:
        raise HTTPException(
            status_code=409,
            detail=f"{verdict.as_polish_detail()} Nie wysyłaj mu go ponownie.",
        )

    # v2: the secret lives only in the URL and as a SHA-256 digest in the DB.
    # The PK holds a non-secret revoke key, so a DB leak yields no working link.
    raw_token = secrets.token_urlsafe(36)
    revoke_key = f"v2${secrets.token_hex(16)}"
    token_digest = hashlib.sha256(raw_token.encode()).hexdigest()
    token = raw_token  # goes into the share URL
    expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)
    row = ChampionCardShareToken(
        token=revoke_key,
        token_sha256=token_digest,
        candidate_stage_id=stage_id,
        created_by=current_user.id,
        expires_at=expires_at,
    )
    db.add(row)
    db.add(
        Activity(
            entity_type="candidate_stage",
            entity_id=stage_id,
            action="champion_share_created",
            user_id=current_user.id,
            details={"expires_at": expires_at.isoformat()},
        )
    )
    await db.commit()
    return {
        "token": token,
        "expires_at": expires_at.isoformat(),
        "share_url_suffix": f"/share/champion-card/{token}",
    }


@router.delete("/stages/share-token/{token}")
async def revoke_share_token(
    token: str,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    """Revoke (soft-delete) a previously issued share token."""
    import hashlib

    from app.models.champion_share import ChampionCardShareToken

    # The caller holds the raw secret from the share URL, not the v2 PK
    # (revoke_key), so match the same dual-read way the public lookup does —
    # otherwise v2 tokens would be unrevocable.
    digest = hashlib.sha256(token.encode()).hexdigest()
    row = await db.scalar(
        select(ChampionCardShareToken).where(
            (ChampionCardShareToken.token_sha256 == digest)
            | (
                (ChampionCardShareToken.token == token)
                & (ChampionCardShareToken.token_sha256.is_(None))
            )
        )
    )
    if not row:
        raise HTTPException(status_code=404, detail="Token not found")

    # Resource scope — token adresuje zasób bez `stage_id` w ścieżce, więc
    # rekrutację wyprowadzamy z `candidate_stage_id` tokenu. Odwołanie cudzego
    # linku to zmiana stanu w cudzej rekrutacji (i sygnał, że taki link
    # istnieje), więc podlega tej samej bramce co jego wystawienie.
    job_id = await db.scalar(
        select(CandidateStage.job_id).where(CandidateStage.id == row.candidate_stage_id)
    )
    if job_id is None:
        raise HTTPException(status_code=404, detail="Token not found")
    await ensure_job_membership(db, current_user, job_id)

    row.revoked = True
    await db.commit()
    return {"status": "revoked", "token": token}


@router.get("/overview")
async def pipeline_overview(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Manager dashboard: bird's eye view across ALL jobs.
    Returns per-job stage counts + bottleneck alerts + workload per recruiter.

    F-07: gated to OperationalUser (excludes the read-only ``user`` viewer).
    The overview aggregates pipeline data across every job — recruiter workload,
    per-job candidate counts — which is operational intelligence, not a public
    dashboard. The bare ``CurrentUser`` let a QC/client viewer read it all.
    """

    # Optymalizacja 2026-07-27: dawniej `select(CandidateStage)` bez WHERE i bez
    # LIMIT (pełna hydratacja ~158k obiektów ORM z JSONB `scorecard_answers` /
    # `screening_answers` + Text `notes`) i dedupe pętlą w Pythonie, bez cache.
    # Teraz agregaty liczy Postgres na widoku `analytics_current_pipeline`
    # (DISTINCT ON per para, indeks `ix_analytics_cs_cand_job_moved`) — wzorzec
    # z `api/dashboard.py::pipeline_funnel`. Kształt odpowiedzi bez zmian.
    BOTTLENECK_THRESHOLD = 3  # More than 3 candidates in prep_call/screening → alert
    AGING_THRESHOLD_DAYS = 5  # Candidate stuck > 5 days → aging alert

    # ── Per-job breakdown (GROUP BY job_id, stage) ──
    # `first_candidate` = MIN(candidate_id): odtwarza kolejność pierwszego
    # wystąpienia joba przy dawnym skanie posortowanym po (candidate_id, job_id).
    per_job_rows = (
        await db.execute(
            text(
                "SELECT job_id, stage::text AS stage, COUNT(*)::int AS cnt, "
                "MIN(candidate_id) AS first_candidate "
                "FROM analytics_current_pipeline GROUP BY job_id, stage"
            )
        )
    ).all()

    jobs_data: dict[int, dict] = {}
    job_first_seen: dict[int, int] = {}
    for row in per_job_rows:
        jid = row.job_id
        bucket = jobs_data.setdefault(jid, {"stages": {}, "total": 0})
        bucket["stages"][row.stage] = bucket["stages"].get(row.stage, 0) + row.cnt
        bucket["total"] += row.cnt
        prev = job_first_seen.get(jid)
        if prev is None or row.first_candidate < prev:
            job_first_seen[jid] = row.first_candidate
    ordered_job_ids = sorted(jobs_data, key=lambda j: (job_first_seen[j], j))

    # Fetch job titles
    job_ids = list(jobs_data.keys())
    job_titles: dict[int, str] = {}
    job_recruiters: dict[int, int | None] = {}
    if job_ids:
        jobs_result = await db.execute(select(Job).where(Job.id.in_(job_ids)))
        for job in jobs_result.scalars().all():
            job_titles[job.id] = job.title
            job_recruiters[job.id] = job.recruiter_id

    # ── Bottleneck detection ──
    bottlenecks = []

    # ── Aging alerts (top 20 wg dni w etapie) ──
    # `days` liczone w SQL identycznie jak `_days_in_stage`: floor po dniach,
    # ucięte do 0. Sortowanie `days DESC, candidate_id, job_id` odtwarza stabilny
    # `sort(key=-days)` na liście, która była już posortowana po parze.
    aging_rows = (
        await db.execute(
            text(
                "WITH cur AS ("
                "  SELECT candidate_id, job_id, stage::text AS stage,"
                "         GREATEST(0, FLOOR("
                "             EXTRACT(EPOCH FROM (now() - moved_at)) / 86400"
                "         ))::int AS days"
                "  FROM analytics_current_pipeline"
                ") "
                "SELECT candidate_id, job_id, stage, days FROM cur "
                "WHERE stage NOT IN ('hired', 'rejected', 'withdrawn') "
                "  AND days > :aging_threshold "
                "ORDER BY days DESC, candidate_id, job_id "
                "LIMIT 20"
            ),
            {"aging_threshold": AGING_THRESHOLD_DAYS},
        )
    ).all()
    aging_alerts = [
        {
            "candidate_id": row.candidate_id,
            "job_id": row.job_id,
            "stage": row.stage,
            "days": row.days,
            "job_title": job_titles.get(row.job_id, "?"),
        }
        for row in aging_rows
    ]

    for jid in ordered_job_ids:
        data = jobs_data[jid]
        for stage_key in ["prep_call", "screening", "cv_sent"]:
            count = data["stages"].get(stage_key, 0)
            if count >= BOTTLENECK_THRESHOLD:
                bottlenecks.append(
                    {
                        "job_id": jid,
                        "job_title": job_titles.get(jid, "?"),
                        "stage": stage_key,
                        "count": count,
                        "message": f"Dużo kandydatów ({count}) czeka na {STAGE_LABELS.get(PipelineStage(stage_key), stage_key)} — potrzebna pomoc!",
                    }
                )

    # ── Workload per recruiter (by moved_by of latest entries) ──
    from app.models.user import User

    # `moved_by IS NULL` → bucket 0 ("Nieprzypisany"), jak w dawnej pętli.
    # Tie-break przy równym `cnt`: pierwsze wystąpienie rekrutera w skanie
    # posortowanym po (candidate_id, job_id) — stąd MIN(candidate_id), MIN(job_id).
    workload_rows = (
        await db.execute(
            text(
                "SELECT COALESCE(moved_by, 0) AS rid, COUNT(*)::int AS cnt, "
                "       MIN(candidate_id) AS first_candidate, "
                "       MIN(job_id) AS first_job "
                "FROM analytics_current_pipeline "
                "WHERE stage::text NOT IN ('hired', 'rejected', 'withdrawn') "
                "GROUP BY COALESCE(moved_by, 0) "
                "ORDER BY cnt DESC, first_candidate, first_job"
            )
        )
    ).all()

    recruiter_ids = [row.rid for row in workload_rows if row.rid > 0]
    recruiter_names: dict[int, str] = {}
    if recruiter_ids:
        users_result = await db.execute(select(User).where(User.id.in_(recruiter_ids)))
        for u in users_result.scalars().all():
            recruiter_names[u.id] = u.name

    workload = [
        {
            "recruiter_id": row.rid,
            "name": recruiter_names.get(row.rid, "Nieprzypisany"),
            "active_candidates": row.cnt,
        }
        for row in workload_rows
    ]

    # ── Opportunity alerts (acceptance/negotiation → help close!) ──
    opportunities = []
    for jid in ordered_job_ids:
        data = jobs_data[jid]
        acceptance_count = data["stages"].get("acceptance", 0) + data["stages"].get(
            "negotiation", 0
        )
        if acceptance_count > 0:
            opportunities.append(
                {
                    "job_id": jid,
                    "job_title": job_titles.get(jid, "?"),
                    "count": acceptance_count,
                    "message": f"{acceptance_count} kandydat(ów) do domknięcia w {job_titles.get(jid, '?')} — manager, pomóż!",
                }
            )

    return {
        "jobs": [
            {
                "job_id": jid,
                "title": job_titles.get(jid, "?"),
                "recruiter_id": job_recruiters.get(jid),
                "stages": jobs_data[jid]["stages"],
                "total": jobs_data[jid]["total"],
            }
            for jid in ordered_job_ids
        ],
        "bottlenecks": bottlenecks,
        "aging_alerts": aging_alerts,  # Top 20 (LIMIT w SQL)
        "opportunities": opportunities,
        "workload": workload,
        "stage_labels": {s.value: STAGE_LABELS[s] for s in PipelineStage},
    }


class ClaimRequest(BaseModel):
    candidate_id: int
    job_id: int


@router.post("/claim")
async def claim_candidate(
    data: ClaimRequest,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    """„Biorę" / „Przejmij" — osoba w „Nowych" na 12 h dla klikającego (0352).

    Wolną osobę (z ogłoszenia, propozycji, po upływie blokady) bierze każdy
    z zespołu rekrutacji. Cudzą, wciąż aktywną blokadę przejmuje wyłącznie
    admin, Delivery Lead albo Head of Recruitment — poprzedni rekruter dostaje
    dzwonek.
    """
    job = await db.scalar(select(Job).where(Job.id == data.job_id))
    if job is None:
        raise HTTPException(status_code=404, detail="Rekrutacja nie istnieje.")
    await ensure_job_membership(db, current_user, job.id)

    # Ta sama kolejność blokad co `/move`: kandydat, potem proces.
    locked = await db.scalar(
        select(Candidate.id).where(Candidate.id == data.candidate_id).with_for_update()
    )
    if locked is None:
        raise HTTPException(status_code=404, detail="Kandydat nie istnieje.")
    process = await db.scalar(
        select(RecruitmentProcess)
        .where(
            RecruitmentProcess.candidate_id == data.candidate_id,
            RecruitmentProcess.job_id == data.job_id,
        )
        .order_by(RecruitmentProcess.attempt_no.desc(), RecruitmentProcess.id.desc())
        .limit(1)
        .with_for_update()
    )
    latest = await db.scalar(
        select(CandidateStage)
        .where(
            CandidateStage.candidate_id == data.candidate_id,
            CandidateStage.job_id == data.job_id,
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        .limit(1)
    )
    if (
        process is None
        or latest is None
        or process.status.value != "open"
        or await candidate_claim.stage_column(db, latest)
        not in candidate_claim.CLAIM_COLUMNS
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Brać można tylko osobę z kolumny „Nowi” albo „Screening” "
                "w otwartym procesie."
            ),
        )

    now = datetime.now(timezone.utc)
    await candidate_claim.assert_can_act(
        db, process=process, user=current_user, now=now
    )
    previous = candidate_claim.claim_state(process)
    previous_holder = (
        previous.user_id
        if previous.active(now) and previous.user_id != current_user.id
        else None
    )
    candidate_claim.set_claim(process, current_user.id, now)
    db.add(
        Activity(
            entity_type="pipeline",
            entity_id=latest.id,
            action="candidate_claimed",
            user_id=current_user.id,
            details={
                "candidate_id": data.candidate_id,
                "job_id": data.job_id,
                "taken_over_from": previous_holder,
                "claimed_until": process.claimed_until.isoformat(),
            },
        )
    )
    if previous_holder is not None:
        from app.services.notification_triggers import emit

        candidate = await db.get(Candidate, data.candidate_id)
        person = (
            f"{candidate.name or ''} {candidate.lastname or ''}".strip()
            if candidate is not None
            else ""
        ) or "Kandydat"
        await emit(
            db,
            user_id=previous_holder,
            title=f"{current_user.name} przejął(a) osobę z „Nowych”",
            message=f"{person} · {job.title}",
            ntype=NotificationType.candidate_claim_taken,
            related_entity_type="recruitment_process",
            related_entity_id=process.id,
            link=f"/jobs/{job.id}?candidate={data.candidate_id}",
        )
    claimed_until = process.claimed_until
    actor_id = current_user.id
    job_id = job.id
    await db.commit()
    await broadcast_pipeline_changed(db, job_id, actor_id)
    return {
        "candidate_id": data.candidate_id,
        "job_id": data.job_id,
        "claim_user_id": actor_id,
        "claim_until": claimed_until,
        "taken_over_from": previous_holder,
    }


class BulkMoveRequest(BaseModel):
    candidate_ids: list[int]
    job_id: int
    stage: PipelineStage
    notes: str | None = None
    # Pipeline v4: jedna stawka do klienta dla całej paczki „CV wysłane"
    # (poza Nordeą wymagana i tylko Delivery Lead / admin).
    client_rate_value: Decimal | None = Field(None, gt=0)
    client_rate_unit: RateUnit | None = None
    client_rate_currency: str | None = Field(None, max_length=3)


@router.post("/bulk-move")
async def bulk_move_candidates(
    data: BulkMoveRequest,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    """Move multiple candidates to a stage at once."""
    if not data.candidate_ids or not data.job_id:
        raise HTTPException(status_code=400, detail="candidate_ids and job_id required")

    # Phase 17 (migracja 0068): bulk-move nie obsługuje rejection_reason_id,
    # więc terminal stages (rejected/withdrawn) zablokowane — wymagają indywidualnego
    # ruchu z powodem. CHECK constraint na DB i tak by to wyłapał, ale clean 422
    # jest dużo lepszy niż IntegrityError.
    if data.stage in (PipelineStage.rejected, PipelineStage.withdrawn):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Bulk-move na stage '{data.stage.value}' niedozwolony — "
                "użyj indywidualnego /move z rejection_reason_id."
            ),
        )

    # M4 PR-02 (audyt P0.4/P0.7/P0.10): bulk nie robi terminal/gate shortcuts.
    # `verified` z bulk omijał gate budżetowy (default verification_status=
    # 'active', zero stawki), `hired` z bulk omijał hook Contract+ClientOrder
    # (baseline PR-00: 499 par hired-bez-kontraktu). FE nie używa bulk-move —
    # 422 z instrukcją zamiast cichej dziury. Nadrzędne wobec wcześniejszych
    # guardów ról z PR-01 (blokada dotyczy wszystkich).
    if data.stage in (PipelineStage.verified, PipelineStage.hired):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Bulk-move na stage '{data.stage.value}' niedozwolony — "
                "wymaga indywidualnego /move (gate stawki / artefakty "
                "zatrudnienia)."
            ),
        )

    # M4 PR-02 (audyt P0.7): limit, dedupe i walidacja wejścia.
    # Canonical command service takes a row lock per candidate.  Stable order
    # prevents two overlapping bulk requests with reversed input order from
    # deadlocking each other.
    unique_ids = canonical_candidate_lock_order(data.candidate_ids)
    if len(unique_ids) > 100:
        raise HTTPException(
            status_code=422,
            detail=f"Bulk-move przyjmuje maksymalnie 100 kandydatów "
            f"(otrzymano {len(unique_ids)} unikalnych).",
        )
    job = await db.scalar(select(Job).where(Job.id == data.job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # P1-PIPE-01: bulk pipeline write — members only (same gate as /move).
    # Runs after the pure-input terminal/gate 422s above (which reveal nothing
    # job-specific) and before any candidate lookup.
    await ensure_job_membership(db, current_user, job.id)

    # Pipeline v4: „CV wysłane" poza Nordeą — DL + stawka (jak pojedynczy /move).
    if pipeline_move_rules.requires_dl_client_rate(data.stage, job.client_id):
        pipeline_move_rules.assert_client_send_allowed(
            current_user, data.client_rate_value
        )
    elif data.client_rate_value is not None and not await resolve_client_rate_write(
        db, current_user, job
    ):
        raise HTTPException(
            status_code=403,
            detail="Stawkę do klienta zapisuje Delivery Lead albo admin.",
        )

    # Etap-odznaka Tablicy (DZ / Cpro) — ta sama reguła co pojedynczy /move.
    bulk_stage_def = await _resolve_stage_def(
        db, job, stage_def_id=None, legacy_stage=data.stage
    )
    if bulk_stage_def is not None:
        ensure_badge_stage_allowed(
            current_user, stage_name=bulk_stage_def.name, client_id=job.client_id
        )

    # Rekrutacja v5 (0361): QC CV przed „CV wysłane” — jak pojedynczy /move.
    # Pierwsza osoba bez QC zatrzymuje całą paczkę (409 z jej `stage_id`).
    for cid in unique_ids:
        await _assert_cv_qc_gate(
            db,
            current_user,
            candidate_id=cid,
            job_id=job.id,
            stage_def=bulk_stage_def,
            legacy_value=data.stage.value,
            client_id=job.client_id,
        )

    # Faza 1 globalnej kolejności blokad: komplet kandydatów rosnąco, ZANIM
    # `transition_process` w pętli niżej weźmie blokadę oferty. Bez tego pętla
    # przeplatała kandydat→oferta→kandydat i zakleszczała się z wsadowym
    # `sync_external_observed_processes` (Traffit), który blokuje wszystkich
    # kandydatów przed jakąkolwiek ofertą. Sam sort tego nie zamykał.
    # Kontrola istnienia jedzie na tym samym zapytaniu — zero dodatkowych rund.
    existing_ids = set(
        (await db.execute(lock_candidates_stmt(unique_ids))).scalars().all()
    )
    missing = [cid for cid in unique_ids if cid not in existing_ids]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Nieistniejący kandydaci: {missing[:20]}",
        )
    # P1-PIPE-01: eligibility gate ── bulk-move only ever targets non-terminal
    # stages (terminal/verified/hired 422 above), so every candidate is a
    # forward move and the hard block applies to all. Fail-closed: any
    # globally blacklisted / hiring-manager-vetoed candidate rejects the batch
    # (409). Client conflicts are warnings since 17.09.2026 and do not stop the
    # batch. Pojedynczy /move ostrzega z potwierdzeniem; bulk zostaje twardym
    # 409 — nie ma UI, które mogłoby potwierdzić ostrzeżenie za paczkę.
    await assert_candidates_move_eligible(
        db,
        candidate_ids=unique_ids,
        job=job,
        now=datetime.now(timezone.utc),
        enforce_manager_verdict=puts_candidate_before_client(data.stage),
    )

    # Pipeline v4: debrief po rozmowie u klienta — jak pojedynczy /move.
    bulk_target_column = board_column_for(None, data.stage.value)
    for cid in unique_ids:
        await pipeline_move_rules.assert_debrief_before_contract(
            db, candidate_id=cid, job_id=data.job_id, target_column=bulk_target_column
        )

    # Pipeline v4: cudza osoba zarezerwowana w „Nowych" blokuje całą paczkę.
    for cid in unique_ids:
        await candidate_claim.assert_can_act(
            db,
            process=await candidate_claim.load_process(
                db, candidate_id=cid, job_id=data.job_id
            ),
            user=current_user,
        )

    bulk_rate: dict = {}
    if data.client_rate_value is not None:
        bulk_rate = {
            "client_rate_value": data.client_rate_value,
            "client_rate_unit": (data.client_rate_unit or RateUnit.hourly).value,
            "client_rate_currency": (data.client_rate_currency or "PLN")[:3].upper(),
        }
    moved = 0
    for cid in unique_ids:
        entry = await transition_process(
            db,
            candidate_id=cid,
            job_id=data.job_id,
            stage=data.stage,
            moved_at=datetime.now(timezone.utc),
            actor_user_id=current_user.id,
            work_channel=PriorityChannel.database,
            notes=data.notes,
            **bulk_rate,
        )
        await create_original_cv_snapshot(db, entry)
        await maybe_ensure_contact_opportunity(
            db,
            candidate_id=cid,
            job_id=data.job_id,
            source="pipeline",
            occurred_at=entry.moved_at,
        )
        moved += 1

    # 0341: przepięcia do połączonych rekrutacji (jak w pojedynczym /move).
    from app.services.job_similarity import on_candidate_sent  # noqa: PLC0415

    bulk_stage = data.stage
    for cid in unique_ids:
        await on_candidate_sent(
            db, job_id=data.job_id, candidate_id=cid, stage=bulk_stage
        )
    from app.services.request_work_state import (  # noqa: PLC0415
        wake_on_client_response,
    )

    await wake_on_client_response(
        db, job_id=data.job_id, stage=bulk_stage, reason="client_stage"
    )

    actor_id = current_user.id
    await db.commit()
    await broadcast_pipeline_changed(db, data.job_id, actor_id)

    # Phase 17 (migracja 0068): recompute risk dla każdego kandydata.
    # Best-effort — pojedynczy fail nie blokuje response ani nie zostawia
    # sesji w failed transaction (M4 PR-02).
    from app.services.candidate_risk import on_candidate_stage_change

    try:
        for cid in unique_ids:
            await on_candidate_stage_change(db, cid)
        await db.commit()
    except Exception as _exc:  # noqa: BLE001
        logger.warning("bulk risk recompute failed: %s", _exc)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass

    # Auto-add to a talent pool when the bulk move is "CV → klient" (same
    # signal as the single /move path). Best-effort: a failure must not affect
    # the move that already committed above.
    if data.stage == PipelineStage.cv_sent:
        import logging as _logging

        from app.services.talent_pool_auto_add import auto_add_on_cv_sent

        pool_job = await db.scalar(select(Job).where(Job.id == data.job_id))
        if pool_job is not None:
            for cid in unique_ids:
                try:
                    pool_candidate = await db.scalar(
                        select(Candidate).where(Candidate.id == cid)
                    )
                    await auto_add_on_cv_sent(
                        db=db,
                        candidate_id=cid,
                        job=pool_job,
                        user_id=current_user.id,
                        candidate=pool_candidate,
                    )
                except Exception as e:  # noqa: BLE001
                    await db.rollback()
                    _logging.getLogger(__name__).warning(
                        "bulk auto_add_on_cv_sent failed candidate=%s job=%s: %s",
                        cid,
                        data.job_id,
                        e,
                    )
            await db.commit()

    return {"moved": moved, "stage": data.stage.value, "job_id": data.job_id}
