import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal
from types import SimpleNamespace
from pydantic import BaseModel, Field
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from typing import TYPE_CHECKING, Annotated, Any, List, Literal, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import exists, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.tasks import spawn
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
from app.models.note import Note
from app.models.notification import Notification, NotificationType
from app.services import board_tasks as board_tasks_svc
from app.services import candidate_audit, candidate_claim, pipeline_move_rules
from app.services.client_off_limits import off_limits_badge
from app.services.process_entry_meta import (
    application_link_owner_id,
    application_screening_badge,
    auto_match_badge,
    autofill_badge,
)
from app.models.contract import ContractType, RateUnit
from app.services.board_stage_badges import (
    BOARD_COLUMN_ORDER,
    _NAME_ONLY_KINDS as NAME_ONLY_STAGE_KINDS,
    board_column_for,
    cpro_enabled_for_client,
    ensure_badge_stage_allowed,
    foreign_stage_target,
    is_cpro_stage,
    is_entry_column,
    stage_badge_kind,
)
from app.services import (
    champion_view,
    move_requirements,
    rejection_reason_labels,
    screening_fix_requests,
    stage_handoff_recipients,
    stage_remarks,
)
from app.services.candidate_added_date import added_to_base
from app.services.candidate_stage_cv_service import (
    create_original_cv_snapshot,
)
from app.services.candidate_contact_hooks import (
    load_contact_case_summaries,
    maybe_close_contact_opportunity,
    maybe_ensure_contact_opportunity,
)
from app.services.b2b_contract_automation import (
    ORDER_SKIPPED_OPEN_GROUP_LINE,
    ensure_b2b_employment_draft,
)
from app.models.job import Job, JobStatus
from app.models.pipeline_template import (
    PipelineStageDef,
    PipelineTemplate,
    RejectionReason,
    TerminalType,
)
from app.models.user import User, UserRole
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
    client_rate_write_denied,
    resolve_client_rate_write,
    user_can_access_candidate_domain,
    user_can_view_client_rate,
    user_has_candidate_read,
)
from app.api.deps import CurrentUser, OperationalUser, RecruiterPlus
from app.api.recruitment_access import (
    ensure_job_read_access,
    ensure_job_membership,
    job_read_scope_clause,
    job_scope_clause,
    user_can_edit_rates,
)
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.services.hiring_manager_verdicts import puts_column_before_client
from app.services.pipeline_eligibility import (
    assert_candidate_move_eligible,
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
from app.services.recruitment_move_policy import (
    MoveTarget,
    RecruitmentMovePolicy,
    UserMovePolicy,
)
from app.services.delivery_alert_recipients import load_delivery_alert_recipient_scope
from app.services.pipeline_realtime import broadcast_pipeline_changed
from app.services.stage_verifier import first_verifier
from app.core.scheduling import DEFAULT_TZ, business_today
from app.services.consultant_elsewhere_notifications import (
    employed_elsewhere_client_ids,
)
from app.services.employment_marker import load_employment_markers
from app.services.candidate_rate_from import (
    effective_currency_sql,
    effective_rate_sql,
)

if TYPE_CHECKING:  # pragma: no cover
    from app.api.proposals_bulk import ProposeResult

# PostgreSQL int4 upper bound — path parameters bound to int4 columns must not
# exceed this value or asyncpg's int4_encode will raise OverflowError.
_PG_INT4_MAX = 2_147_483_647
DbIdPath = Annotated[int, Path(ge=1, le=_PG_INT4_MAX)]

# Karty, które niosą powód zamknięcia i osobę zamykającą (19.10.2026).
_CLOSED_CARD_STAGES = frozenset({PipelineStage.rejected, PipelineStage.withdrawn})

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


def _spawn(coro, label: str) -> None:
    # Wspólny `app.core.tasks.spawn`: trzymana referencja (goły `create_task`
    # gubi zadanie pod GC) i log porażki — powiadomienie Teams padłe w zadaniu
    # nie ma czytelnika. Nazwa `_spawn` zostaje: testy ją podmieniają.
    spawn(coro, f"pipeline:{label}")


async def _post_commit_effect(
    db: AsyncSession, label: str, effect: Callable[[], Awaitable[None]]
) -> bool:
    """Efekt uboczny po zatwierdzonym ruchu — nigdy nie rzuca i nie wygasza sesji.

    ``True`` = zapisy efektu są zatwierdzone (mail o nich może już wyjść).

    Efekt biegnie w savepoincie: błąd cofa wyłącznie jego zapisy, a obiekty
    załadowane w sesji żądania (``current_user``, ``stage``, ``job``) zostają
    ważne — `db.rollback()` na całej sesji wygaszał je i kolejny odczyt
    atrybutu kończył się MissingGreenlet (500 po zapisanym ruchu, audyt
    25.09.2026). Commit dopiero po udanym efekcie; nieudany commit cofa sesję
    (wtedy nie ma już czego chronić — odpowiedź jest policzona wcześniej).
    """

    try:
        async with db.begin_nested():
            await effect()
    except Exception as exc:  # noqa: BLE001 — efekt uboczny nie psuje ruchu
        # Klasa wyjątku, nie treść: IntegrityError niesie `DETAIL: Key (...)=(...)`
        # z danymi wiersza, których `hide_parameters` nie ukrywa (runda 7, R7-X2-9).
        logger.warning("%s failed (%s)", label, type(exc).__name__)
        return False
    try:
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("%s commit failed (%s)", label, type(exc).__name__)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return False
    return True


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
    # Runda 9 (R9-N11-8): kilka etapów szablonu bywa z tym samym kodem
    # („QC CV” ma kod `interview`, obok zwykłej rozmowy), a `scalar` bez
    # ORDER BY brał dowolny. Pierwszy w kolejności szablonu, z pominięciem
    # etapów rozpoznawanych po NAZWIE (QC, Cpro) — jak `foreign_stage_target`.
    candidates = (
        await db.scalars(
            select(PipelineStageDef)
            .where(
                PipelineStageDef.template_id == template_id,
                PipelineStageDef.legacy_enum_value == legacy_stage.value,
            )
            .order_by(PipelineStageDef.order.asc(), PipelineStageDef.id.asc())
        )
    ).all()
    for sd in candidates:
        if stage_badge_kind(sd.name) not in NAME_ONLY_STAGE_KINDS:
            return sd
    return candidates[0] if candidates else None


async def _pair_has_no_stage(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> bool:
    """Para (kandydat, rekrutacja) nie ma jeszcze żadnego wiersza etapu."""
    return not await db.scalar(
        select(
            exists().where(
                CandidateStage.candidate_id == candidate_id,
                CandidateStage.job_id == job_id,
            )
        )
    )


FRESH_PAIR_ENTRY_ONLY = (
    "Tej osoby nie ma jeszcze w rekrutacji — dodaje się ją do „Nowych” albo "
    "„Screeningu”, a dalej prowadzi zwykłym ruchem."
)


def _fresh_pair_entry_kwargs(user: User, request: Optional[Request]) -> dict:
    """Źródło wejścia i blokada nowego procesu dodanego ruchem ``/move``.

    Lustro ``proposals_bulk``: człowiek dostaje ``added_manual`` + 12 h
    blokady, integracja (token OAuth) — ``auto_match`` bez blokady.
    """
    if candidate_claim.is_integration_request(request):
        return {"entry_source": candidate_claim.ENTRY_AUTO_MATCH}
    return {
        "entry_source": candidate_claim.ENTRY_ADDED_MANUAL,
        "claim_for_user_id": user.id,
    }


INTEGRATION_PROPOSED = (
    "Osoba czeka w „Do przejrzenia” tej rekrutacji — integracja dodaje na "
    "Tablicę tylko osoby, które zgłosiły się do tej rekrutacji."
)


async def _integration_fresh_pair_proposal(
    db: AsyncSession, request: Optional[Request], *, job: Job, candidate_id: int
) -> Optional["ProposeResult"]:
    """Integracja dodaje NOWĄ osobę ruchem ``/move`` → propozycja (06.10.2026).

    Bez dowodu zgłoszenia do tej rekrutacji (``integration_intake``) karta nie
    powstaje; osoba trafia do „Do przejrzenia” jako propozycja ``job_board``.
    Bez commita: trasa zatwierdza i odpowiada 202
    (``_integration_proposed_response`` — nie kształt etapu, etapu nie ma).
    ``None`` = dodaj jak dotąd (człowiek albo osoba ze zgłoszeniem).
    """
    if not candidate_claim.is_integration_request(request):
        return None
    from app.api.proposals_bulk import propose_candidates_for_job
    from app.services.integration_intake import candidates_with_application_evidence

    applied = await candidates_with_application_evidence(
        db, job_id=job.id, candidate_ids=[candidate_id]
    )
    if candidate_id in applied:
        return None
    return await propose_candidates_for_job(
        db, job=job, candidate_ids=[candidate_id], entry_meta=None
    )


def _integration_proposed_response(outcome: "MoveProposed") -> JSONResponse:
    """Odpowiedź 202 ``/move`` po propozycji zamiast karty (po commicie)."""
    proposal = outcome.proposal
    return JSONResponse(
        status_code=202,
        content={
            "status": "proposed" if proposal.proposed else "skipped",
            "candidate_id": outcome.candidate_id,
            "job_id": outcome.job_id,
            "proposed": proposal.proposed,
            "detail": INTEGRATION_PROPOSED,
        },
    )


def _assert_fresh_pair_entry(
    stage_def: Optional[PipelineStageDef], legacy: Optional[PipelineStage]
) -> None:
    """422, gdy osoba spoza rekrutacji ma wejść dalej niż „Nowi”/„Screening”."""
    if not is_entry_column(
        stage_def.name if stage_def else None,
        (stage_def.legacy_enum_value if stage_def else None)
        or (legacy.value if legacy is not None else None),
        category=(
            stage_def.category.value if stage_def and stage_def.category else None
        ),
        terminal_type=(
            stage_def.terminal_type.value
            if stage_def and stage_def.terminal_type
            else None
        ),
    ):
        raise HTTPException(status_code=422, detail=FRESH_PAIR_ENTRY_ONLY)


# Kod etapu, którym haki „osoba u klienta” (przepięcia, „Klient milczy”)
# rozpoznają kolumnę Tablicy — lustro `_COLUMN_BY_ENUM` w odwrotną stronę.
_CLIENT_COLUMN_HOOK_STAGE: dict[str, PipelineStage] = {
    "cv_sent": PipelineStage.cv_sent,
    "client_interview": PipelineStage.client_interview,
    "contract": PipelineStage.acceptance,
}


def _client_hook_stage(column: str, legacy: PipelineStage) -> PipelineStage:
    """Kod etapu dla haków po ruchu, liczony z kolumny docelowej.

    Własny kod zostaje, gdy leży w tej samej kolumnie (`negotiation` to
    „Umowa”); etap rozpoznany po nazwie dostaje kod swojej kolumny.
    """
    mapped = _CLIENT_COLUMN_HOOK_STAGE.get(column)
    if mapped is None:
        return legacy
    if board_column_for(None, legacy.value) == column:
        return legacy
    return mapped


def _record_stage_change(
    db: AsyncSession,
    *,
    stage: CandidateStage,
    stage_def: Optional[PipelineStageDef],
    legacy_enum: PipelineStage,
    actor_id: Optional[int],
    stage_display_name: str,
    extra_details: Optional[dict] = None,
) -> None:
    """Ślad ruchu: `Activity stage_changed` + `UserActivity` (ranking osób).

    Wspólny dla `/move` i `/bulk-move` — do rundy 9 (R9-N11-7) ruch zbiorczy
    nie zostawiał żadnego z nich, więc historia karty i liczniki osoby
    gubiły przesunięcia zrobione paczką.

    ``actor_id=None`` = ruch konta serwisowego (API v1): zostaje `Activity`
    (autora mówi ``details.via`` ze stempla sesji klucza), a `UserActivity`
    nie powstaje — to ranking ludzi, a ``user_activities.user_id`` jest NOT NULL.
    """
    details: dict = {
        "candidate_id": stage.candidate_id,
        "job_id": stage.job_id,
        "stage": legacy_enum.value,
        "stage_def_id": stage_def.id if stage_def else None,
        "stage_name": stage_display_name,
    }
    if extra_details:
        details.update(extra_details)
    db.add(
        Activity(
            entity_type="pipeline",
            entity_id=stage.id,
            action="stage_changed",
            user_id=actor_id,
            details=details,
        )
    )
    if actor_id is None:
        return
    db.add(
        UserActivity(
            user_id=actor_id,
            action_type=UserActionType.stage_changed,
            entity_type="pipeline",
            entity_id=stage.id,
            details={
                "candidate_id": stage.candidate_id,
                "job_id": stage.job_id,
                "stage": legacy_enum.value,
                "stage_def_id": stage_def.id if stage_def else None,
            },
        )
    )


async def _cancel_pending_rejection_emails(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    actor_id: Optional[int],
    restored_to: PipelineStage,
) -> None:
    """Ruch na etap nieterminalny anuluje niewysłane maile odrzucenia pary.

    W TEJ SAMEJ transakcji co ruch (M4 PR-02, audyt P1.7). Wiersz, którego
    wysyłka już ruszyła, zostaje — rozstrzyga go pętla wysyłki (runda 9).
    """
    from app.models.rejection_email import RejectionEmailStatus
    from app.services.rejection_email_scheduler import (
        pending_rows_covering,
        send_in_progress,
    )

    # Wspólny mail (D3, 17.10.2026) mówi też o tej rekrutacji — osoba, która
    # do niej wraca, nie może dostać maila, że w niej „nie przechodzi dalej”.
    pending_mails = await pending_rows_covering(
        db, candidate_id=candidate_id, job_id=job_id
    )
    for mail_row in pending_mails:
        if send_in_progress(mail_row):
            continue
        mail_row.status = RejectionEmailStatus.cancelled
        mail_row.cancelled_at = datetime.now(timezone.utc)
        mail_row.cancelled_by = actor_id
        db.add(
            Activity(
                entity_type="candidate",
                entity_id=candidate_id,
                action="rejection_email_cancelled_on_restore",
                user_id=actor_id,
                details={
                    "scheduled_rejection_email_id": mail_row.id,
                    "job_id": job_id,
                    "restored_to_stage": restored_to.value,
                },
            )
        )


def _spawn_cv_qc_after_move(
    target_column: str, stage_id: int, actor_id: Optional[int]
) -> None:
    """QC CV liczy się samo po wejściu do kolumny „QC CV” (Rekrutacja v5).

    Ten sam wyłącznik co bramka (w testach wyłączony autouse-fixturą). QC,
    które nie przeszło i którego nikt nie przepuścił, dzwoni do rekrutera
    kandydata („QC CV do poprawy”, 14.10.2026) — tylko z tej ścieżki, nie po
    podpięciu CV.
    """
    if target_column != "cv_qc":
        return
    try:
        from app.core.config import settings as _settings
        from app.services import cv_qc as _cv_qc

        if _settings.CV_QC_GATE_ENABLED:
            _spawn(
                _cv_qc.run_after_move(
                    stage_id, actor_id, notify_recruiter_on_fail=True
                ),
                f"cv_qc stage={stage_id}",
            )
    except Exception as _exc:  # noqa: BLE001 — automat nigdy nie psuje ruchu
        logger.warning(
            "cv_qc spawn failed stage=%s (%s)", stage_id, type(_exc).__name__
        )


def _notify_stage_change_effect(
    db: AsyncSession,
    *,
    stage: CandidateStage,
    previous_stage_row: Optional[CandidateStage],
    job: Job,
    mover: User,
    stage_display_name: str,
    hired_engagement: Optional[str] = None,
) -> Callable[[], Awaitable[None]]:
    """Powiadomienia o przejściu (reguły 0066) — efekt po commicie ruchu."""

    async def _effect() -> None:
        from app.services.stage_notification_emitter import notify_stage_change

        candidate_obj = await db.scalar(
            select(Candidate).where(Candidate.id == stage.candidate_id)
        )
        if candidate_obj is not None:
            await notify_stage_change(
                db,
                new_stage=stage,
                previous_stage=previous_stage_row,
                job=job,
                candidate=candidate_obj,
                mover=mover,
                stage_display_name=stage_display_name,
                hired_engagement=hired_engagement,
            )

    return _effect


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


# Typ kontraktu zakładanego przy ręcznym „Zatrudniony” (D2, 04.10.2026):
# do tego dnia każdy szkic był B2B, także przy umowie o pracę i zleceniu.
_HIRED_CONTRACT_TYPE = {
    "uop": ContractType.uop,
    "zlecenie": ContractType.uzlecenie,
}


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


async def _assert_client_rate_not_order_locked(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> None:
    """Kwota do klienta w ruchu karty = ta sama blokada co ``PATCH …/client-rate``.

    Po zamówieniu pary stawkę zmienia się w zamówieniu (decyzja Artura
    20.10.2026) — powrót na „CV wysłane” z nową kwotą nie może jej obejść.
    """

    from app.services import client_rate_correction  # noqa: PLC0415

    lock = await client_rate_correction.order_lock(
        db, candidate_id=candidate_id, job_id=job_id
    )
    if lock is not None:
        raise HTTPException(
            status_code=409, detail=client_rate_correction.order_lock_message(lock)
        )


async def _record_rate_from_move(
    db: AsyncSession,
    *,
    candidate_id: int,
    value: Decimal,
    unit: Optional[str],
    currency: Optional[str],
    is_minimum: bool,
    actor_id: int,
) -> None:
    """Stawka z okna „Zweryfikowany” w „Stawce od” (0414).

    Zaznaczone „To jego nowe minimum” zapisuje ją też w profilu jako jawne
    minimum (audyt ``rate_meaning: minimum``). Potem przeliczenie — nigdy nie
    cofa samego ruchu (``recompute_safely``).
    """
    from app.services.candidate_profile_rate import write_profile_rate
    from app.services.candidate_rate_from import recompute_safely
    from app.services.candidate_rate_observations import hourly_from_unit

    if is_minimum:
        hourly = hourly_from_unit(value, unit, currency)
        candidate = await db.scalar(
            select(Candidate).where(Candidate.id == candidate_id).with_for_update()
        )
        if hourly is not None and candidate is not None:
            details = write_profile_rate(candidate, hourly, source="stage_minimum")
            details["rate_meaning"] = "minimum"
            candidate_audit.record_candidate_audit(
                db,
                action=candidate_audit.PROFILE_RATE_CHANGED,
                user_id=actor_id,
                entity_id=candidate_id,
                details=details,
            )
            await db.flush()
    await recompute_safely(db, [candidate_id])


def _rate_rejection_note(
    amount: Decimal, *, is_minimum: bool, notes: Optional[str]
) -> str:
    """„Chce min. 150 zł/h — opis rekrutera” do historii procesu (26.10.2026).

    Profil pokazuje odrzucenie jako „Powód — opis”, więc kwota stoi w opisie
    także wtedy, gdy rekruter nic nie dopisał.
    """
    text = f"{amount:.2f}".rstrip("0").rstrip(".").replace(".", ",")
    line = f"Chce {'min. ' if is_minimum else ''}{text} zł/h"
    rest = (notes or "").strip()
    return f"{line} — {rest}" if rest else line


async def _record_rejection_rate(
    db: AsyncSession,
    *,
    candidate_id: int,
    amount: Decimal,
    is_minimum: bool,
    job_id: int,
    stage_id: int,
    actor_id: int,
) -> None:
    """Nowa stawka z odrzucenia „za drogo” w profilu i „Stawce od” (26.10.2026).

    Ta sama ścieżka co stawka z okna „Zweryfikowany” (``_record_rate_from_move``),
    ale kwota trafia do profilu zawsze: jako jawne minimum (domyślnie, starsze
    niższe stawki przestają się liczyć) albo jako zwykła stawka w historii.
    Rekrutacja i etap w audycie mówią, skąd przyszła.
    """
    from app.services.candidate_profile_rate import write_profile_rate
    from app.services.candidate_rate_from import recompute_safely
    from app.services.match_score_cache import mark_stale_for_candidate

    candidate = await db.scalar(
        select(Candidate).where(Candidate.id == candidate_id).with_for_update()
    )
    if candidate is None:
        return
    details = write_profile_rate(
        candidate,
        amount,
        source="rejection_minimum" if is_minimum else "rejection",
    )
    if is_minimum:
        details["rate_meaning"] = "minimum"
    details["job_id"] = job_id
    details["stage_id"] = stage_id
    candidate_audit.record_candidate_audit(
        db,
        action=candidate_audit.PROFILE_RATE_CHANGED,
        user_id=actor_id,
        entity_id=candidate_id,
        details=details,
    )
    await mark_stale_for_candidate(db, candidate_id)
    await db.flush()
    await recompute_safely(db, [candidate_id])


async def _record_work_mode_from_rejection(
    db: AsyncSession,
    *,
    candidate_id: int,
    job: Job,
    stage: CandidateStage,
    max_onsite_days: int,
    user: User,
) -> None:
    """Odrzucenie „Nie akceptuje trybu pracy” zapisuje tryb pracy na profilu.

    Ta sama ścieżka co ołówek „Tryb pracy” na profilu (audyt
    ``candidate_work_mode_changed``, odświeżenie wyników dopasowań), tylko ze
    źródłem — rekrutacja i etap, z którego przyszła deklaracja.
    """
    from app.services.candidate_notes_facts import set_work_mode_from_rejection
    from app.services.match_score_cache import mark_stale_for_candidate

    candidate = await db.scalar(
        select(Candidate).where(Candidate.id == candidate_id).with_for_update()
    )
    if candidate is None:
        return
    job_title = job.working_title or job.title
    change = set_work_mode_from_rejection(
        candidate,
        max_onsite_days=max_onsite_days,
        job_id=job.id,
        job_title=job_title,
        stage_id=stage.id,
        user_id=user.id,
        user_name=user.name,
        at_iso=stage.moved_at.isoformat(),
    )
    candidate_audit.record_candidate_audit(
        db,
        action=candidate_audit.WORK_MODE_CHANGED,
        user_id=user.id,
        entity_id=candidate_id,
        details={
            **change,
            "source": "rejection",
            "job_id": job.id,
            "stage_id": stage.id,
        },
    )
    await mark_stale_for_candidate(db, candidate_id)


def _stage_response(
    stage: CandidateStage,
    *,
    candidate_name: Optional[str] = None,
    candidate_lastname: Optional[str] = None,
    added_to_job_by_name: Optional[str] = None,
    added_to_job_by_id: Optional[int] = None,
    added_to_job_at: Optional[datetime] = None,
    verified_by_name: Optional[str] = None,
    verified_by_id: Optional[int] = None,
    verified_at: Optional[datetime] = None,
    candidate_expected_rate_hourly: Optional[Decimal] = None,
    # Bez wartości domyślnej: każdy wołający decyduje jawnie
    # (`user_can_view_client_rate`) — zapomniany argument nie może odsłonić
    # stawki do klienta rekruterowi.
    show_client_rate: bool,
) -> dict:
    """Convert a CandidateStage to response dict with days_in_stage.

    Candidate name/lastname are optional — populated by the Kanban endpoint
    so the frontend can render card titles without an extra round-trip.

    ``added_to_job_by_name`` / ``added_to_job_by_id`` / ``added_to_job_at``
    describe WHO assigned the candidate to the recruitment and WHEN — i.e. the
    mover on the *earliest* stage of this candidate/job pair, not the
    current-stage mover. Also populated by the Kanban endpoint (NULL elsewhere).

    ``verified_by_name`` / ``verified_by_id`` / ``verified_at`` — the FIRST
    verifier of the pair (``stage_verifier.first_verifier``, the same rule as
    the recruiter bonus and the DL review). Kanban only.
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
        # Filtr „Kto dodał” na Tablicy (14.10.2026) porównuje po numerze —
        # po imieniu myliłby imienników.
        "added_to_job_by_id": added_to_job_by_id,
        "added_to_job_at": added_to_job_at,
        # Karta od „Zweryfikowanego” pokazuje osobę, która zweryfikowała, nie
        # tę, która dodała (decyzja Artura 20.10.2026).
        "verified_by_name": verified_by_name,
        "verified_by_id": verified_by_id,
        "verified_at": verified_at,
        # Odznaki karty (17.09.2026) — patrz `CandidateStageResponse`.
        # Arkusz z odpowiedzią — jak bramka „Zweryfikowany” (14.10.2026).
        "screening_done": move_requirements.sheet_answered(stage.screening_answers),
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


async def _link_reapplications(
    db: AsyncSession, *, job_id: int, candidate_ids: Iterable[int]
) -> list[tuple[int, int, datetime]]:
    """Zgłoszenia z linków do tej rekrutacji: ``(kandydat, właściciel linku, kiedy)``.

    Etap 2 linków (19.10.2026), plakietka „Zgłosił się też z Twojego linku”.
    Dwa źródła, jedno zapytanie dla całej tablicy: zgłoszenie dołączone do
    osoby (``application_submissions`` → właściciel linku po skrócie tokenu)
    i przegląd AI, który zastał osobę w rekrutacji (``application_screenings``
    ``already_in_job``). Które z nich są PONOWNE (po otwarciu karty), wybiera
    wołający — zgłoszenie, które kartę otworzyło, jest od niej starsze albo
    z tej samej transakcji.
    """
    from sqlalchemy import Integer, cast, union_all

    from app.models.application_screening import ApplicationScreening
    from app.models.application_submission import (
        ApplicationSubmission,
        ApplicationSubmissionStatus,
    )
    from app.models.invite_link import CandidateInviteLink

    ids = sorted(set(candidate_ids))
    if not ids:
        return []
    submissions = (
        select(
            ApplicationSubmission.matched_candidate_id.label("candidate_id"),
            CandidateInviteLink.created_by.label("owner_id"),
            ApplicationSubmission.created_at.label("at"),
        )
        .join(
            CandidateInviteLink,
            CandidateInviteLink.token_sha256
            == ApplicationSubmission.invite_link_token_sha256,
        )
        .where(
            ApplicationSubmission.job_id == job_id,
            ApplicationSubmission.matched_candidate_id.in_(ids),
            ApplicationSubmission.status.in_(
                (
                    ApplicationSubmissionStatus.linked.value,
                    ApplicationSubmissionStatus.merged.value,
                )
            ),
        )
    )
    owner_in_context = ApplicationScreening.context["link_owner_id"].astext
    screenings = select(
        ApplicationScreening.candidate_id.label("candidate_id"),
        cast(owner_in_context, Integer).label("owner_id"),
        ApplicationScreening.created_at.label("at"),
    ).where(
        ApplicationScreening.job_id == job_id,
        ApplicationScreening.candidate_id.in_(ids),
        ApplicationScreening.outcome == "already_in_job",
        owner_in_context.op("~")(r"^\d+$"),
    )
    rows = await db.execute(union_all(submissions, screenings))
    return [
        (cid, owner, at)
        for cid, owner, at in rows.all()
        if cid is not None and owner is not None and at is not None
    ]


def _reapplied_link_owners(
    reapplications: Iterable[tuple[int, int, datetime]],
    processes: Mapping[int, RecruitmentProcess],
    link_owner_by_candidate: Mapping[int, int],
) -> dict[int, list[int]]:
    """Właściciele linków, z których osoba zgłosiła się PO otwarciu karty.

    Bez właściciela linku, który kartę przyprowadził (to mówi plakietka
    „Z Twojego linku”), kolejność = pierwsze ponowne zgłoszenie.
    """
    earliest: dict[int, dict[int, datetime]] = {}
    for cid, owner, at in reapplications:
        process = processes.get(cid)
        opened = (process.opened_at or process.created_at) if process else None
        if opened is None or at <= opened:
            continue
        if owner == link_owner_by_candidate.get(cid):
            continue
        seen = earliest.setdefault(cid, {})
        if owner not in seen or at < seen[owner]:
            seen[owner] = at
    return {
        cid: sorted(owners, key=lambda o: (owners[o], o))
        for cid, owners in earliest.items()
    }


def _merge_skip_traces(
    rows: Iterable[tuple[int, Optional[dict], Optional[int], Optional[datetime]]],
    since: Mapping[int, Optional[datetime]],
) -> dict[int, tuple[list[str], Optional[int]]]:
    """Suma braków ze śladów pary (od najstarszego) i autor najnowszego.

    Kolejny ruch mimo braków (np. przeskok debriefu) nie chowa braków
    z wejścia na „Zweryfikowany”; ślad sprzed bieżącej próby (``since``
    = początek próby, gdy osoba wróciła do rekrutacji) się nie liczy.
    """
    found: dict[int, tuple[list[str], Optional[int]]] = {}
    for cid, details, user_id, moved_at in rows:
        start = since.get(cid)
        if start is not None and moved_at is not None and moved_at < start:
            continue
        keys = found[cid][0] if cid in found else []
        for key in (details or {}).get("missing") or []:
            if str(key) not in keys:
                keys.append(str(key))
        found[cid] = (keys, user_id)
    return found


async def _requirements_skipped(
    db: AsyncSession,
    *,
    job_id: int,
    candidate_ids: Iterable[int],
    since: Optional[Mapping[int, Optional[datetime]]] = None,
) -> dict[int, tuple[list[str], Optional[int]]]:
    """Ruchy mimo braków każdej pary: ``(braki, kto)`` — 22.10.2026.

    Ślad zapisuje ``/move``, gdy Delivery Lead przeszedł bramki pól
    (``pipeline_move_rules.skips_fill_gates``); jedno zapytanie na tablicę
    przez wiersze etapów rekrutacji (``Activity.entity_id`` = wiersz).
    Braki z bieżącej próby sumują się (:func:`_merge_skip_traces`).
    """
    ids = sorted(set(candidate_ids))
    if not ids:
        return {}
    rows = await db.execute(
        select(
            CandidateStage.candidate_id,
            Activity.details,
            Activity.user_id,
            CandidateStage.moved_at,
        )
        .join(
            Activity,
            (Activity.entity_type == "pipeline")
            & (Activity.entity_id == CandidateStage.id),
        )
        .where(
            CandidateStage.job_id == job_id,
            CandidateStage.candidate_id.in_(ids),
            Activity.action == pipeline_move_rules.REQUIREMENTS_SKIPPED_ACTION,
        )
        .order_by(CandidateStage.candidate_id, Activity.id)
    )
    return _merge_skip_traces(rows.all(), since or {})


def _still_missing(keys: list[str], payload: dict) -> list[str]:
    """Braki ze śladu ``requirements_skipped``, których karta dalej nie ma.

    Arkusz i „Dlaczego” — ``screening_done``; stawka — stawka etapu albo
    z profilu; pola karty — ``minimum_missing``. Debrief zostaje, dopóki
    jest w śladzie (karta nie zna jego stanu).
    """
    minimum = set(payload.get("minimum_missing") or ())
    has_rate = (
        payload.get("expected_rate_value") is not None
        or payload.get("candidate_expected_rate_hourly") is not None
    )
    out: list[str] = []
    for key in keys:
        if key in ("screening_sheet", "why_candidate"):
            if payload.get("screening_done") is False:
                out.append(key)
        elif key == "candidate_rate":
            if not has_rate:
                out.append(key)
        elif key == "debrief" or key in minimum:
            out.append(key)
    return out


# Krótkie nazwy braków w dzwonku — etykiety komunikatu 409 mają cudzysłowy
# i dopiski („ta rekrutacja nie ma pytań…”), które w dzwonku nie pasują.
_SKIP_BELL_LABELS = {
    "screening_sheet": "arkusz screeningu",
    "why_candidate": "Dlaczego ten kandydat",
    "candidate_rate": "stawka kandydata",
    "debrief": "debrief",
}


async def _notify_recruiter_of_skip(
    db: AsyncSession,
    *,
    job: Job,
    candidate_id: int,
    mover: Optional[User],
    stage_name: str,
    missing: list[str],
) -> None:
    """Dzwonek do prowadzącego rekrutację: Delivery Lead przesunął osobę mimo
    braków (22.10.2026) — rekruter wie, że osobę prowadzi już ktoś inny.

    Każde przejście przez „Zweryfikowany” od lewej — ruch na „Zweryfikowany”
    albo przeskok dalej, np. na „QC CV” (DL przejmuje proces; audyt
    22.10.2026, F58); sam przeskok debriefu nikogo nie powiadamia. ``emit`` sprawdza odbiorcę i dzienny duplikat.
    """
    from app.services.notification_triggers import emit  # noqa: PLC0415

    if mover is None or job.recruiter_id is None or job.recruiter_id == mover.id:
        return
    candidate = await db.get(Candidate, candidate_id)
    person = (
        f"{candidate.name or ''} {candidate.lastname or ''}".strip()
        if candidate is not None
        else ""
    ) or "Kandydat"
    labels = ", ".join(
        _SKIP_BELL_LABELS.get(key) or move_requirements.card_field_label(key)
        for key in missing
    )
    await emit(
        db,
        user_id=job.recruiter_id,
        title=f"{mover.name} przesunął(-ęła) {person} na „{stage_name}”",
        message=f"{job.title} · bez: {labels}",
        ntype=NotificationType.stage_changed,
        related_entity_type="candidate",
        related_entity_id=candidate_id,
        link=f"/jobs/{job.id}?candidate={candidate_id}",
    )


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
    # Para w „Zamkniętych" liczy się kolumną sprzed zamknięcia — inaczej
    # „Nowi → Odrzucony → CV wysłane" omijało QC i osobę od Cpro.
    # Para bez wierszy liczy się od „Nowych” (`current` = None) — świeży
    # kandydat wysłany przez API wprost na „CV wysłane” nie omija bramki.
    current, current_column = await pipeline_move_rules.gate_stage_row(
        db, candidate_id=candidate_id, job_id=job_id
    )
    if not cv_qc.gate_applies(current_column, target_column, target_is_cpro):
        return
    # U Nordei „CV wysłane" = „Wysłane do Cpro": wrzuca osoba od Cpro
    # wyznaczona dla całej firmy (albo admin / DL / HoR). Rekruter po QC
    # przekazuje kartę Delivery Leadowi, który akceptuje ją do kolejki Cpro
    # (13.10.2026, `pipeline_move_rules.requires_dl_client_rate`).
    from app.services.board_stage_badges import cpro_enabled_for_client

    if target_column == "cv_sent" and cpro_enabled_for_client(client_id):
        from app.services import cpro_sender

        # Bez osoby na firmę wrzuca też osoba zapasowa tej rekrutacji — ta
        # sama, której kolejka pokazuje zadanie (`board_tasks._sees_cpro`).
        job_sender_id = await db.scalar(
            select(Job.cpro_sender_id).where(Job.id == job_id)
        )
        if not await cpro_sender.can_send_to_cpro(
            db,
            user,
            fallback_sender_ids=(
                job_sender_id,
                current.task_assignee_id if current is not None else None,
            ),
        ):
            sender = await cpro_sender.effective_sender(db)
            names = await cpro_sender.user_names(db, {sender.user_id})
            who = names.get(sender.user_id) or "osoba wyznaczona do Cpro"
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Do Cpro wrzuca {who}, z kolejki Cpro po akceptacji "
                    "Delivery Leada. Po QC użyj „Przekaż Delivery Leadowi”."
                ),
            )
    # Runda 8 (R8-N8-3): wyłącznik QC dotyczy wyłącznie kontroli CV — reguła
    # „do Cpro wrzuca osoba od Cpro” wyżej działa także przy wyłączonym QC.
    if not settings.CV_QC_GATE_ENABLED:
        return
    # Osoba już w kolejce Cpro przeszła bramkę przy wejściu do niej (albo —
    # sprzed 24.09.2026 — ręczny przegląd DZ). „✓ Wrzucone” nie liczy QC
    # drugi raz: CV Nordei to zwykle pliki Word spoza NEXUSA, a obejście ma
    # tylko osoba z uprawnieniem `recruitment_manage` (domyślnie DL/admin),
    # więc osoba od Cpro dostawałaby odmowę na zaakceptowanych.
    if (
        target_column == "cv_sent"
        and current is not None
        and current.stage_def_id is not None
    ):
        current_name = await db.scalar(
            select(PipelineStageDef.name).where(
                PipelineStageDef.id == current.stage_def_id
            )
        )
        if is_cpro_stage(current_name):
            return
    # 0521 (26.10.2026): klient bierze formularz CV z Plików rekrutacji, nie
    # CV firmowe — QC CV firmowego nie ma czego sprawdzać (decyzja D3:
    # o brakach formularza przypomina lista wymagań, bez blokady).
    from app.services import client_form_status

    if await client_form_status.client_takes_client_form(db, client_id):
        return
    await cv_qc.assert_qc_passed(
        db, candidate_id=candidate_id, job_id=job_id, user=user, stage=current
    )


async def _spend_advisory_qc_override_on_return(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    stage_def: Optional[PipelineStageDef],
    legacy_value: Optional[str],
) -> None:
    """Zwrot karty kończy obejście doradcze QC (tryb doradczy, 12.10.2026).

    „Przesuń mimo uwag…” rekrutera przepuszcza kartę naprzód — także wysyłkę
    przez Delivery Leada, który widzi baner z powodem. Każdy inny ruch (wstecz,
    z kolejki Cpro do „QC CV”, do „Zamkniętych”) je kończy: gdy karta wróci,
    QC znów pyta, a kolejne obejście znów powiadamia Delivery Leada. Zapis
    w transakcji ruchu — odmowa ruchu cofa także ten zapis.
    """

    from app.services import cv_finding_dismissals, cv_qc

    has_override = await cv_qc.has_live_advisory_override(db, candidate_id, job_id)
    # Pominięte uwagi blokujące („To nieprawda”, D5) działają jak obejście
    # doradcze: zwrot karty przywraca te, które pominęła osoba bez prawa wysyłki.
    has_dismissals = await cv_finding_dismissals.has_blocking(db, candidate_id, job_id)
    if not (has_override or has_dismissals):
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
    _current, current_column = await pipeline_move_rules.gate_stage_row(
        db, candidate_id=candidate_id, job_id=job_id
    )
    order = BOARD_COLUMN_ORDER
    forward = (
        target_column in order
        and current_column in order
        and (
            order.index(target_column) > order.index(current_column)
            # Ta sama kolumna „QC CV”: naprzód idzie tylko wejście do kolejki Cpro.
            or (
                target_column == current_column
                and stage_def is not None
                and is_cpro_stage(stage_def.name)
            )
        )
    )
    if not forward:
        if has_override:
            await cv_qc.spend_advisory_overrides(db, candidate_id, job_id)
        if has_dismissals:
            await cv_finding_dismissals.restore_on_card_return(db, candidate_id, job_id)


@dataclass
class MoveProposed:
    """Integracja (token OAuth) dodała ruchem NOWĄ osobę bez zgłoszenia do tej
    rekrutacji — propozycja ``job_board`` zamiast karty (06.10.2026)."""

    proposal: "ProposeResult"
    candidate_id: int
    job_id: int


@dataclass
class MoveReplayed:
    """Powtórzony ruch na „Zatrudniony” — karta już tam stoi, nic nie zapisano."""

    stage: CandidateStage


@dataclass
class MoveApplied:
    """Zapisany ruch (bez commita) i to, czego potrzebują efekty po commicie."""

    stage: CandidateStage
    job: Job
    candidate_id: int
    job_id: int
    stage_def: Optional[PipelineStageDef]
    legacy_enum: PipelineStage
    target_column: str
    previous_stage_row: Optional[CandidateStage]
    stage_display_name: str
    hired_engagement: Optional[str]
    cpro_assignee: Optional[User]
    cpro_assignee_added_to_team: bool
    scheduled_rejection_email_id: Optional[int]
    rejection_email_status: Optional[str]
    # Ostrzeżenie eligibility przyjęte flagą `acknowledge_eligibility`.
    eligibility_acknowledged: Optional[str]
    # Czytane PRZED commitem — obiekty sesji po commicie bywają wygasłe.
    actor_id: Optional[int]
    # Uwaga zapisana przy ruchu (`stage_remarks`) — jej wzmianki „@” dzwonią
    # po commicie (22.10.2026).
    remark_note: Optional[Note] = None


async def apply_move(
    db: AsyncSession,
    data: StageMove,
    *,
    policy: RecruitmentMovePolicy,
    request: Optional[Request] = None,
) -> Union[MoveProposed, MoveReplayed, MoveApplied]:
    """Ruch karty bez commita — jedno ciało dla Tablicy i API v1 (15.10.2026).

    Wszystkie bramki ``/move`` w tej samej kolejności; „czy wolno” i „kto”
    idą przez ``policy`` (``services/recruitment_move_policy.py``): osoba
    z Tablicy dostaje dokładnie bramki sprzed wydzielenia, konto serwisowe —
    reguły API v1. Wołający zatwierdza transakcję i po commicie woła
    ``run_move_effects`` (powiadomienia, Tablica na żywo, pula talentów,
    ryzyko). Dwa wyniki nie zapisują ruchu: ``MoveProposed`` i ``MoveReplayed``.
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
    await policy.ensure_job_access(job.id)

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
            policy.viewer, stage_name=stage_def.name, client_id=job.client_id
        )
    # Runda 9 (R9-N11-4): para BEZ żadnego wiersza etapu to dodanie osoby do
    # rekrutacji, nie ruch. Wejście tylko do „Nowych”/„Screeningu” i twarda
    # bramka czarnej listy / weta — ta sama reguła co bulk-add
    # (`proposals_bulk`, `is_entry_column`). Dalsze kolumny mają bramki
    # ruchu, które liczą się względem drogi, której tu nie ma.
    fresh_pair = await _pair_has_no_stage(
        db, candidate_id=data.candidate_id, job_id=job.id
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
    # Kolumna docelowa (bramki debriefu, „Zweryfikowany”, haki po ruchu).
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
    # Ruchy, których autor nie robi wcale — przed pierwszym zapisem i przed
    # bramkami biznesowymi (osoba z ekranu: bez listy odmów, API v1:
    # `requires_screen_decision`, `services/recruitment_move_policy.py`).
    await policy.assert_move_allowed(
        MoveTarget(
            data=data,
            job=job,
            stage_def=stage_def,
            legacy_enum=legacy_enum,
            target_column=target_column,
            fresh_pair=fresh_pair,
        )
    )
    if fresh_pair:
        _assert_fresh_pair_entry(stage_def, data.stage)
        await assert_candidate_move_eligible(
            db,
            candidate_id=data.candidate_id,
            job=job,
            now=datetime.now(timezone.utc),
        )
        proposal = await _integration_fresh_pair_proposal(
            db, request, job=job, candidate_id=data.candidate_id
        )
        if proposal is not None:
            return MoveProposed(
                proposal=proposal, candidate_id=data.candidate_id, job_id=job.id
            )

    # Rekrutacja v5 (0361): QC CV przed „CV wysłane”/Cpro. Tu, przed
    # pierwszym zapisem ruchu — odmowa zapisuje przebieg QC i nic więcej.
    await _assert_cv_qc_gate(
        db,
        policy.viewer,
        candidate_id=data.candidate_id,
        job_id=job.id,
        stage_def=stage_def,
        legacy_value=data.stage.value if data.stage is not None else None,
        client_id=job.client_id,
    )
    await _spend_advisory_qc_override_on_return(
        db,
        candidate_id=data.candidate_id,
        job_id=job.id,
        stage_def=stage_def,
        legacy_value=data.stage.value if data.stage is not None else None,
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
        # Wskazanie osoby przy ruchu ustawia osobę od Cpro rekrutacji (zapas,
        # który widzi stawki do klienta w kolejce) — ta sama bramka co
        # `PUT /api/board-tasks/cpro/sender`: tylko admin albo DL Nordei
        # (przegląd PR #1844; inaczej rekruter wskazywał sam siebie).
        from app.services import cpro_sender as cpro_sender_svc

        if not await cpro_sender_svc.can_set_sender(db, policy.viewer):
            raise HTTPException(
                status_code=403, detail=cpro_sender_svc.SET_SENDER_FORBIDDEN
            )
        cpro_assignee = await board_tasks_svc.load_assignee(db, data.task_assignee_id)
        # Przed ruchem: odmowa (osoba spoza zespołu, a typuje ktoś bez prawa
        # zmiany zespołu) ma zatrzymać ruch, zanim cokolwiek się zapisze.
        cpro_assignee_added_to_team = await board_tasks_svc.ensure_assignee_can_move(
            db, job_id=job.id, assignee=cpro_assignee, actor=policy.viewer
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
    await policy.assert_can_act(candidate_id=data.candidate_id, job_id=data.job_id)

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

    # ── M4 PR-01: capability guard na ruchy terminalne i rate-bearing ──────
    # Terminal (po stage_def LUB legacy enum) i ruch na `verified` (niesie
    # stawkę kandydata) mają własne listy ról. Od 02.10.2026 obie obejmują
    # każdą rolę wewnętrzną, także sourcera (decyzja Artura).
    is_terminal_target = bool(stage_def and stage_def.is_terminal) or legacy_enum in (
        PipelineStage.hired,
        PipelineStage.rejected,
        PipelineStage.withdrawn,
    )
    if is_terminal_target and not policy.can_terminal_transition():
        raise HTTPException(
            status_code=403,
            detail=(
                "Ruch na etap terminalny (hired/rejected/withdrawn) wymaga roli "
                "admin, head_of_recruitment, delivery_lead, "
                "talent_community_manager, recruiter lub finance."
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
        return MoveReplayed(stage=previous_stage_row)

    if legacy_enum == PipelineStage.verified and not policy.can_edit_rates():
        raise HTTPException(
            status_code=403,
            detail=(
                "Ruch na etap 'Zweryfikowany' może nieść stawkę kandydata i wymaga "
                "roli admin, head_of_recruitment, delivery_lead, "
                "talent_community_manager, recruiter lub finance."
            ),
        )

    # D2 (04.10.2026): ręczny ruch na „Zatrudniony” mówi, jak podpisano umowę.
    pipeline_move_rules.assert_hired_signed_via(
        legacy_enum, data.hired_signed_via, data.hired_signed_note
    )
    # Etap 1b (22.10.2026): umowa w podpisie w NEXUSIE zatrudnia sama.
    await pipeline_move_rules.assert_no_esign_in_progress(
        db,
        target=legacy_enum,
        candidate_id=data.candidate_id,
        job_id=data.job_id,
    )
    # 16.10.2026 (D1): okno „Klient zaakceptował” — data akceptacji i start.
    pipeline_move_rules.assert_client_acceptance_dates(
        legacy_enum,
        data.client_accepted_on,
        data.planned_start_on,
        today=business_today(),
    )

    # Pipeline v4 (23.09.2026): wejście do „Umowy"/„Zatrudnionego" wymaga
    # debriefu po rozmowie u klienta (pytania klienta albo „klient nie zadawał
    # pytań") — pytania zasilają prep i profil Championa.
    # Delivery Lead przechodzi mimo braków (22.10.2026) — braki idą do śladu
    # ruchu (`requirements_skipped`), z którego Tablica rysuje odznakę.
    debrief_skipped = await pipeline_move_rules.assert_debrief_before_contract(
        db,
        candidate_id=data.candidate_id,
        job_id=data.job_id,
        target_column=target_column,
        user=policy.viewer,
    )
    # D1 (04.10.2026): „Zweryfikowany” z Nowych/Screeningu wymaga arkusza
    # screeningu i stawki kandydata — ta sama reguła co okno „Przesuń dalej”.
    # Lista niepusta tylko przy przejściu przez „Zweryfikowany” od lewej
    # (z Nowych/Screeningu na „Zweryfikowany” albo dalej).
    verified_skipped = await pipeline_move_rules.assert_verified_requirements(
        db,
        candidate_id=data.candidate_id,
        job=job,
        user=policy.viewer,
        target_column=target_column,
        pending_rate=data.expected_rate_value is not None
        and data.expected_rate_value > 0,
    )
    skipped_requirements = debrief_skipped + verified_skipped
    # D6 (08.10.2026): „Wróć do poprawy” z „QC CV” niesie listę pól do poprawy.
    # Walidacja PRZED zapisem ruchu — zła lista nie może cofnąć karty bez niej.
    fix_keys: list[str] = []
    if data.fix_fields:
        _gate_row, from_column = await pipeline_move_rules.gate_stage_row(
            db, candidate_id=data.candidate_id, job_id=data.job_id
        )
        screening_fix_requests.assert_allowed(
            from_column=from_column,
            target_column=target_column,
            client_id=job.client_id,
        )
        fix_keys = screening_fix_requests.validate(
            data.fix_fields, screening_fix_requests.fix_options(job)
        )

    # Pipeline v4 (23.09.2026): „CV wysłane" poza Nordeą wysyła Delivery Lead
    # (uprawnienie `recruitment_manage`) i wpisuje stawkę do klienta. U Nordei
    # tym krokiem jest akceptacja do kolejki Cpro (13.10.2026). Stawka
    # zapisana wcześniej w tej rekrutacji (powrót na etap) wystarcza — nie
    # trzeba jej przepisywać.
    client_rate_value = data.client_rate_value
    client_rate_unit = data.client_rate_unit
    client_rate_currency = (data.client_rate_currency or "PLN")[:3].upper()
    to_cpro_queue = cpro_enabled_for_client(job.client_id)
    if pipeline_move_rules.requires_dl_client_rate(
        legacy_enum,
        job.client_id,
        stage_name=stage_def.name if stage_def else None,
    ) and await pipeline_move_rules.arrives_from_before_client_send(
        db, candidate_id=data.candidate_id, job_id=data.job_id
    ):
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
        pipeline_move_rules.assert_client_send_allowed(
            policy.viewer, known_rate, cpro=to_cpro_queue
        )
    elif client_rate_value is not None and not await resolve_client_rate_write(
        db, policy.viewer, job
    ):
        # Stawka do klienta w ruchu = ta sama bramka co `PATCH …/client-rate`.
        raise client_rate_write_denied()
    # Stawka pary sprzed ruchu — „stara” kwota w audycie, jak w PATCH. Nowy
    # wiersz etapu startuje bez stawki, więc bez niej historia gubi kwotę
    # wysyłki („brak stawki → X”).
    client_rate_before = None
    if client_rate_value is not None:
        await _assert_client_rate_not_order_locked(
            db, candidate_id=data.candidate_id, job_id=data.job_id
        )
        from app.services.stage_client_rate import latest_client_rates  # noqa: PLC0415

        client_rate_before = (
            await latest_client_rates(db, [(data.candidate_id, data.job_id)])
        ).get((data.candidate_id, data.job_id))

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
    if not is_removal_move and not fresh_pair:
        eligibility_block = await check_candidate_move_eligibility(
            db,
            candidate_id=data.candidate_id,
            job=job,
            now=datetime.now(timezone.utc),
            # Runda 9 (R9-N11-3): weto z kolumny docelowej, jak bramka QC —
            # etapy u klienta rozpoznane po nazwie mają kod `interview`.
            enforce_manager_verdict=puts_column_before_client(target_column),
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
            data.ended_by, withdrawn=is_withdrawn_target, user=policy.viewer
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
    reason: Optional[RejectionReason] = None
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
    # Powód „Nie akceptuje trybu pracy” (14.10.2026): liczba dni w biurze,
    # które kandydat akceptuje, jest przy nim obowiązkowa (trafia na profil),
    # a przy każdym innym ruchu nie ma czego zapisać.
    work_mode_rejection = (
        reason is not None and reason.name == rejection_reason_labels.WORK_MODE_MISMATCH
    )
    if work_mode_rejection and data.work_mode_max_onsite_days is None:
        raise HTTPException(
            status_code=422,
            detail="Podaj, ile dni w biurze kandydat akceptuje.",
        )
    if not work_mode_rejection and data.work_mode_max_onsite_days is not None:
        raise HTTPException(
            status_code=422,
            detail=(
                "Liczbę dni w biurze podaje się tylko przy powodzie "
                "„Nie akceptuje trybu pracy”."
            ),
        )
    # Powód „za drogo” (26.10.2026): nowa stawka osoby ma sens tylko przy nim.
    rate_rejection = reason is not None and rejection_reason_labels.is_rate_too_high(
        reason.name
    )
    if data.rejection_rate_hourly is not None and not rate_rejection:
        raise HTTPException(
            status_code=422,
            detail=(
                "Nową stawkę podaje się tylko przy powodzie "
                "„Za wysokie oczekiwania finansowe”."
            ),
        )
    # Osoba od systemu (23.10.2026): odrzucenie z „Nowych”/„Screeningu”
    # wymaga powodu ze stałej listy i „skąd wiesz” — z powodów poprawiamy
    # wyszukiwanie (`services/autofill_feedback.py`). Walidacja PRZED zapisem.
    from app.services import autofill_feedback  # noqa: PLC0415

    target_terminal = (
        getattr(stage_def.terminal_type, "value", stage_def.terminal_type)
        if is_terminal_move_stagedef
        else legacy_enum.value
    )
    autofill_process = None
    if target_terminal == PipelineStage.rejected.value:
        _gate_row, autofill_from_column = await pipeline_move_rules.gate_stage_row(
            db, candidate_id=data.candidate_id, job_id=data.job_id
        )
        autofill_process = await autofill_feedback.system_process_in_decision(
            db,
            candidate_id=data.candidate_id,
            job_id=data.job_id,
            from_column=autofill_from_column,
        )
    autofill_feedback.validate(
        process=autofill_process,
        reason=data.autofill_reason,
        learned_from=data.autofill_learned_from,
        note=data.notes,
        not_looking_until=data.autofill_not_looking_until,
    )
    # 20.10.2026: „Inne” i „Już po rozmowie u tego hiring managera” bez opisu
    # zostawiały w historii samo słowo. Opis przychodzi jako `notes` (okna
    # odrzucenia) albo `rejection_reason` (API integracyjne).
    reason_description = (data.notes or "").strip() or (
        data.rejection_reason or ""
    ).strip()
    if (
        reason is not None
        and rejection_reason_labels.needs_description(reason.name)
        and not reason_description
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Przy powodzie „{rejection_reason_labels.rejection_reason_label(reason.name)}” "
                "opisz, dlaczego — bez opisu w historii zostaje samo słowo."
            ),
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
        if expected_rate_value is None:
            # D2 (14.10.2026): Tablica przesuwa parę ze stawką bez okna stawki
            # i bez stawki w żądaniu — nowy wiersz dostaje najnowszą stawkę pary
            # (`pair_rates`, ta sama reguła co karta), żeby porównanie
            # z budżetem i odznaka „ponad budżet” liczyły się jak po oknie.
            from app.services.candidate_rate_change import pair_rates

            carried = await pair_rates(
                db, candidate_id=data.candidate_id, job_id=data.job_id
            )
            if carried["amount"] is not None:
                expected_rate_value = carried["amount"]
                expected_rate_unit = (
                    RateUnit(carried["unit"]) if carried["unit"] else None
                )
                expected_rate_currency = str(carried["currency"] or "PLN")
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
    elif (
        data.rejection_reason
        and data.rejection_reason.strip()
        and not (data.notes or "").strip()
    ):
        # Powód ze słownika z opisem z API integracyjnego — opis dotąd znikał.
        effective_notes = data.rejection_reason.strip()
    if rate_rejection and data.rejection_rate_hourly is not None:
        effective_notes = _rate_rejection_note(
            data.rejection_rate_hourly,
            is_minimum=data.rejection_rate_is_minimum,
            notes=effective_notes,
        )

    stage = await transition_process(
        db,
        candidate_id=data.candidate_id,
        job_id=data.job_id,
        stage=legacy_enum,
        stage_def_id=stage_def.id if stage_def else None,
        rejection_reason_id=data.rejection_reason_id,
        moved_at=datetime.now(timezone.utc),
        actor_user_id=policy.actor_id,
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
        # Runda 10 (R10-V2-4): para bez wiersza to dodanie osoby — źródło
        # wejścia i blokada 12 h jak w bulk-add (integracja bez blokady).
        **(_fresh_pair_entry_kwargs(policy.viewer, request) if fresh_pair else {}),
    )
    if legacy_enum == PipelineStage.acceptance and (
        data.client_accepted_on is not None
        or await _enters_acceptance_from_before_contract(db, previous_stage_row)
    ):
        # Karta i dzwonek mówią, KIEDY klient zaakceptował — przeciągnięcie
        # bez okna to akceptacja z dnia ruchu. Powrót na „Akceptację” z kroku
        # umowy (odznaczone „Umowa wysłana”) nie jest nową akceptacją: wiersz
        # zostaje bez daty, a karta czyta ostatnią akceptację z datą.
        stage.client_accepted_on = data.client_accepted_on or business_today()
        stage.planned_start_on = data.planned_start_on
    if client_rate_value is not None:
        old_value, old_unit, old_currency = client_rate_before or (None, None, None)
        candidate_audit.record_candidate_audit(
            db,
            action=candidate_audit.CLIENT_RATE_CHANGED,
            user_id=policy.actor_id,
            entity_id=data.candidate_id,
            details={
                "job_id": data.job_id,
                "stage_id": stage.id,
                "old_client_rate": old_value,
                "old_client_rate_unit": old_unit,
                "old_client_rate_currency": old_currency,
                "new_client_rate": float(client_rate_value),
                "new_client_rate_unit": stage.client_rate_unit,
                "new_client_rate_currency": stage.client_rate_currency,
                "source": "pipeline_move",
            },
        )
    # 0506: umowa przedwstępna pary — termin umowy B2B po akceptacji klienta
    # i ślad ruchu bez podpisanej umowy (ostrzeżenie, nie bramka).
    from app.services import pre_contracts as _pre_contracts  # noqa: PLC0415
    from app.services.board_stage_badges import (  # noqa: PLC0415
        board_column_for as _board_column_for,
    )
    from app.services.move_requirements import (  # noqa: PLC0415
        column_label as _column_label,
    )

    _to_column = _board_column_for(
        stage_def.name if stage_def is not None else None,
        legacy_enum.value,
        category=getattr(
            getattr(stage_def, "category", None),
            "value",
            getattr(stage_def, "category", None),
        ),
        terminal_type=getattr(
            getattr(stage_def, "terminal_type", None),
            "value",
            getattr(stage_def, "terminal_type", None),
        ),
    )
    # 28.10.2026: karta bez osoby („System”) przeniesiona przez człowieka
    # z „Nowych” do „Screeningu” jest jego, jak po „Biorę”.
    if (
        policy.mover is not None
        and policy.actor_id is not None
        and not candidate_claim.is_integration_request(request)
    ):
        await candidate_claim.take_unowned_on_screening(
            db, previous=previous_stage_row, moved=stage, user_id=policy.actor_id
        )
    await _pre_contracts.on_move(
        db,
        candidate_id=data.candidate_id,
        job_id=data.job_id,
        to_column=_to_column,
        to_label=_column_label(_to_column),
        accepted_on=stage.client_accepted_on,
        actor_id=policy.actor_id,
        actor_name=getattr(policy.viewer, "name", None),
    )
    await create_original_cv_snapshot(db, stage)
    if expected_rate_value is not None:
        await _record_rate_from_move(
            db,
            candidate_id=data.candidate_id,
            value=Decimal(expected_rate_value),
            unit=expected_rate_unit.value if expected_rate_unit else None,
            currency=expected_rate_currency,
            is_minimum=data.expected_rate_is_minimum,
            actor_id=policy.actor_id,
        )
    if autofill_process is not None:
        await autofill_feedback.record(
            db,
            process=autofill_process,
            job=job,
            stage_id=stage.id,
            reason=data.autofill_reason,
            learned_from=data.autofill_learned_from,
            rate_hourly=data.autofill_rate_hourly,
            note=data.notes,
            actor_id=policy.actor_id,
            whole_client=data.autofill_whole_client,
        )
        if (
            data.autofill_whole_client
            and data.autofill_reason in autofill_feedback.CLIENT_WIDE_REASONS
            and job.client_id is not None
        ):
            from app.services import autofill_withdraw

            await autofill_withdraw.withdraw_at_client(
                db,
                candidate_id=data.candidate_id,
                client_id=job.client_id,
                except_job_id=job.id,
            )
        # „Nie szuka pracy” z datą (28.10.2026): profil + zdjęcie nietkniętych
        # kart od systemu z innych rekrutacji, silnik pomija do tej daty.
        if data.autofill_not_looking_until is not None:
            from app.services import autofill_withdraw

            change = await autofill_feedback.mark_not_looking(
                db,
                candidate_id=data.candidate_id,
                until=data.autofill_not_looking_until,
            )
            if change is not None:
                candidate_audit.record_candidate_audit(
                    db,
                    action=candidate_audit.AVAILABILITY_CHANGED,
                    user_id=policy.actor_id,
                    entity_id=data.candidate_id,
                    details={
                        **change,
                        "source": "autofill_rejection",
                        "job_id": job.id,
                        "stage_id": stage.id,
                    },
                )
            await autofill_withdraw.withdraw_elsewhere(
                db, candidate_id=data.candidate_id, except_job_id=job.id
            )
        # „Ile chce?” z rozmowy — ta sama droga do „Stawki od” co stawka
        # z okna „Zweryfikowany”.
        if data.autofill_rate_hourly is not None:
            await _record_rate_from_move(
                db,
                candidate_id=data.candidate_id,
                value=Decimal(data.autofill_rate_hourly),
                unit="hourly",
                currency="PLN",
                is_minimum=False,
                actor_id=policy.actor_id,
            )
    if rate_rejection and data.rejection_rate_hourly is not None:
        await _record_rejection_rate(
            db,
            candidate_id=data.candidate_id,
            amount=Decimal(data.rejection_rate_hourly),
            is_minimum=data.rejection_rate_is_minimum,
            job_id=job.id,
            stage_id=stage.id,
            actor_id=policy.actor_id,
        )
    if work_mode_rejection and data.work_mode_save_to_profile:
        await _record_work_mode_from_rejection(
            db,
            candidate_id=data.candidate_id,
            job=job,
            stage=stage,
            max_onsite_days=data.work_mode_max_onsite_days,
            user=policy.actor,
        )
    remark_note = stage_remarks.record(
        db, stage=stage, author_id=policy.actor_id, text=data.recruiter_remark
    )
    await screening_fix_requests.record(
        db, job=job, stage=stage, user=policy.actor, keys=fix_keys
    )
    await stage_handoff_recipients.close_cpro_queue_bells(
        db,
        previous=previous_stage_row,
        target_name=stage_def.name if stage_def else None,
    )
    await stage_handoff_recipients.close_client_acceptance_bells(
        db, previous=previous_stage_row, target_column=target_column
    )
    if cpro_assignee is not None:
        stage.task_assignee_id = cpro_assignee.id
        job.cpro_sender_id = cpro_assignee.id
    if is_terminal_target:
        await maybe_close_contact_opportunity(
            db,
            candidate_id=data.candidate_id,
            job_id=data.job_id,
            actor_user_id=policy.actor_id,
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

    # Activity log + UserActivity (ranking) — wspólne z `/bulk-move`.
    activity_extra: dict = {}
    if legacy_enum == PipelineStage.hired and data.hired_signed_via is not None:
        activity_extra["hired_signed_via"] = data.hired_signed_via
        if data.hired_signed_note:
            activity_extra["hired_signed_note"] = data.hired_signed_note.strip()
    # „Co z obecną współpracą?” (12.10.2026): odpowiedź zapisujemy tylko, gdy
    # osoba faktycznie ma u nas zatrudnienie u innego klienta — inaczej
    # historia mówiłaby o współpracy, której nie ma.
    hired_engagement: Optional[str] = None
    if legacy_enum == PipelineStage.hired and data.hired_current_engagement is not None:
        elsewhere_client_ids = await employed_elsewhere_client_ids(
            db, candidate_id=data.candidate_id, job=job
        )
        if elsewhere_client_ids:
            hired_engagement = data.hired_current_engagement
            activity_extra["hired_current_engagement"] = hired_engagement
            activity_extra["employed_at_client_ids"] = elsewhere_client_ids
            candidate_audit.record_candidate_audit(
                db,
                action=candidate_audit.HIRED_ENGAGEMENT_ACTIONS[hired_engagement],
                user_id=policy.actor_id,
                entity_id=data.candidate_id,
                details={"job_id": job.id, "client_ids": elsewhere_client_ids},
            )
    if legacy_enum == PipelineStage.verified and budget_max_snapshot is not None:
        # M4 PR-02: audyt decyzji gate'u — z jakiej normalizacji wynikła.
        activity_extra["rate_gate"] = {
            "policy": RATE_POLICY_VERSION,
            "note": normalization_note,
            "budget_exceeded": budget_exceeded,
            "budget_max": budget_max_snapshot,
        }
    _record_stage_change(
        db,
        stage=stage,
        stage_def=stage_def,
        legacy_enum=legacy_enum,
        actor_id=policy.actor_id,
        stage_display_name=stage_display_name,
        extra_details=activity_extra,
    )
    if skipped_requirements:
        db.add(
            Activity(
                entity_type="pipeline",
                entity_id=stage.id,
                action=pipeline_move_rules.REQUIREMENTS_SKIPPED_ACTION,
                user_id=policy.actor_id,
                details={
                    "candidate_id": data.candidate_id,
                    "job_id": data.job_id,
                    "stage": legacy_enum.value,
                    "missing": skipped_requirements,
                },
            )
        )
        # Audyt 22.10.2026 (F58), decyzja Artura: dzwonek przy każdym
        # przejściu DL-a przez „Zweryfikowany” od lewej, także przeskoku
        # od razu na „QC CV” czy dalej. Sam przeskok debriefu nie dzwoni.
        if verified_skipped:
            await _notify_recruiter_of_skip(
                db,
                job=job,
                candidate_id=data.candidate_id,
                mover=policy.mover,
                stage_name=stage_display_name,
                missing=skipped_requirements,
            )
    if eligibility_block is not None:
        # Przeniesiono mimo ostrzeżenia — audyt widzi, co zignorowano i kto.
        db.add(
            Activity(
                entity_type="pipeline",
                entity_id=stage.id,
                action="eligibility_acknowledged",
                user_id=policy.actor_id,
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
        await _cancel_pending_rejection_emails(
            db,
            candidate_id=data.candidate_id,
            job_id=data.job_id,
            actor_id=policy.actor_id,
            restored_to=legacy_enum,
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
                    actor_id=policy.actor_id,
                    default_start_date=business_today(),
                    ensure_order=True,
                    # The stage was inserted and flushed just above. The
                    # idempotent guard sees it as latest and never appends a
                    # duplicate.
                    ensure_hired=True,
                    require_b2b=False,
                    ensure_detail=False,
                    contract_type=_HIRED_CONTRACT_TYPE.get(
                        data.hired_signed_via or "", ContractType.b2b
                    ),
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
                    user_id=policy.actor_id,
                    details={
                        "candidate_id": data.candidate_id,
                        "job_id": job.id,
                        "stage": legacy_enum.value,
                        "order_id": (employment.order.id if employment.order else None),
                        # Stawka z tej rekrutacji wpisana w szkic — po niej
                        # podpis w Generatorze rozpoznaje zaślepkę.
                        "seeded_rate_candidate": (
                            str(employment.seeded_rate_candidate)
                            if employment.seeded_rate_candidate is not None
                            else None
                        ),
                    },
                )
            )
            # D3 (04.10.2026): nowy szkic zamówienia ma kartę DL „uzupełnij
            # zamówienie” (`_notify_new_contractor_draft`) — dzwonek dublowałby
            # tę samą sprawę. Zostaje tylko dla samego szkicu kontraktu.
            bell_recipients = (
                []
                if employment.created_order
                else delivery_recipients.bell_recipients(
                    job.client_id, NotificationType.contract_activated
                )
            )
            for uid in bell_recipients:
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

        if (
            employment is not None
            and employment.contract is not None
            and employment.order_skipped_reason != ORDER_SKIPPED_OPEN_GROUP_LINE
        ):
            # D3 (04.10.2026): ręczne zatrudnienie otwiera tę samą sprawę co
            # podpis w Generatorze — Finanse dostają dzwonek (o ile para nie
            # ma jeszcze uzupełnionego zamówienia). Fail-soft, savepoint.
            from app.services.hired_order_status import (  # noqa: PLC0415
                notify_finance_hired_without_order,
            )

            await notify_finance_hired_without_order(
                db,
                contract_id=employment.contract.id,
                candidate_id=data.candidate_id,
                job_id=job.id,
                client_id=job.client_id,
                start_date=employment.contract.start_date,
            )

        if draft_skip_reason is not None:
            from app.services.notification_triggers import emit

            db.add(
                Activity(
                    entity_type="pipeline",
                    entity_id=stage.id,
                    action="contract_draft_skipped",
                    user_id=policy.actor_id,
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
            for uid in delivery_recipients.bell_recipients(
                job.client_id, NotificationType.suggest_next_step
            ):
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

    # Obsada kompletna → PODPOWIEDŹ zamknięcia rekrutacji, nie automat
    # (`job_fill.suggest_closing_when_fully_staffed` — ta sama reguła woła
    # potwierdzenie podpisu B2B). Savepoint, nigdy nie rzuca.
    if legacy_enum == PipelineStage.hired:
        from app.services.job_fill import (  # noqa: PLC0415
            suggest_closing_when_fully_staffed,
        )

        await suggest_closing_when_fully_staffed(db, job)

    # Mail odrzucenia (0045_rejection_emails) jest OPT-IN od 17.09.2026:
    # planujemy WYŁĄCZNIE gdy klient przysłał `send_rejection_email=True`
    # (checkbox w oknie odrzucenia, domyślnie odznaczony). `maybe_schedule`
    # nadal sam sprawdza kwalifikowalność (etap klienta, e-mail kandydata).
    #
    # Runda 9 (R9-N11-1): mail wychodzi ze skrzynki osoby, która ODRZUCA —
    # nie prowadzącego rekrutacji (dotąd `job.recruiter_id`: cudza skrzynka,
    # cudzy podpis i 403 na „Cofnij wysyłkę” dla odrzucającego). Bez
    # podłączonej skrzynki nic nie planujemy i odpowiedź mówi dlaczego.
    scheduled_rejection_email_id: Optional[int] = None
    rejection_email_status: Optional[str] = None
    if (
        legacy_enum == PipelineStage.rejected
        and data.send_rejection_email is True
        and policy.may_send_rejection_email
    ):
        from app.services import rejection_email_scheduler as _rejection_mail

        rejection_email_status = await _rejection_mail.skip_reason(
            db, stage=stage, sender=policy.actor
        )
        if rejection_email_status is None:
            scheduled = await _rejection_mail.maybe_schedule(
                db,
                stage=stage,
                job=job,
                recruiter_id=policy.actor_id,
                template_override_id=data.rejection_email_template_id,
                edited_subject=data.rejection_email_subject,
                edited_body=data.rejection_email_body,
                append_other_processes=data.rejection_email_other_processes
                is not False,
                merge=data.rejection_email_merge is not False,
            )
            if scheduled is not None:
                scheduled_rejection_email_id = scheduled.id
                rejection_email_status = _rejection_mail.EMAIL_STATUS_SCHEDULED
            else:
                rejection_email_status = _rejection_mail.EMAIL_SKIP_NOT_CLIENT_VISIBLE

    # 0341: osoba weszła do klienta → przepnij ją do połączonych (podobnych)
    # rekrutacji jako propozycję „przepięcie". Nigdy nie rzuca.
    if legacy_enum is not None:
        from app.services.job_similarity import on_candidate_sent  # noqa: PLC0415

        # Runda 9 (R9-N11-3): haki czytają kolumnę docelową, nie sam kod —
        # „Po Interview” / „Preparation Meeting” (kod `interview`) to rozmowa
        # u klienta.
        hook_stage = _client_hook_stage(target_column, legacy_enum)
        await on_candidate_sent(
            db, job_id=data.job_id, candidate_id=stage.candidate_id, stage=hook_stage
        )
        # 0371: klient zaprosił na rozmowę / zaakceptował → „Klient milczy”
        # wraca do „Szukamy kandydatów”. Nigdy nie rzuca.
        from app.services.request_work_state import (  # noqa: PLC0415
            wake_on_client_response,
        )

        await wake_on_client_response(
            db, job_id=data.job_id, stage=hook_stage, reason="client_stage"
        )

    return MoveApplied(
        stage=stage,
        job=job,
        candidate_id=data.candidate_id,
        job_id=data.job_id,
        stage_def=stage_def,
        legacy_enum=legacy_enum,
        target_column=target_column,
        previous_stage_row=previous_stage_row,
        stage_display_name=stage_display_name,
        hired_engagement=hired_engagement,
        cpro_assignee=cpro_assignee,
        cpro_assignee_added_to_team=cpro_assignee_added_to_team,
        scheduled_rejection_email_id=scheduled_rejection_email_id,
        rejection_email_status=rejection_email_status,
        eligibility_acknowledged=(
            eligibility_block.reason_code if eligibility_block is not None else None
        ),
        actor_id=policy.actor_id,
        remark_note=remark_note,
    )


async def run_move_effects(
    db: AsyncSession, outcome: MoveApplied, *, mover: Optional[User]
) -> None:
    """Efekty po zatwierdzonym ruchu — wspólne dla ``/move`` i API v1.

    Transition jest już trwały. Nic tu nie może zwrócić 500 ani cofnąć ruchu
    (M4 PR-02, audyt P0.6). Każdy efekt biegnie w SAVEPOINCIE
    (``_post_commit_effect``): błąd cofa tylko jego zapisy i nie wygasza
    obiektów sesji, więc kolejne efekty dalej widzą ``mover``, ``job``
    i ``stage``. ``mover=None`` — ruch konta serwisowego (powiadomienia bez
    osoby, Tablica na żywo dla całego zespołu).
    """
    stage = outcome.stage
    stage_id = stage.id
    job = outcome.job
    actor_id = outcome.actor_id

    # Live kanban: the rest of the team re-reads the board (best-effort).
    await broadcast_pipeline_changed(db, outcome.job_id, actor_id)

    # Configurable stage-transition notifications (migracja 0066) —
    # in-app + email (SMTP) per regułą; teraz wyłącznie PO commicie.
    await _post_commit_effect(
        db,
        f"stage_notif stage={stage_id}",
        _notify_stage_change_effect(
            db,
            stage=stage,
            previous_stage_row=outcome.previous_stage_row,
            job=job,
            mover=mover,
            stage_display_name=outcome.stage_display_name,
            hired_engagement=outcome.hired_engagement,
        ),
    )

    # Wzmianki „@” w uwadze ruchu (22.10.2026) — dzwonek jak przy notatce;
    # mail dopiero, gdy dzwonki są zatwierdzone. Ruch konta serwisowego
    # (``mover=None``) nikogo nie oznacza.
    remark_note = outcome.remark_note
    if remark_note is not None and mover is not None:
        remark_mentions: list[stage_remarks.RemarkMentions] = []

        async def _remark_mentions() -> None:
            found = await stage_remarks.enqueue_mentions(
                db,
                note=remark_note,
                author=mover,
                stage_name=outcome.stage_display_name,
            )
            if found is not None:
                remark_mentions.append(found)

        if await _post_commit_effect(
            db, f"remark mentions stage={stage_id}", _remark_mentions
        ):
            for found in remark_mentions:
                await stage_remarks.send_mentions(found)

    # 0348/0353: dzwonek dla osoby, która wysyła do Cpro. Best-effort.
    cpro_assignee = outcome.cpro_assignee
    if cpro_assignee is not None:

        async def _notify_cpro_sender() -> None:
            await board_tasks_svc.notify_cpro_sender(
                db,
                job_id=job.id,
                job_title=job.title,
                waiting=0,
                sender_id=cpro_assignee.id,
                actor=mover,
            )

        await _post_commit_effect(
            db,
            f"cpro assignment notice stage={stage_id} "
            f"(added_to_team={outcome.cpro_assignee_added_to_team})",
            _notify_cpro_sender,
        )

    # Phase 10 A1: auto-add candidate to a talent pool when CV is sent to
    # the client. Best-effort — po commicie ruchu.
    if outcome.legacy_enum == PipelineStage.cv_sent:

        async def _auto_add_to_pool() -> None:
            from app.services.talent_pool_auto_add import auto_add_on_cv_sent

            pool_candidate = await db.scalar(
                select(Candidate).where(Candidate.id == outcome.candidate_id)
            )
            await auto_add_on_cv_sent(
                db=db,
                candidate_id=outcome.candidate_id,
                job=job,
                user_id=actor_id,
                candidate=pool_candidate,
            )

        await _post_commit_effect(
            db,
            f"auto_add_on_cv_sent candidate={outcome.candidate_id} "
            f"job={outcome.job_id}",
            _auto_add_to_pool,
        )

    # 0450 (D5, D7): karta championa zamknięta → champion schodzi sam;
    # zatrudnienie przelicza miejsca. PO commicie, we własnej transakcji —
    # blokady przydział → rekrutacja (wewnątrz ruchu trzymamy już kandydata
    # i blokadę klucza rekrutacji, więc tam groziłoby zakleszczenie).
    if outcome.target_column in ("closed", "hired"):

        async def _reconcile_champions() -> None:
            from app.services import job_champions

            await job_champions.reconcile(
                db,
                job_id=outcome.job_id,
                candidate_ids=[outcome.candidate_id],
                actor_id=actor_id,
            )

        await _post_commit_effect(
            db,
            f"champions after move job={outcome.job_id}",
            _reconcile_champions,
        )

    # Phase 17 (migracja 0068): event-driven recompute risk profile.
    # Best-effort — błąd NIE może wywołać 500 po zapisanym transition.
    async def _recompute_risk() -> None:
        from app.services.candidate_risk import on_candidate_stage_change

        await on_candidate_stage_change(db, outcome.candidate_id)

    await _post_commit_effect(
        db,
        f"risk recompute post-move candidate={outcome.candidate_id}",
        _recompute_risk,
    )


@router.post("/move", response_model=CandidateStageResponse)
async def move_candidate(
    data: StageMove,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
    request: Request = None,  # type: ignore[assignment] — wywołania wprost w testach
):
    """Move a candidate to a new pipeline stage for a given job.

    Accepts either `stage` (legacy enum) or `stage_def_id` (new FK). For
    custom stages introduced via templates, the legacy enum is set to
    `PipelineStage.new` as a placeholder — the real identifier is stage_def_id.

    Ciało ruchu (bramki i zapisy) to ``apply_move`` z ``UserMovePolicy`` —
    to samo co ``POST /api/integrations/v1/recruitments/{id}/moves``.
    """
    outcome = await apply_move(
        db, data, policy=UserMovePolicy(current_user, db), request=request
    )
    if isinstance(outcome, MoveProposed):
        await db.commit()
        return _integration_proposed_response(outcome)
    if isinstance(outcome, MoveReplayed):
        resp = _stage_response(
            outcome.stage,
            show_client_rate=user_can_view_client_rate(current_user),
        )
        resp["scheduled_rejection_email_id"] = None
        await db.commit()
        return CandidateStageResponse(**resp)

    stage = outcome.stage
    await db.commit()
    await db.refresh(stage)

    # Odpowiedź i wszystko, czego potrzebują efekty uboczne, liczymy TERAZ —
    # zanim któryś z nich zawiedzie. Do 25.09.2026 blok po commicie przy
    # błędzie robił `db.rollback()` na sesji żądania, co wygaszało
    # `current_user` i `stage`, a końcowe `_stage_response` czytało wygasłe
    # atrybuty → MissingGreenlet → 500 po zapisanym ruchu (audyt 25.09.2026).
    resp = _stage_response(
        stage, show_client_rate=user_can_view_client_rate(current_user)
    )
    stage_id = stage.id
    # F05: nowa wersja procesu po ruchu — karta podmienia ją od razu, żeby
    # kolejny ruch z tej samej karty (przed odświeżeniem tablicy) nie wysłał
    # wersji sprzed własnego ruchu i nie dostał 409 za samego siebie.
    versions = await _process_state_versions(
        db, job_id=data.job_id, candidate_ids=[data.candidate_id]
    )
    resp["process_state_version"] = versions.get(data.candidate_id, 0)

    # Po commicie: Tablica na żywo, powiadomienia o przejściu
    # (`notify_stage_change` z `previous_stage_row`), dzwonek osoby od Cpro,
    # pula talentów, ryzyko — `run_move_effects`, wspólne z API v1.
    await run_move_effects(db, outcome, mover=current_user)

    # Auto-CV (21.09.2026): po trwałym ruchu na „Zweryfikowany" system w tle
    # zakolejkowuje CV w szablonie firmowym. Własna sesja, fire-and-forget —
    # nie wpływa na status ani czas tej odpowiedzi; reguły klienta (zrzut zgody
    # RODO itd.) NIE są omijane. Tylko ten endpoint: `/bulk-move` nie przyjmuje
    # etapu `verified`, importy nie przechodzą tędy, a ruch z API v1 nie ma
    # osoby, w której imieniu CV by powstało.
    if outcome.legacy_enum == PipelineStage.verified:
        try:
            from app.services import cv_auto_generate

            if cv_auto_generate.enabled():
                _spawn(
                    cv_auto_generate.generate_after_verified(
                        stage_id=stage_id, user_id=outcome.actor_id
                    ),
                    f"cv_auto_generate stage={stage_id}",
                )
        except Exception as _exc:  # noqa: BLE001 — automat nigdy nie psuje ruchu
            logger.warning(
                "cv_auto_generate spawn failed stage=%s (%s)",
                stage_id,
                type(_exc).__name__,
            )

    # QC CV (Rekrutacja v5): po wejściu do kolumny „QC CV” QC liczy się samo,
    # żeby karta, przegląd DL i kolejka Cpro nie mówiły „nie sprawdzone”.
    _spawn_cv_qc_after_move(outcome.target_column, stage_id, outcome.actor_id)

    resp["scheduled_rejection_email_id"] = outcome.scheduled_rejection_email_id
    resp["rejection_email_status"] = outcome.rejection_email_status
    return CandidateStageResponse(**resp)


def _newest_first(entries: Iterable[CandidateStage]) -> list[CandidateStage]:
    """Kolejność kart w kolumnie Tablicy: najświeższe wejście na etap na górze.

    Remis czasu → wyżej później zapisany wiersz (`id`). Wcześniej karty stały
    wg `candidate_id`, więc osoba dodana ze starej bazy lądowała w środku
    kolumny (ticket rekrutera 15.10.2026, decyzja Artura 16.10.2026).
    """
    return sorted(entries, key=lambda s: (s.moved_at, s.id), reverse=True)


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
    job_id: DbIdPath,
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
    """Dopisz `next_action_owner` — ta sama reguła co karta na froncie.

    Faza cyklu rozmowy u klienta idzie z odznaki terminarza karty
    (`interview_cycle.badge_phase`) — tej samej, którą czyta front.
    """
    badge = payload.get("interview_badge") or {}
    payload["next_action_owner"] = next_action_for(
        column,
        days_in_stage=payload.get("days_in_stage"),
        screening_done=payload.get("screening_done"),
        screening_requirement=payload.get("screening_requirement"),
        hm_veto=payload.get("hm_veto") is not None,
        group=group,
        interview_phase=badge.get("phase"),
        interview_date=badge.get("interview_date"),
    ).owner
    return payload


async def _viewer_owns_dl_review(
    db: AsyncSession,
    job: Job,
    viewer: Optional[User],
    *,
    memo: Optional[dict[Any, Any]] = None,
) -> bool:
    """Czy przegląd przed wysłaniem do klienta w ``job`` należy do patrzącego.

    Ta sama reguła co pas „Do wysłania do klienta” na pulpicie
    (`board_tasks.reviews_as_dl`):
    Delivery Lead wpisany w rekrutacji, a bez niego — Delivery Lead z portfelem
    klienta. Nieaktywny DL rekrutacji liczy się jak brak DL-a (lustro
    `_LATEST_SQL`). U Nordei to akceptacja do kolejki Cpro (13.10.2026) —
    ta sama reguła. Bez roli Delivery Leada — bez zapytań.

    ``memo`` — pamięć jednego żądania tego samego patrzącego: „Moje następne
    kroki” składają do kilkudziesięciu tablic, a portfel i aktywność DL-a
    rekrutacji pytały bazę osobno dla każdej (audyt 13.10.2026).
    """
    if viewer is None or not viewer.has_role(UserRole.delivery_lead):
        return False
    memo = {} if memo is None else memo
    delivery_lead_id = job.delivery_lead_id
    if delivery_lead_id is not None and delivery_lead_id != viewer.id:
        # Własne konto patrzącego jest aktywne (jest zalogowany) — pytamy tylko
        # o cudze.
        key = ("active", delivery_lead_id)
        if key not in memo:
            memo[key] = bool(
                await db.scalar(
                    select(User.is_active).where(User.id == delivery_lead_id)
                )
            )
        if not memo[key]:
            delivery_lead_id = None
    if delivery_lead_id is None:
        if "portfolio" not in memo:
            memo["portfolio"] = await board_tasks_svc.dl_portfolio_client_ids(
                db, viewer.id
            )
        portfolio = memo["portfolio"]
    else:
        portfolio = frozenset()
    return board_tasks_svc.reviews_as_dl(
        viewer,
        delivery_lead_id=delivery_lead_id,
        client_id=job.client_id,
        portfolio=portfolio,
    )


async def _job_stages_generating_auto_cv(db: AsyncSession, job_id: int) -> set[int]:
    """Wiersze etapu rekrutacji, dla których automat auto-CV właśnie generuje
    dokument (``origin="auto"``, ``status="processing"``) — jedno zapytanie.

    Zadanie przerwane utratą wykonawcy `recovery_loop` przestawia na
    ``failed``, więc „w przygotowaniu” nie wisi bez końca.
    """
    from app.models.cv_generated_document import CvGeneratedDocument

    rows = await db.scalars(
        select(CvGeneratedDocument.stage_id)
        .where(
            CvGeneratedDocument.job_id == job_id,
            CvGeneratedDocument.stage_id.is_not(None),
            CvGeneratedDocument.origin == "auto",
            CvGeneratedDocument.status == "processing",
        )
        .distinct()
    )
    return {int(stage_id) for stage_id in rows.all()}


async def _enters_acceptance_from_before_contract(
    db: AsyncSession, previous: Optional[CandidateStage]
) -> bool:
    """Czy ruch na „Akceptację” przychodzi spoza kolumny „Akceptacja i umowa”
    (rozmowa u klienta, wcześniej, nowa para) — to jest akceptacja klienta."""

    if previous is None:
        return True
    previous_def = (
        await db.get(PipelineStageDef, previous.stage_def_id)
        if previous.stage_def_id is not None
        else None
    )
    column = board_column_for(
        previous_def.name if previous_def else None,
        getattr(previous.stage, "value", previous.stage),
        category=(
            previous_def.category.value
            if previous_def and previous_def.category
            else None
        ),
        terminal_type=(
            previous_def.terminal_type.value
            if previous_def and previous_def.terminal_type
            else None
        ),
    )
    return column not in ("contract", "hired")


def _client_acceptance_badge(
    row: Optional[CandidateStage], names: dict[int, Optional[str]]
) -> Optional[dict]:
    """Ostatnia akceptacja klienta pary (0451). Front rysuje ją wyłącznie
    w kolumnie „Akceptacja i umowa” — karta cofnięta do „Rozmowy u klienta”
    niesie dawną akceptację, ale jej nie pokazuje."""

    if row is None:
        return None
    accepted_on = row.client_accepted_on or (
        row.moved_at.astimezone(ZoneInfo(DEFAULT_TZ)).date() if row.moved_at else None
    )
    return {
        "stage_id": row.id,
        "accepted_on": accepted_on.isoformat() if accepted_on else None,
        "planned_start_on": (
            row.planned_start_on.isoformat() if row.planned_start_on else None
        ),
        "marked_at": row.moved_at.isoformat() if row.moved_at else None,
        "marked_by_name": names.get(row.moved_by) if row.moved_by else None,
    }


async def build_kanban_view(
    db: AsyncSession,
    job: Job,
    *,
    viewer: Optional[User] = None,
    with_followups: bool = True,
    with_employment: bool = True,
    with_cv_state: bool = True,
    with_other_jobs: bool = True,
    dl_review_memo: Optional[dict[Any, Any]] = None,
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
    # 0451: najnowsza akceptacja klienta pary — zielony wiersz „Klient
    # zaakceptował · data · kto” na karcie w kolumnie „Akceptacja i umowa”.
    # Wiersz z datą to prawdziwa akceptacja; powrót z kroku umowy daty nie ma
    # (wiersze sprzed 0451 też nie — wtedy najnowszy wiersz akceptacji).
    latest_acceptance: dict[int, CandidateStage] = {}
    latest_any_acceptance: dict[int, CandidateStage] = {}
    # Kto zweryfikował: pierwszy weryfikujący pary, jak premia rekrutera.
    # Najnowszy wiersz „Zweryfikowany” bywa cofnięciem karty przez DL z „QC
    # CV” (21.10.2026: karta pokazywała DL-a zamiast rekruterki).
    first_verified: dict[int, CandidateStage] = {}
    for s in all_stages:
        if s.candidate_id not in seen:
            seen[s.candidate_id] = s
        earliest[s.candidate_id] = s  # overwritten; last write wins (oldest row)
        # Ta sama reguła co bramka „Zweryfikowany”: arkusz z odpowiedzią, nie
        # sam zapisany arkusz (audyt 13.10.2026, pkt 5).
        if move_requirements.sheet_answered(s.screening_answers):
            screened_pairs.add(s.candidate_id)
        if s.expected_rate_value is not None:
            carried_expected_rate.setdefault(s.candidate_id, s)
        if s.client_rate_value is not None:
            carried_client_rate.setdefault(s.candidate_id, s)
        if s.stage == PipelineStage.verified:
            first_verified[s.candidate_id] = first_verifier(
                first_verified.get(s.candidate_id), s
            )
        if s.stage == PipelineStage.acceptance:
            latest_any_acceptance.setdefault(s.candidate_id, s)
            if s.client_accepted_on is not None:
                latest_acceptance.setdefault(s.candidate_id, s)
    for cid, row in latest_any_acceptance.items():
        latest_acceptance.setdefault(cid, row)
    show_client_rate = user_can_view_client_rate(viewer)
    # „Czeka na Ciebie” w kolumnie „QC CV”: raz na tablicę, dla obu gałęzi niżej.
    viewer_owns_dl_review = await _viewer_owns_dl_review(
        db, job, viewer, memo=dl_review_memo
    )

    # Bulk-load candidate names so cards render with real names (not "Kandydat" fallback)
    candidate_ids = list(seen.keys())
    contact_case_by_candidate = await load_contact_case_summaries(db, candidate_ids)
    name_by_id: dict[int, tuple[Optional[str], Optional[str]]] = {}
    # Stawka z profilu (PLN/h) — podpowiedź w oknie „Zweryfikowany" (17.09.2026).
    profile_rate_by_id: dict[int, Optional[Decimal]] = {}
    rate_from_by_id: dict[int, Optional[Decimal]] = {}
    # Dostępność z profilu (tabela rekrutacji „wersja 3") i lekkie wiersze dla
    # polityki dopuszczalności — TO SAMO zapytanie, bez ładowania całej encji.
    availability_by_id: dict[int, tuple[Optional[str], Optional[date]]] = {}
    eligibility_rows: dict[int, SimpleNamespace] = {}
    # „W bazie od” (0437): data wejścia osoby do bazy i kto ją dodał — pigułka
    # „Nowy · N dni” na karcie w „Nowych” i „Screeningu”.
    added_to_base_by_id: dict[int, tuple[Optional[datetime], bool, Optional[int]]] = {}
    if candidate_ids:
        rows = await db.execute(
            select(
                Candidate.id,
                Candidate.name,
                Candidate.lastname,
                Candidate.expected_rate_hourly,
                effective_rate_sql(Candidate),
                effective_currency_sql(Candidate),
                Candidate.availability_status,
                Candidate.availability_date,
                Candidate.status,
                Candidate.preferences,
                Candidate.created_at,
                Candidate.source_created_at,
                Candidate.external_source,
                Candidate.created_by,
            ).where(Candidate.id.in_(candidate_ids))
        )
        for (
            cid,
            cname,
            clastname,
            rate_hourly,
            rate_from,
            rate_from_currency,
            availability_status,
            availability_date,
            candidate_status,
            preferences,
            created_at,
            source_created_at,
            external_source,
            created_by,
        ) in rows.all():
            added = added_to_base(created_at, source_created_at, external_source)
            added_to_base_by_id[cid] = (added.at, added.exact, created_by)
            name_by_id[cid] = (cname, clastname)
            profile_rate_by_id[cid] = rate_hourly
            # „Stawka od” (0414) — porównywalna tylko w PLN.
            rate_from_by_id[cid] = (
                rate_from
                if str(rate_from_currency or "PLN").strip().upper() in {"", "PLN"}
                else None
            )
            availability_by_id[cid] = (
                availability_status.value if availability_status else None,
                availability_date,
            )
            eligibility_rows[cid] = SimpleNamespace(
                id=cid, status=candidate_status, preferences=preferences
            )

    # Bulk-load names of the recruiters who first assigned each candidate to the
    # job (mover on the earliest stage). One query, no per-card N+1.
    added_by_user_ids = (
        {e.moved_by for e in earliest.values() if e.moved_by is not None}
        | {v.moved_by for v in first_verified.values() if v is not None}
        | {
            creator
            for _, _, creator in added_to_base_by_id.values()
            if creator is not None
        }
    )
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
    # „Prowadzi” (25.10.2026): przypisanie admina/HoR wygrywa z właścicielem
    # procesu i osobą, która dodała — karta, panel i „kto ma ruch”.
    from app.services.pair_owner import owners_for_job

    pair_owners = await owners_for_job(db, job_id)
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
    # Etap 2 linków (19.10.2026): plakietka „Z Twojego linku” / „Z linku …”.
    link_owner_by_candidate = {
        cid: owner
        for cid, p in v4_processes.items()
        if p.entry_source == candidate_claim.ENTRY_APPLICATION
        and (owner := application_link_owner_id(p.entry_meta)) is not None
    }
    owner_ids |= set(link_owner_by_candidate.values())
    # …i ślad ponownego zgłoszenia osoby, która już była w rekrutacji:
    # „Zgłosił się też z Twojego linku” / „Zgłosił się też z linku: Marta”.
    reapplied_link_owners = _reapplied_link_owners(
        await _link_reapplications(db, job_id=job_id, candidate_ids=candidate_ids),
        v4_processes,
        link_owner_by_candidate,
    )
    for reapplied in reapplied_link_owners.values():
        owner_ids |= set(reapplied)
    inactive_claimers = await candidate_claim.inactive_holders(
        db, v4_processes.values()
    )
    reassign_job_ids = {
        p.reassign_from_job_id
        for p in v4_processes.values()
        if p.reassign_from_job_id is not None
    }
    reassign_titles: dict[int, str] = {}
    reassign_refs: dict[int, Optional[str]] = {}
    if reassign_job_ids:
        for rid, rtitle, rref in (
            await db.execute(
                select(Job.id, Job.title, Job.reference_number).where(
                    Job.id.in_(reassign_job_ids)
                )
            )
        ).all():
            reassign_titles[rid] = rtitle
            reassign_refs[rid] = rref
    board_now = datetime.now(timezone.utc)
    # Osoby od systemu (23.10.2026): termin decyzji liczy się od przypisania
    # rekrutera; jedno zapytanie tylko wtedy, gdy na Tablicy są takie karty.
    from app.services import autofill_decisions

    autofill_recruiter_since = (
        (await autofill_decisions.recruiter_since_for_jobs(db, [job_id])).get(job_id)
        if any(
            p.entry_source == candidate_claim.ENTRY_SYSTEM
            for p in v4_processes.values()
        )
        else None
    )
    # Odznaki terminarza rozmowy u klienta i status zamówienia zatrudnionych —
    # po jednym zapytaniu hurtowym (liczone w serwisach, front tylko rysuje).
    from app.services.hired_order_status import order_status_for_pairs
    from app.services.interview_cycle import interview_badges_for_job

    interview_badges = await interview_badges_for_job(
        db, job_id=job_id, candidate_ids=candidate_ids, now=board_now
    )
    # „Zatrudniony” na Tablicy to też Onboarding (`job_similarity.HIRED_STAGES`).
    from app.services.job_similarity import HIRED_STAGES  # noqa: PLC0415

    hired_ids = [s.candidate_id for s in seen.values() if s.stage in HIRED_STAGES]
    order_statuses = (
        await order_status_for_pairs(db, [(cid, job_id) for cid in hired_ids])
        if hired_ids
        else {}
    )
    # 17.10.2026: „Zatrudniony” bez umowy w Kontraktach — „Pracuje u nas”
    # liczy się wyłącznie z umowy, więc karta mówi, czego brakuje.
    from app.services.hire_contract_reminder import missing_contract_ids

    missing_contracts = (
        await missing_contract_ids(
            db,
            job_client_id=job.client_id,
            hired=[
                (s.candidate_id, s.moved_at)
                for s in seen.values()
                if s.stage in HIRED_STAGES
            ],
            now=board_now,
        )
        if hired_ids
        else set()
    )
    # 04.10.2026: stan umowy z Generatora na karcie w każdej kolumnie.
    from app.services.agreement_status import agreement_status_for_pairs

    agreements = await agreement_status_for_pairs(
        db, job_id=job_id, candidate_ids=candidate_ids
    )
    # Znacznik „Pracuje u nas” — jedno zapytanie o źródła na tablicę.
    employment_markers = (
        await load_employment_markers(
            db, candidate_ids, today=business_today(), job_client_id=job.client_id
        )
        if with_employment
        else {}
    )
    # 0506: umowa przedwstępna pary na karcie — dwa zapytania na tablicę.
    from app.services.pre_contracts import kanban_badges  # noqa: PLC0415

    pre_contract_badges = await kanban_badges(db, job_id, candidate_ids)
    # 0450 (D3): złota plakietka „Champion” na karcie — jedno zapytanie.
    from app.services.job_champions import live_candidate_ids  # noqa: PLC0415

    champion_ids = await live_candidate_ids(db, job_id)
    # „+1 rekrutacja” (14.10.2026): ta sama osoba czeka też w „Nowych”/
    # „Screeningu” innej rekrutacji — sygnał „zrób screening razem”.
    other_open_jobs: dict[int, list[dict]] = {}
    if with_other_jobs and candidate_ids:
        from app.services.also_fits import (
            SCREENING_ENTRY_STAGES,
            other_open_jobs_for_candidates,
        )

        # Znacznik stoi tylko na kartach w „Nowych”/„Screeningu” — reszty Tablicy
        # nie pytamy (zespół czyta Tablicę przy każdym `pipeline_changed`).
        screening_ids = [
            cid
            for cid, s in seen.items()
            if getattr(s.stage, "value", s.stage) in SCREENING_ENTRY_STAGES
        ]
        other_open_jobs = await other_open_jobs_for_candidates(
            db,
            candidate_ids=screening_ids,
            exclude_job_id=job_id,
            scope_clause=(
                job_read_scope_clause(viewer, Job.id) if viewer is not None else None
            ),
        )
    # 0348: wytypowani do wysłania do Cpro — ta sama paczka nazwisk.
    owner_ids |= {
        s.task_assignee_id for s in seen.values() if s.task_assignee_id is not None
    }
    # 0451: kto zaznaczył akceptację klienta.
    owner_ids |= {
        s.moved_by for s in latest_acceptance.values() if s.moved_by is not None
    }
    # Powód zamknięcia na karcie i w panelu osoby (19.10.2026): nazwa powodu
    # i kto zamknął kartę — tylko w „Odrzuconych” i „Rezygnacjach”. Nazwa
    # z bazy, nie ze słownika szablonu: powód wycofany z szablonu nadal ma
    # się wyświetlić przy kartach, które go dostały.
    closed_cards = [s for s in seen.values() if s.stage in _CLOSED_CARD_STAGES]
    owner_ids |= {s.moved_by for s in closed_cards if s.moved_by is not None}
    closed_reason_ids = {
        s.rejection_reason_id for s in closed_cards if s.rejection_reason_id is not None
    }
    reason_name_by_id: dict[int, Optional[str]] = {}
    if closed_reason_ids:
        rrows = await db.execute(
            select(RejectionReason.id, RejectionReason.name).where(
                RejectionReason.id.in_(closed_reason_ids)
            )
        )
        reason_name_by_id = {
            rid: rejection_reason_labels.rejection_reason_label(rname)
            for rid, rname in rrows.all()
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
    # Droga rekrutera do DL (14.10.2026): automat właśnie generuje CV dla
    # wiersza etapu — karta mówi „CV w przygotowaniu…”. Też jedno zapytanie.
    generating_stage_ids = (
        await _job_stages_generating_auto_cv(db, job_id) if with_cv_state else set()
    )
    # Rekrutacja v5 (0361): stan QC CV każdej karty — jedno zapytanie hurtowe
    # (najnowszy przebieg pary; obejście DL/admina = `overridden`).
    from app.services.cv_qc import pair_statuses

    qc_by_pair = await pair_statuses(db, [(cid, job_id) for cid in candidate_ids])
    # 22.10.2026: Delivery Lead przesunął mimo braków — odznaka na karcie.
    # Tylko ślady bieżącej próby — po ponownym dodaniu osoby dawne nie wracają.
    from app.services.recommendation_cards import attempt_started

    skipped_by_candidate = await _requirements_skipped(
        db,
        job_id=job_id,
        candidate_ids=candidate_ids,
        since={cid: attempt_started(p) for cid, p in v4_processes.items()},
    )
    missing_skip_names = {
        uid for _keys, uid in skipped_by_candidate.values() if uid is not None
    } - set(user_name_by_id)
    if missing_skip_names:
        srows = await db.execute(
            select(User.id, User.name).where(User.id.in_(missing_skip_names))
        )
        for uid, uname in srows.all():
            user_name_by_id[uid] = uname
    # 0413: stan karty rekomendacji każdej osoby („Karta gotowa” / „brakuje N”)
    # i liczba prób kontaktu — po jednym zapytaniu na tablicę.
    from sqlalchemy import func, or_

    from app.models.note import Note as _Note
    from app.services import (
        note_kinds,
        recommendation_cards,
        screening_sheets,
    )

    from app.services import candidate_rate_change as _rate_change

    job_has_questions = bool(screening_sheets.question_texts(job.champion_profile))
    # Pola, które klient dokłada do minimum dla DL (karta klienta, D3).
    job_client_required, _ = await move_requirements.client_required_fields(
        db, job.client_id
    )
    # Para ma CV firmowe — ta sama reguła co wymaganie ruchu na „QC CV”
    # (`company_cv_refs`, hurtem: najwyżej 4 zapytania na tablicę). Karta
    # z „Zweryfikowanego” wie przed ruchem, że CV brakuje (14.10.2026).
    company_cv_pairs = (
        set(
            await move_requirements.company_cv_refs(
                db, [(cid, job_id) for cid in candidate_ids]
            )
        )
        if with_cv_state
        else None
    )
    # 0521 (26.10.2026): klient bierze formularz CV — karta pokazuje stan
    # formularza zamiast CV firmowego. `None` = klient bierze CV firmowe.
    from app.services import client_form_status

    client_forms = (
        await client_form_status.job_states(db, job_id, candidate_ids)
        if with_cv_state
        else None
    )
    # „Do wysłania do klienta” (`dl_send_queue`): kolejka Delivery Leada bierze
    # tylko opublikowane rekrutacje, a etap z importu Traffita nie liczy się do
    # „Czeka na Ciebie” — karta mówi to samo co pas na pulpicie (audyt 13.10.2026).
    from app.services.dl_send_queue import TRAFFIT_SOURCE

    dl_send_job = job.status == JobStatus.published

    # 0418: otwarta sprawa zmiany stawki pary — plakietka na karcie.
    rate_change_by_candidate = await _rate_change.open_badges_for_job(db, job_id=job_id)
    card_by_candidate = await recommendation_cards.summaries_for_job(
        db,
        job_id=job_id,
        started_by_candidate={
            cid: recommendation_cards.attempt_started(v4_processes.get(cid))
            for cid in candidate_ids
        },
    )
    contact_attempts: dict[int, int] = {}
    if candidate_ids:
        contact_attempts = {
            cid: int(total)
            for cid, total in (
                await db.execute(
                    select(_Note.candidate_id, func.count(_Note.id))
                    .where(
                        _Note.candidate_id.in_(sorted(candidate_ids)),
                        _Note.kind == note_kinds.CONTACT_ATTEMPT,
                        or_(_Note.job_id == job_id, _Note.job_id.is_(None)),
                    )
                    .group_by(_Note.candidate_id)
                )
            ).all()
        }
    # 0372: follow-up z kandydatem, gdy klient milczy — liczony dla OSOBY (ze
    # wszystkimi jej procesami), na karcie tylko przy procesie, który czeka.
    from app.services import candidate_followups

    followups = (
        await candidate_followups.load_followups_safely(
            db, now=board_now, candidate_ids=candidate_ids
        )
        if with_followups
        else {}
    )
    followup_today = candidate_followups.local_date(board_now)
    followup_names = await candidate_followups.user_names(
        db, (f.caller_id for f in followups.values())
    )

    def _followup_badge(candidate_id: int) -> Optional[dict]:
        f = followups.get(candidate_id)
        if f is None or all(p.job_id != job_id for p in f.processes):
            return None
        return {
            "caller_id": f.caller_id,
            "caller_name": followup_names.get(f.caller_id) if f.caller_id else None,
            "due_on": f.due_on.isoformat(),
            "state": f.state(followup_today),
            "overdue_days": f.overdue_days(followup_today),
            "process_count": len(f.processes),
        }

    def _stage_resp_with_name(e: CandidateStage) -> dict:
        n, ln = name_by_id.get(e.candidate_id, (None, None))
        first = earliest.get(e.candidate_id)
        added_by_name = (
            user_name_by_id.get(first.moved_by)
            if first is not None and first.moved_by is not None
            else None
        )
        added_at = first.moved_at if first is not None else None
        verified = first_verified.get(e.candidate_id)
        payload = _stage_response(
            e,
            show_client_rate=show_client_rate,
            candidate_name=n,
            candidate_lastname=ln,
            added_to_job_by_name=added_by_name,
            added_to_job_by_id=first.moved_by if first is not None else None,
            added_to_job_at=added_at,
            verified_by_name=(
                user_name_by_id.get(verified.moved_by)
                if verified is not None and verified.moved_by is not None
                else None
            ),
            verified_by_id=verified.moved_by if verified is not None else None,
            verified_at=verified.moved_at if verified is not None else None,
            candidate_expected_rate_hourly=profile_rate_by_id.get(e.candidate_id),
        )
        # Rekrutacja bez pytań: karta mówi o „Dlaczego ten kandydat”, nie
        # o arkuszu, którego tam nie ma (ta sama reguła co bramka ruchu).
        (
            payload["screening_done"],
            payload["screening_requirement"],
        ) = move_requirements.card_screening_state(
            has_questions=job_has_questions,
            sheet=e.candidate_id in screened_pairs,
            card=card_by_candidate.get(e.candidate_id),
        )
        payload["candidate_rate_from_hourly"] = rate_from_by_id.get(e.candidate_id)
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
        payload["auto_cv_state"] = (
            "processing" if e.id in generating_stage_ids else None
        )
        payload["company_cv"] = (
            (e.candidate_id, job_id) in company_cv_pairs
            if company_cv_pairs is not None
            else None
        )
        form_state = client_forms.get(e.candidate_id) if client_forms else None
        payload["client_form"] = (
            {"template": form_state.template is not None, "missing": form_state.missing}
            if form_state is not None
            else None
        )
        payload["qc"] = qc_by_pair.get((e.candidate_id, job_id))
        payload["dl_send_counts"] = dl_send_job and e.external_source != TRAFFIT_SOURCE
        card = card_by_candidate.get(e.candidate_id)
        payload["card"] = (
            {
                "status": card["status"],
                "missing": len(card["missing"]),
                "answers": card["answers"],
                "rate_hourly": card["rate_hourly"],
            }
            if card is not None
            else None
        )
        payload["contact_attempts"] = contact_attempts.get(e.candidate_id, 0)
        # Rekruter karty: przypisany „Prowadzi”, potem właściciel procesu
        # (Priority Work), a gdy proces go nie ma — osoba, która dodała
        # kandydata do rekrutacji.
        assigned = pair_owners.get(e.candidate_id)
        process_owner = process_cards.get(e.candidate_id, (0, None))[1]
        recruiter_id = (
            assigned.owner_user_id
            if assigned is not None
            else process_owner
            if process_owner is not None
            else (first.moved_by if first is not None else None)
        )
        payload["recruiter_id"] = recruiter_id
        payload["recruiter_name"] = (
            assigned.owner_name
            if assigned is not None
            else user_name_by_id.get(recruiter_id)
            if recruiter_id is not None
            else None
        )
        if assigned is not None:
            payload["owner_user_id"] = assigned.owner_user_id
            payload["owner_name"] = assigned.owner_name
            payload["owner_assigned_by_name"] = assigned.assigned_by_name
            payload["owner_assigned_at"] = assigned.assigned_at
            payload["owner_previous_name"] = assigned.previous_owner_name
        if e.task_assignee_id is not None:
            payload["task_assignee_name"] = user_name_by_id.get(e.task_assignee_id)
        if e.stage in _CLOSED_CARD_STAGES:
            payload["closed_by_name"] = (
                user_name_by_id.get(e.moved_by) if e.moved_by is not None else None
            )
            payload["rejection_reason_name"] = (
                reason_name_by_id.get(e.rejection_reason_id)
                if e.rejection_reason_id is not None
                else None
            )
        payload["interview_badge"] = interview_badges.get(e.candidate_id)
        payload["followup"] = _followup_badge(e.candidate_id)
        payload["rate_change"] = rate_change_by_candidate.get(e.candidate_id)
        if e.stage in HIRED_STAGES:
            payload["order_status"] = order_statuses.get((e.candidate_id, job_id))
            payload["missing_contract"] = e.candidate_id in missing_contracts
        payload["agreement"] = agreements.get(e.candidate_id)
        payload["client_acceptance"] = _client_acceptance_badge(
            latest_acceptance.get(e.candidate_id), user_name_by_id
        )
        payload["employment_marker"] = employment_markers.get(e.candidate_id)
        payload["pre_contract"] = pre_contract_badges.get(e.candidate_id)
        payload["other_open_jobs"] = other_open_jobs.get(e.candidate_id) or []
        payload["is_champion"] = e.candidate_id in champion_ids
        v4 = v4_processes.get(e.candidate_id)
        if v4 is not None:
            payload["entry_source"] = v4.entry_source
            payload["entry_auto_match"] = auto_match_badge(v4.entry_meta)
            payload["entry_autofill"] = (
                autofill_badge(
                    v4.entry_meta,
                    waiting_days=autofill_decisions.waiting_days(
                        meta=v4.entry_meta,
                        entered_at=v4.opened_at,
                        recruiter_since=autofill_recruiter_since,
                        now=board_now,
                    ),
                )
                if v4.entry_source == candidate_claim.ENTRY_SYSTEM
                else None
            )
            payload["entry_ai_screening"] = application_screening_badge(v4.entry_meta)
            payload["entry_off_limits"] = off_limits_badge(
                v4.entry_meta, user_name_by_id
            )
            link_owner = link_owner_by_candidate.get(e.candidate_id)
            if link_owner is not None:
                payload["entry_link_owner_id"] = link_owner
                payload["entry_link_owner_name"] = user_name_by_id.get(link_owner)
            payload["reapplied_via_links"] = [
                {"owner_id": uid, "owner_name": user_name_by_id.get(uid)}
                for uid in reapplied_link_owners.get(e.candidate_id, ())
            ]
            payload["reassign_from_job_id"] = v4.reassign_from_job_id
            if v4.reassign_from_job_id is not None:
                payload["reassign_from_title"] = reassign_titles.get(
                    v4.reassign_from_job_id
                )
                payload["reassign_from_reference"] = reassign_refs.get(
                    v4.reassign_from_job_id
                )
            claim = candidate_claim.claim_state(v4, inactive_claimers)
            if claim.active(board_now):
                payload["claim_user_id"] = claim.user_id
                payload["claim_user_name"] = user_name_by_id.get(claim.user_id)
                payload["claim_until"] = claim.until
            # „Biorę” zmienia osobę karty (prośba rekruterki, decyzja Artura
            # 27.10.2026): ostatnia osoba, która wzięła, zostaje na karcie
            # i w filtrze „Kto dodał” także po 12 h — do pierwszej weryfikacji.
            if claim.user_id is not None and first_verified.get(e.candidate_id) is None:
                payload["taken_by_user_id"] = claim.user_id
                payload["taken_by_name"] = user_name_by_id.get(claim.user_id)
            if viewer is not None:
                payload["can_take"] = candidate_claim.can_take(
                    v4, viewer, board_now, inactive_claimers
                )
        elif viewer is not None:
            payload["can_take"] = True
        availability = availability_by_id.get(e.candidate_id, (None, None))
        payload["availability_status"] = availability[0]
        payload["availability_date"] = availability[1]
        # Minimum dla DL (21.10.2026): strzałka i „Przesuń dalej” znają braki
        # przed ruchem — ta sama reguła co bramka serwera.
        payload["minimum_missing"] = move_requirements.board_minimum_missing(
            card_by_candidate.get(e.candidate_id),
            has_questions=job_has_questions,
            availability_known=availability[1] is not None,
            screening_met=bool(payload["screening_done"]),
            client_required=job_client_required,
        )
        # 22.10.2026: ruch DL-a mimo braków — na karcie zostają tylko braki,
        # których dalej brakuje (uzupełnione gaszą odznakę).
        skipped = skipped_by_candidate.get(e.candidate_id)
        if skipped is not None:
            still_missing = _still_missing(skipped[0], payload)
            if still_missing:
                payload["requirements_skipped"] = still_missing
                payload["requirements_skipped_by_name"] = (
                    user_name_by_id.get(skipped[1]) if skipped[1] is not None else None
                )
        in_base_at, in_base_exact, in_base_by = added_to_base_by_id.get(
            e.candidate_id, (None, False, None)
        )
        payload["candidate_added_at"] = in_base_at
        payload["candidate_added_exact"] = in_base_exact
        payload["candidate_added_by_name"] = (
            user_name_by_id.get(in_base_by) if in_base_by is not None else None
        )
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
            _newest_first(seen.values()), stage_defs, foreign_defs
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
            viewer_owns_dl_review=viewer_owns_dl_review,
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
    for stage_entry in _newest_first(seen.values()):
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
        viewer_owns_dl_review=viewer_owns_dl_review,
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
    from app.api.jobs import (  # noqa: PLC0415 — import cycle
        _live_work_assignment_job_ids,
        jobs_mine_working_clause,
    )

    # Runda 10 (R10-V2-2): członkostwo filtrujemy w SQL PRZED LIMIT — inaczej
    # rekrutacje odrzucane niżej (samo przypisanie, usunięty współpracownik)
    # zjadały miejsca i wypychały własne rekrutacje osoby.
    jobs = (
        await db.scalars(
            select(Job)
            .options(selectinload(Job.client))
            .where(
                # „Poprzedni rekruter” (14.10.2026) nie ma tu następnych kroków.
                jobs_mine_working_clause(current_user),
                Job.status != JobStatus.closed,
                job_scope_clause(current_user, Job.id, oversight_bypass=False),
            )
            .order_by(Job.deadline.asc().nullslast(), Job.id.desc())
            # One extra row tells a full page from a cut list.
            .limit(MY_NEXT_STEPS_JOB_LIMIT + 1)
        )
    ).all()
    truncated = len(jobs) > MY_NEXT_STEPS_JOB_LIMIT
    jobs = jobs[:MY_NEXT_STEPS_JOB_LIMIT]
    # Aktywne przypisanie z przydziału to „moja” rekrutacja (R9-N15-2) — dla
    # nich decyduje zakres w SQL wyżej. Od 02.10.2026 zna je też bramka
    # tablicy (`is_member_of_job`); ten zbiór oszczędza jej zapytań.
    assigned_job_ids = (
        set(await db.scalars(_live_work_assignment_job_ids([current_user.id])))
        if user_can_access_candidate_domain(current_user)
        else set()
    )
    out: list[MyNextStepsJob] = []
    # „Czyj przegląd” raz na żądanie, nie raz na tablicę (audyt 13.10.2026).
    dl_review_memo: dict[Any, Any] = {}
    for job in jobs:
        try:
            # The board read guard is the one that decides (`jobs_mine_clause`
            # is a list scope, not an access rule). Widok OSOBISTY:
            # od 23.09.2026 tablicę każdej rekrutacji czyta każdy, więc
            # przypisanie liczymy jawnie (`oversight_bypass=False`).
            if job.id not in assigned_job_ids:
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
                # Follow-up (0372) liczy ~14 zapytań na tablicę — „Moje
                # następne kroki” składa do 25 tablic, a plakietki nie pokazuje.
                # Stan CV firmowego (14.10.2026) też nie: `company_cv=None`
                # znaczy „nie wiadomo” i niczego nie blokuje.
                view=await build_kanban_view(
                    db,
                    job,
                    viewer=current_user,
                    with_followups=False,
                    with_employment=False,
                    with_cv_state=False,
                    with_other_jobs=False,
                    dl_review_memo=dl_review_memo,
                ),
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
# `candidate_id` zawęża dziennik do jednej osoby (panel osoby): filtr stoi w CTE,
# bo okno jest partycjonowane po kandydacie — odpada cała partycja, a LAG dalej
# widzi komplet ruchów tej pary.
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
          AND (CAST(:candidate_id AS INTEGER) IS NULL OR cs.candidate_id = :candidate_id)
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
    "SELECT COUNT(*) FROM candidate_stages cs WHERE cs.job_id = :job_id "
    "AND (CAST(:candidate_id AS INTEGER) IS NULL OR cs.candidate_id = :candidate_id)"
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
    candidate_id: Optional[int] = Query(None, ge=1),
    db: AsyncSession = Depends(get_db),
):
    """Ruchy etapów całej rekrutacji, od najnowszych.

    Ta sama bramka co tablica: odczyt sekcji Pipeline (router) + zakres
    rekrutacji. Imię i nazwisko kandydata tylko dla ról z odczytem kandydatów;
    pozostali dostają `candidate_id` i `candidate_names_redacted`.
    `candidate_id` = ruchy jednej osoby w tej rekrutacji (panel osoby).
    """
    job_exists = await db.scalar(select(Job.id).where(Job.id == job_id))
    if job_exists is None:
        raise HTTPException(status_code=404, detail="Job not found")
    await ensure_job_read_access(db, current_user, job_id)

    show_names = user_has_candidate_read(current_user)
    scope = {"job_id": job_id, "candidate_id": candidate_id}
    rows = (
        await db.execute(_JOB_MOVES_SQL, {**scope, "limit": limit, "offset": offset})
    ).all()
    if rows:
        total = int(rows[0].total)
    elif offset:
        # Strona za końcem listy nie niesie wiersza z `total`.
        total = int(await db.scalar(_JOB_MOVES_COUNT_SQL, scope) or 0)
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
    from app.services import screening_sheets
    from app.services.screening_suggestions import suggestions_from_notes

    candidate = await db.get(Candidate, stage.candidate_id)
    answers, source_stage_id = await screening_sheets.latest_filled_sheet(db, stage)
    # Arkusze sprzed 02.10.2026 nie niosą tekstu pytań — dok i profil czytają
    # go z odpowiedzi, więc uzupełniamy z bieżącego profilu po identyfikatorze.
    answers = screening_sheets.with_question_texts(
        answers, screening_sheets.question_texts(job.champion_profile if job else None)
    )
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
    from pydantic import ValidationError

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

    from app.services import screening_sheets

    # Ciało przychodzi jako słownik, więc błąd schematu nie jest błędem
    # żądania FastAPI — bez zamiany na 422 arkusz ponad limit (albo z nieznaną
    # wartością) kończył się 500 bez komunikatu.
    try:
        answers = ScreeningAnswers.model_validate(payload or {})
    except ValidationError as exc:
        too_long = any(
            error.get("type") in ("string_too_long", "too_long")
            for error in exc.errors()
        )
        raise HTTPException(
            status_code=422,
            detail=(
                "Arkusz screeningu jest za długi — skróć odpowiedzi albo notatkę."
                if too_long
                else "Arkusz screeningu ma nieprawidłowe dane."
            ),
        ) from None
    previous = stage.screening_answers
    if answers.answers and not _sheet_filled(previous):
        # Arkusz należy do pary — wiersz bez własnej kopii porównujemy
        # z najnowszym wypełnionym arkuszem tej pary.
        previous, _ = await screening_sheets.latest_filled_sheet(
            db, stage, for_write=True
        )
    # „Pomiń brakujące” tylko z powodem — ta sama bramka co formularz
    # (`PUT /screening-form`, audyt 13.10.2026, pkt 6).
    from app.services.screening_reassign import assert_skip_allowed

    await assert_skip_allowed(
        db,
        answers=answers.answers,
        previous=previous,
        candidate_id=stage.candidate_id,
        job_id=stage.job_id,
        user=current_user,
    )
    job = await db.scalar(select(Job).where(Job.id == stage.job_id))
    # Zapis człowieka przejmuje arkusz z notatki (07.10.2026): odpowiedzi
    # `note_sync` stają się `note_import`, więc automat już ich nie poprawi.
    from app.services.screening_note_sync import humanize_origins

    humanize_origins(answers)
    screening_sheets.stamp_sheet(
        answers,
        questions=screening_sheets.question_texts(
            getattr(job, "champion_profile", None)
        ),
        previous=previous,
        user_id=current_user.id,
        now=datetime.now(timezone.utc),
    )

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

# D2 (07.10.2026): z NEXUSA nic nie idzie do klienta — wszystko w formularzu
# screeningu jest dla Delivery Leada. Wystawienie linku do karty Championa
# odpowiada 410 bez sprawdzania rekrutacji (nic nie czyta ani nie zapisuje),
# a migracja 0424 odwołała wszystkie tokeny. Odwołanie (DELETE) zostaje.
CHAMPION_SHARE_REMOVED_MESSAGE = (
    "Udostępnianie karty Championa klientowi zostało wyłączone — formularz "
    "screeningu jest dla Delivery Leada, a CV do klienta wysyła DL."
)


@router.post("/stages/{stage_id}/share-token")
async def create_share_token(
    stage_id: int,
    current_user: RecruiterPlus,
):
    """Karta Championa dla klienta — wyłączona (410)."""
    raise HTTPException(
        status_code=410,
        detail={
            "code": "CHAMPION_SHARE_REMOVED",
            "message": CHAMPION_SHARE_REMOVED_MESSAGE,
        },
    )


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

    Wolną osobę (z propozycji, z ogłoszenia bez właściciela linku, po upływie
    blokady) bierze każdy z zespołu rekrutacji. Osoba, która zgłosiła się
    z linku rekrutacji, ma od wejścia do „Nowi” blokadę właściciela linku
    (etap 2 linków, 19.10.2026) — jak osoba dodana ręcznie. Cudzą, wciąż
    aktywną blokadę przejmuje wyłącznie admin, Delivery Lead albo Head of
    Recruitment — poprzedni rekruter dostaje dzwonek.
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
    previous = candidate_claim.claim_state(
        process, await candidate_claim.inactive_holders(db, [process])
    )
    # Runda 8 (R8-N8-7): własnej aktywnej blokady nie da się przedłużyć —
    # po 12 h każdy z zespołu może osobę przejąć (tablica: `can_take` = False).
    if previous.active(now) and previous.user_id == current_user.id:
        raise HTTPException(
            status_code=409,
            detail="Już prowadzisz tę osobę — blokady nie da się przedłużyć.",
        )
    previous_holder = (
        previous.user_id
        if previous.active(now) and previous.user_id != current_user.id
        else None
    )
    candidate_claim.set_claim(process, current_user.id, now)
    # Osoba od systemu (23.10.2026): „Dzwonię” to decyzja na stałe — po
    # wygaśnięciu blokady karta nie wraca do „Czeka na Ciebie”.
    from app.services.autofill_decisions import record_call

    record_call(process, current_user.id, now)
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
    # (poza Nordeą wymagana; wysyła osoba z uprawnieniem `recruitment_manage`,
    # domyślnie Delivery Lead i admin).
    client_rate_value: Decimal | None = Field(None, gt=0)
    client_rate_unit: RateUnit | None = None
    client_rate_currency: str | None = Field(None, max_length=3)


@router.post("/bulk-move")
async def bulk_move_candidates(
    data: BulkMoveRequest,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
    request: Request = None,  # type: ignore[assignment] — wywołania wprost w testach
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

    # Etap-odznaka Tablicy (DZ / Cpro) — ta sama reguła co pojedynczy /move.
    bulk_stage_def = await _resolve_stage_def(
        db, job, stage_def_id=None, legacy_stage=data.stage
    )
    if bulk_stage_def is not None:
        ensure_badge_stage_allowed(
            current_user, stage_name=bulk_stage_def.name, client_id=job.client_id
        )
    bulk_target_column = board_column_for(
        bulk_stage_def.name if bulk_stage_def else None,
        data.stage.value,
        category=(
            bulk_stage_def.category.value
            if bulk_stage_def and bulk_stage_def.category
            else None
        ),
        terminal_type=(
            bulk_stage_def.terminal_type.value
            if bulk_stage_def and bulk_stage_def.terminal_type
            else None
        ),
    )

    # Runda 9 (R9-N11-4): osoby spoza rekrutacji (para bez wiersza) wchodzą
    # tylko do „Nowych”/„Screeningu” i przez twardą bramkę — jak bulk-add.
    fresh_ids = [
        cid
        for cid in unique_ids
        if await _pair_has_no_stage(db, candidate_id=cid, job_id=job.id)
    ]
    if fresh_ids:
        try:
            _assert_fresh_pair_entry(bulk_stage_def, data.stage)
        except HTTPException as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail=f"{exc.detail} (kandydaci: {fresh_ids[:20]})",
            ) from None
        if candidate_claim.is_integration_request(request):
            # 06.10.2026: integracja nie wstawia nowych osób paczką bez dowodu
            # zgłoszenia do tej rekrutacji — propozycje idą przez
            # `proposals/bulk` (pojedynczy `/move` zakłada je sam).
            from app.services.integration_intake import (
                candidates_with_application_evidence,
            )

            applied = await candidates_with_application_evidence(
                db, job_id=job.id, candidate_ids=fresh_ids
            )
            unproven = [cid for cid in fresh_ids if cid not in applied]
            if unproven:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Integracja dodaje nowe osoby przez „Do przejrzenia” "
                        "(POST /api/jobs/{id}/proposals/bulk) — bez zgłoszenia "
                        f"do tej rekrutacji (kandydaci: {unproven[:20]})."
                    ),
                )

    # Pipeline v4: „CV wysłane" poza Nordeą — DL + stawka (jak pojedynczy /move);
    # u Nordei akceptacja do kolejki Cpro (13.10.2026) — `bulk_stage_def` bywa
    # etapem Cpro (`_resolve_stage_def` z samego kodu etapu).
    # Runda 9 (R9-N11-6): tylko dla osób, które do klienta dopiero idą — cofnięcie
    # karty z „Rozmowy u klienta” to nie wysłanie.
    dl_send = False
    bulk_stage_name = bulk_stage_def.name if bulk_stage_def else None
    if pipeline_move_rules.requires_dl_client_rate(
        data.stage, job.client_id, stage_name=bulk_stage_name
    ):
        for cid in unique_ids:
            if await pipeline_move_rules.arrives_from_before_client_send(
                db, candidate_id=cid, job_id=job.id
            ):
                dl_send = True
                break
    if dl_send:
        pipeline_move_rules.assert_client_send_allowed(
            current_user,
            data.client_rate_value,
            cpro=cpro_enabled_for_client(job.client_id),
        )
    elif data.client_rate_value is not None and not await resolve_client_rate_write(
        db, current_user, job
    ):
        raise client_rate_write_denied()
    if data.client_rate_value is not None:
        # Jak pojedynczy /move: osoba z zamówieniem zatrzymuje całą paczkę.
        for cid in unique_ids:
            await _assert_client_rate_not_order_locked(
                db, candidate_id=cid, job_id=job.id
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
        await _spend_advisory_qc_override_on_return(
            db,
            candidate_id=cid,
            job_id=job.id,
            stage_def=bulk_stage_def,
            legacy_value=data.stage.value,
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
    # Runda 9 (R9-N11-3): weto z kolumny docelowej; osoby spoza rekrutacji
    # zawsze z wetem (jak bulk-add).
    moving_ids = [cid for cid in unique_ids if cid not in fresh_ids]
    if moving_ids:
        await assert_candidates_move_eligible(
            db,
            candidate_ids=moving_ids,
            job=job,
            now=datetime.now(timezone.utc),
            enforce_manager_verdict=puts_column_before_client(bulk_target_column),
        )
    if fresh_ids:
        await assert_candidates_move_eligible(
            db,
            candidate_ids=fresh_ids,
            job=job,
            now=datetime.now(timezone.utc),
        )

    # Pipeline v4: debrief po rozmowie u klienta — jak pojedynczy /move.
    for cid in unique_ids:
        await pipeline_move_rules.assert_debrief_before_contract(
            db, candidate_id=cid, job_id=data.job_id, target_column=bulk_target_column
        )
    # D1 jak pojedynczy /move: skok z Nowych/Screeningu ponad „Zweryfikowany”
    # wymaga arkusza i stawki (audyt 05.10.2026 — bulk tej bramki nie wołał).
    for cid in unique_ids:
        await pipeline_move_rules.assert_verified_requirements(
            db,
            candidate_id=cid,
            job=job,
            user=current_user,
            target_column=bulk_target_column,
            pending_rate=False,
            # Ruch zbiorczy nie zapisuje śladu `requirements_skipped` — bramka
            # pól obowiązuje tu także Delivery Leada (22.10.2026).
            allow_skip=False,
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
    bulk_display_name = (
        bulk_stage_def.name
        if bulk_stage_def
        else STAGE_LABELS.get(data.stage, data.stage.value)
    )
    # (etap, poprzedni wiersz) — do powiadomień po commicie, jak w /move.
    moved_entries: list[tuple[CandidateStage, Optional[CandidateStage]]] = []
    for cid in unique_ids:
        previous_row = await db.scalar(
            select(CandidateStage)
            .where(
                CandidateStage.candidate_id == cid,
                CandidateStage.job_id == data.job_id,
            )
            .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
            .limit(1)
        )
        entry = await transition_process(
            db,
            candidate_id=cid,
            job_id=data.job_id,
            stage=data.stage,
            # Runda 8 (R8-N8-6): wiersz z paczki niesie etap szablonu jak
            # pojedynczy /move — kolejka Cpro i tablica filtrują po nim.
            stage_def_id=bulk_stage_def.id if bulk_stage_def else None,
            moved_at=datetime.now(timezone.utc),
            actor_user_id=current_user.id,
            work_channel=PriorityChannel.database,
            notes=data.notes,
            **bulk_rate,
            # Runda 11 (PIPE-1): osoba spoza rekrutacji dodana paczką dostaje
            # to samo źródło wejścia i blokadę 12 h co pojedynczy /move.
            **(
                _fresh_pair_entry_kwargs(current_user, request)
                if cid in fresh_ids
                else {}
            ),
        )
        if not candidate_claim.is_integration_request(request):
            await candidate_claim.take_unowned_on_screening(
                db, previous=previous_row, moved=entry, user_id=current_user.id
            )
        await create_original_cv_snapshot(db, entry)
        await maybe_ensure_contact_opportunity(
            db,
            candidate_id=cid,
            job_id=data.job_id,
            source="pipeline",
            occurred_at=entry.moved_at,
        )
        # Runda 9 (R9-N11-7): te same ślady co pojedynczy /move.
        _record_stage_change(
            db,
            stage=entry,
            stage_def=bulk_stage_def,
            legacy_enum=data.stage,
            actor_id=current_user.id,
            stage_display_name=bulk_display_name,
            extra_details={"bulk": True},
        )
        await _cancel_pending_rejection_emails(
            db,
            candidate_id=cid,
            job_id=data.job_id,
            actor_id=current_user.id,
            restored_to=data.stage,
        )
        await stage_handoff_recipients.close_cpro_queue_bells(
            db, previous=previous_row, target_name=bulk_stage_name
        )
        moved_entries.append((entry, previous_row))
        moved += 1

    # 0341: przepięcia do połączonych rekrutacji (jak w pojedynczym /move).
    from app.services.job_similarity import on_candidate_sent  # noqa: PLC0415

    bulk_stage = _client_hook_stage(bulk_target_column, data.stage)
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

    # Efekty po commicie — każdy w savepoincie (`_post_commit_effect`), osobno
    # dla każdej osoby: błąd jednej nie cofa efektów pozostałych i nie wygasza
    # obiektów sesji. Do rundy 2 audytu (25.09.2026) `db.rollback()` po
    # błędzie wygaszał `current_user`, kolejne odczyty `current_user.id`
    # kończyły się połykanym MissingGreenlet, a reszta paczki nie trafiała do
    # pul talentów (commit był dopiero po pętli).
    for entry, previous_row in moved_entries:
        await _post_commit_effect(
            db,
            f"bulk stage_notif stage={entry.id}",
            _notify_stage_change_effect(
                db,
                stage=entry,
                previous_stage_row=previous_row,
                job=job,
                mover=current_user,
                stage_display_name=bulk_display_name,
            ),
        )
        _spawn_cv_qc_after_move(bulk_target_column, entry.id, actor_id)

    from app.services.candidate_risk import on_candidate_stage_change

    for cid in unique_ids:

        async def _recompute_risk(cid: int = cid) -> None:
            await on_candidate_stage_change(db, cid)

        await _post_commit_effect(
            db, f"bulk risk recompute candidate={cid}", _recompute_risk
        )

    # Auto-add to a talent pool when the bulk move is "CV → klient" (same
    # signal as the single /move path). Best-effort: a failure must not affect
    # the move that already committed above.
    if data.stage == PipelineStage.cv_sent:
        from app.services.talent_pool_auto_add import auto_add_on_cv_sent

        pool_job = await db.scalar(select(Job).where(Job.id == data.job_id))
        if pool_job is not None:
            for cid in unique_ids:

                async def _auto_add_to_pool(cid: int = cid) -> None:
                    pool_candidate = await db.scalar(
                        select(Candidate).where(Candidate.id == cid)
                    )
                    await auto_add_on_cv_sent(
                        db=db,
                        candidate_id=cid,
                        job=pool_job,
                        user_id=actor_id,
                        candidate=pool_candidate,
                    )

                await _post_commit_effect(
                    db,
                    f"bulk auto_add_on_cv_sent candidate={cid} job={data.job_id}",
                    _auto_add_to_pool,
                )

    return {"moved": moved, "stage": data.stage.value, "job_id": data.job_id}
