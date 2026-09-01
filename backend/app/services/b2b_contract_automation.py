"""Idempotent Candidate → B2B Contract/Order employment automation.

The generator, pipeline and manual signature confirmation all need the same
answer to "does this recruitment already have a contractor?".  This service is
the single transactional implementation.  It never commits: the caller owns
the transaction and may compose the returned draft with other audit changes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.activity import Activity
from app.models.b2b_contract_detail import B2BContractDetail
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.candidate import Candidate
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus, ContractType, RateUnit
from app.models.contract_candidate_rate import ContractCandidateRate
from app.models.job import Job
from app.models.order_type import OrderType
from app.models.pipeline_template import PipelineStageDef, PipelineTemplate
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.services.candidate_contact_hooks import maybe_close_contact_opportunity
from app.services.cost_orders import skips_standard_order_automation
from app.services.multi_consultant_orders import is_multi_consultant_client
from app.services.order_engagement_separation import has_open_group_line
from app.services.order_rate_snapshots import inherited_order_rate_fields
from app.services.order_types import suggested_order_type
from app.services.priority_work_policy import PriorityWorkLocked
from app.services.recruitment_process_commands import transition_process

logger = logging.getLogger(__name__)


_COMPATIBLE_CONTRACT_STATUSES = (
    ContractStatus.draft,
    ContractStatus.ready_for_signature,
    ContractStatus.active,
    ContractStatus.ending,
)
_OPEN_ORDER_STATUSES = (
    ClientOrderStatus.draft,
    ClientOrderStatus.active,
    ClientOrderStatus.paused,
)


@dataclass(frozen=True)
class B2BEmploymentDraftResult:
    contract: Contract
    order: ClientOrder | None
    created_contract: bool
    created_order: bool
    created_hired_stage: bool


def _payload_value(payload: Any | None, name: str) -> Any | None:
    if payload is None:
        return None
    return getattr(payload, name, None)


def _conflict_detail(
    message: str,
    *,
    contract_ids: list[int],
    order_ids: list[int] | None = None,
) -> dict[str, object]:
    detail: dict[str, object] = {
        "message": message,
        "contract_ids": contract_ids,
    }
    if order_ids is not None:
        detail["order_ids"] = order_ids
    return detail


def _raise_conflict(contract: Contract, details: list[str]) -> None:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=_conflict_detail(
            (
                "Istniejący kontraktor ma inne niepuste warunki: "
                + ", ".join(details)
                + ". Otwórz istniejący kontrakt i wyjaśnij konflikt ręcznie."
            ),
            contract_ids=[contract.id],
        ),
    )


async def _is_skeletal_pipeline_draft(
    db: AsyncSession,
    contract: Contract,
    detail: B2BContractDetail | None,
) -> bool:
    """Recognize the placeholder draft created by the hired-stage hook.

    That legacy hook populated ``start_date=today`` plus model defaults for
    currency/rate unit while its own note still told Delivery to complete the
    dates and rates. Those defaults are not negotiated terms and must not make
    a later signed document look conflicting.
    """

    has_skeletal_shape = (
        contract.status == ContractStatus.draft
        and detail is None
        and contract.rate_candidate is None
        and contract.rate_client is None
        and not contract.candidate_rate_schedule
        and contract.draft_content_html is None
    )
    if not has_skeletal_shape:
        return False

    # Shape alone is not evidence of origin: a user may intentionally save an
    # incomplete manual draft with a negotiated date or currency. Only the
    # durable audit written by the hired-stage hook authorizes replacing its
    # placeholder defaults from the signed document.
    origin_activity_id = await db.scalar(
        select(Activity.id)
        .where(
            Activity.entity_type == "contract",
            Activity.entity_id == contract.id,
            Activity.action == "auto_drafted_from_pipeline",
        )
        .limit(1)
    )
    return origin_activity_id is not None


def _assert_compatible_terms(
    contract: Contract,
    detail: B2BContractDetail | None,
    payload: Any | None,
    *,
    signing_date: date | None,
    language: str | None,
    skeletal_pipeline_draft: bool,
) -> None:
    """Reject only material conflicts where both sides already carry a value."""

    conflicts: list[str] = []
    start_date = _payload_value(payload, "start_date")
    if (
        not skeletal_pipeline_draft
        and contract.start_date is not None
        and start_date is not None
    ):
        if contract.start_date != start_date:
            conflicts.append("data rozpoczęcia")

    candidate_rate = _payload_value(payload, "rate_candidate")
    if contract.rate_candidate is not None and candidate_rate is not None:
        if Decimal(str(contract.rate_candidate)) != Decimal(str(candidate_rate)):
            conflicts.append("stawka kandydata")

    currency = (_payload_value(payload, "currency") or "").strip().upper()
    if (
        not skeletal_pipeline_draft
        and contract.resolved_rate_candidate_currency
        and currency
        and contract.resolved_rate_candidate_currency != currency
    ):
        conflicts.append("waluta")

    if (
        not skeletal_pipeline_draft
        and contract.rate_unit
        and contract.rate_unit != RateUnit.hourly
    ):
        conflicts.append("jednostka stawki")

    payload_stages = _payload_value(payload, "rate_stages") or []
    if contract.candidate_rate_schedule and payload_stages:
        payload_start = _payload_value(payload, "start_date")
        expected = [
            (
                Decimal(str(stage.rate)),
                stage.effective_from or payload_start,
                stage.effective_to,
            )
            for stage in payload_stages
        ]
        current = [
            (
                Decimal(str(stage.rate)),
                stage.effective_from,
                stage.effective_to,
            )
            for stage in contract.candidate_rate_schedule
        ]
        if current != expected:
            conflicts.append("harmonogram stawek")
    elif contract.candidate_rate_schedule and candidate_rate is not None:
        # A document carrying one flat rate is materially different from an
        # existing progressive schedule, even if its first amount happens to
        # equal the cached ``rate_candidate``.
        conflicts.append("harmonogram stawek")

    effective_signing_date = _payload_value(payload, "signing_date") or signing_date
    if detail is not None and detail.signing_date and effective_signing_date:
        if detail.signing_date != effective_signing_date:
            conflicts.append("data podpisania")

    role_id = _payload_value(payload, "role_id")
    if detail is not None and detail.b2b_role_id and role_id:
        if detail.b2b_role_id != role_id:
            conflicts.append("rola B2B")

    if detail is not None and detail.language and language:
        if detail.language != language:
            conflicts.append("język umowy")

    if detail is not None:
        detail_pairs = (
            (
                "miasto realizacji",
                detail.project_city,
                _payload_value(payload, "project_city"),
            ),
            (
                "opis projektu",
                detail.project_description,
                _payload_value(payload, "project_description"),
            ),
            (
                "adres korespondencyjny",
                detail.correspondence_address,
                _payload_value(payload, "partner_correspondence_address")
                or _payload_value(payload, "correspondence_address"),
            ),
            (
                "stawka słownie",
                detail.rate_in_words,
                _payload_value(payload, "rate_in_words"),
            ),
            (
                "indywidualny zakres roli",
                detail.role_scope_override,
                _payload_value(payload, "scope_items_override"),
            ),
        )
        for label, existing_value, document_value in detail_pairs:
            if (
                existing_value not in (None, "", [])
                and document_value not in (None, "", [])
                and existing_value != document_value
            ):
                conflicts.append(label)

    if conflicts:
        _raise_conflict(contract, conflicts)


def _fill_contract_terms(
    contract: Contract,
    payload: Any | None,
    *,
    replace_skeletal_defaults: bool,
) -> None:
    """Fill only absent values; never overwrite a populated existing contract."""

    if replace_skeletal_defaults or contract.start_date is None:
        contract.start_date = _payload_value(payload, "start_date")
    if replace_skeletal_defaults or contract.rate_candidate is None:
        contract.rate_candidate = _payload_value(payload, "rate_candidate")
    payload_currency = _payload_value(payload, "currency")
    if replace_skeletal_defaults and payload_currency:
        contract.rate_candidate_currency = payload_currency
    elif not contract.rate_candidate_currency and payload_currency:
        contract.rate_candidate_currency = payload_currency
    if not contract.currency:
        # Legacy fallback for a pre-0248 skeletal record. ``currency`` stays
        # the client/revenue alias once that side is populated.
        contract.currency = payload_currency or "PLN"
    contract.rate_unit = RateUnit.hourly


async def _upsert_b2b_detail(
    db: AsyncSession,
    contract: Contract,
    existing_detail: B2BContractDetail | None,
    payload: Any | None,
    *,
    contract_number: str | None,
    signing_date: date | None,
    language: str | None,
    canonicalize_snapshot: bool,
) -> B2BContractDetail:
    detail = existing_detail
    if detail is None:
        detail = B2BContractDetail(contract_id=contract.id)
        # The relationship was eagerly loaded as ``None`` earlier in the same
        # identity map. Assigning through it prevents a subsequent selectinload
        # from reusing that stale value when /generate renders the draft.
        contract.b2b_detail = detail
        db.add(detail)

    values = {
        "contract_number": contract_number,
        "signing_date": signing_date,
        "project_city": _payload_value(payload, "project_city"),
        "project_description": _payload_value(payload, "project_description"),
        "correspondence_address": _payload_value(
            payload, "partner_correspondence_address"
        )
        or _payload_value(payload, "correspondence_address"),
        "rate_in_words": _payload_value(payload, "rate_in_words"),
        "b2b_role_id": _payload_value(payload, "role_id"),
        "role_scope_override": _payload_value(payload, "scope_items_override"),
    }
    for field, value in values.items():
        if getattr(detail, field) is None and value is not None:
            setattr(detail, field, value)
    if canonicalize_snapshot:
        if contract_number:
            detail.contract_number = contract_number
        if signing_date:
            detail.signing_date = signing_date
    if language and (not detail.language or detail.language == "pl"):
        detail.language = language
    return detail


def _seed_candidate_rate_schedule(
    contract: Contract,
    payload: Any | None,
    *,
    actor_id: int,
) -> None:
    """Persist render-time progressive rates only when the contract has none."""

    if contract.candidate_rate_schedule:
        return
    stages = _payload_value(payload, "rate_stages") or []
    start_date = _payload_value(payload, "start_date")
    if not stages or start_date is None:
        return
    contract.candidate_rate_schedule = [
        ContractCandidateRate(
            rate=stage.rate,
            effective_from=stage.effective_from or start_date,
            effective_to=stage.effective_to,
            created_by=actor_id,
        )
        for stage in stages
    ]


def should_auto_create_order(client_id: int | None) -> bool:
    """Czy hook zatrudnienia ma auto-tworzyć szkic zamówienia u tego klienta.

    U historycznych klientów z ``COST_ORDER_CLIENT_IDS`` (Polkomtel) — NIE.
    Zamówienie bywa tam kosztowe albo MD, a hook nie ma skąd znać typu.
    Cyfrowy Polsat jest jawnym wyjątkiem: standardowy typ nadal korzysta z
    legacy auto-szkicu, natomiast jego specjalne grupy kosztowe/MD operator
    zakłada osobno. Dlatego bramka polityki jest węższa od capability kosztowej.
    """
    return not skips_standard_order_automation(client_id)


async def _ensure_open_order(
    db: AsyncSession,
    *,
    contract: Contract,
    candidate: Candidate,
    job: Job,
    actor_id: int,
    source: str,
) -> tuple[ClientOrder | None, bool]:
    # Klient kosztowy: zero zamówienia z automatu — także zero dowiązywania
    # istniejących linii grupowych (i zero 409 przy dwóch otwartych liniach
    # tej samej osoby, co u Polkomtela jest legalne).
    if not should_auto_create_order(job.client_id):
        return None, False
    # Osoba obsadzona na żywej linii zamówienia MD/kosztowego JEST już opisana
    # zamówieniem u tego klienta. Auto-szkic okresowy byłby drugim zapisem tej
    # samej współpracy na tym samym kontrakcie — a wtedy zakończenie jednego
    # domyka drugie (zgłoszenie BNP/Polkomtel/BIK/Wedel). Cicho, nie 409:
    # zatrudnienie nie może się wywrócić przez zamówienie, które już jest.
    if await has_open_group_line(db, contract.id):
        return None, False
    orders = list(
        (
            await db.execute(
                select(ClientOrder)
                .where(
                    ClientOrder.contract_id == contract.id,
                    # Linie grup mają własny rejestr i własny cykl życia —
                    # hook standardowego zamówienia nigdy ich nie adoptuje.
                    ClientOrder.order_group_id.is_(None),
                    ClientOrder.status.in_(_OPEN_ORDER_STATUSES),
                )
                .order_by(ClientOrder.created_at.desc(), ClientOrder.id.desc())
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    if len(orders) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_conflict_detail(
                (
                    "Kontraktor ma więcej niż jedno otwarte zamówienie dla tej "
                    "rekrutacji. Zamknij duplikaty przed potwierdzeniem podpisu."
                ),
                contract_ids=[contract.id],
                order_ids=[order.id for order in orders],
            ),
        )
    if orders:
        order = orders[0]
        if order.client_id != job.client_id or (
            order.job_id is not None and order.job_id != job.id
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_conflict_detail(
                    (
                        "Otwarte zamówienie kontraktora wskazuje innego klienta "
                        "lub rekrutację."
                    ),
                    contract_ids=[contract.id],
                    order_ids=[order.id],
                ),
            )
        if order.job_id is None:
            order.job_id = job.id
        return orders[0], False

    candidate_name = f"{candidate.name} {candidate.lastname}".strip()
    from_signed_confirmation = source == "signed_generated_contract"
    suggested_type = await suggested_order_type(db, job.client_id)
    # U klienta wielo-konsultantowego tytuł szkicu to przyszły NUMER GRUPY
    # (materializacja przy aktywacji). Tytuł-imię przechodziłby bramkę
    # aktywacji jako „numer" i zakładał grupę „Jan Kowalski — Java Developer";
    # placeholder „(bez numeru)" jest przez bramkę odrzucany, więc szkic
    # czeka w zakładce Draft, aż DL wpisze prawdziwy numer. Widok standardowy
    # zostaje przy tytule-imieniu — tam tytuł jest etykietą karty, nie numerem.
    title = (
        "(bez numeru)"
        if is_multi_consultant_client(job.client_id)
        or suggested_type in (OrderType.cost, OrderType.md)
        else f"{candidate_name} — {job.title}"
    )
    order = ClientOrder(
        client_id=job.client_id,
        contract_id=contract.id,
        job_id=job.id,
        title=title,
        order_type=suggested_type.value,
        status=ClientOrderStatus.draft,
        start_date=contract.start_date,
        **inherited_order_rate_fields(contract),
        created_by_user_id=actor_id,
        notes=(
            (
                "Auto-utworzone po potwierdzeniu obustronnego podpisania umowy. "
                if from_signed_confirmation
                else "Auto-utworzone po zmianie etapu pipeline na zatrudniony. "
            )
            + "Uzupełnij stawkę klienta, daty i wgraj PDF zamówienia."
        ),
    )
    db.add(order)
    await db.flush()
    db.add(
        Activity(
            entity_type="client_order",
            entity_id=order.id,
            action=(
                "auto_drafted_from_signed_contract"
                if from_signed_confirmation
                else "auto_drafted_from_pipeline"
            ),
            user_id=actor_id,
            details={
                "contract_id": contract.id,
                "candidate_id": candidate.id,
                "job_id": job.id,
            },
        )
    )
    return order, True


async def _resolve_hired_stage_def(
    db: AsyncSession, job: Job
) -> PipelineStageDef | None:
    template_id = job.pipeline_template_id
    if template_id is None:
        template_id = await db.scalar(
            select(PipelineTemplate.id).where(PipelineTemplate.is_default.is_(True))
        )
    if template_id is None:
        return None
    return await db.scalar(
        select(PipelineStageDef)
        .where(
            PipelineStageDef.template_id == template_id,
            PipelineStageDef.legacy_enum_value == PipelineStage.hired.value,
        )
        .order_by(PipelineStageDef.order, PipelineStageDef.id)
        .limit(1)
    )


async def _ensure_hired_stage(
    db: AsyncSession,
    *,
    candidate: Candidate,
    job: Job,
    actor_id: int,
) -> bool:
    latest = await db.scalar(
        select(CandidateStage)
        .where(
            CandidateStage.candidate_id == candidate.id,
            CandidateStage.job_id == job.id,
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        .limit(1)
        .with_for_update()
    )
    if latest is not None and latest.stage == PipelineStage.hired:
        return False

    stage_def = await _resolve_hired_stage_def(db, job)
    try:
        stage = await transition_process(
            db,
            candidate_id=candidate.id,
            job_id=job.id,
            stage=PipelineStage.hired,
            stage_def_id=stage_def.id if stage_def else None,
            moved_at=datetime.now(timezone.utc),
            actor_user_id=actor_id,
            require_existing=True,
            notes="Auto: Zatrudniony (umowa podpisana obustronnie)",
        )
    except PriorityWorkLocked:
        # Podpis umowy jest nadrzędny, ale nie może wykreować nowej rekrutacji
        # jako efektu ubocznego. Brakujący proces uzupełnia HoR — 409 z polityki
        # wywróciłby całą transakcję i umowa nigdy nie zostałaby podpisana.
        logger.warning(
            "b2b hired stage skipped: no existing process for candidate %s / job %s",
            candidate.id,
            job.id,
        )
        return False
    # Etap zapisuje command service (writer fence), więc kolejka kontaktu
    # domyka się na jego wierszu — nie na własnym `CandidateStage`.
    await maybe_close_contact_opportunity(
        db,
        candidate_id=candidate.id,
        job_id=job.id,
        actor_user_id=actor_id,
        reason="pipeline_terminal:hired",
        occurred_at=stage.moved_at,
    )
    db.add(
        Activity(
            entity_type="pipeline",
            entity_id=stage.id,
            action="stage_changed",
            user_id=actor_id,
            details={
                "candidate_id": candidate.id,
                "job_id": job.id,
                "stage": PipelineStage.hired.value,
                "stage_def_id": stage.stage_def_id,
                "source": "b2b_generated_contract_signature",
            },
        )
    )
    return True


async def ensure_b2b_employment_draft(
    db: AsyncSession,
    *,
    candidate_id: int,
    job: Job,
    actor_id: int,
    payload: Any | None = None,
    contract_number: str | None = None,
    signing_date: date | None = None,
    language: str | None = None,
    default_start_date: date | None = None,
    ensure_order: bool = False,
    ensure_hired: bool = False,
    audit_source_generated_id: int | None = None,
    allowed_statuses: tuple[ContractStatus, ...] = _COMPATIBLE_CONTRACT_STATUSES,
    require_b2b: bool = True,
    ensure_detail: bool = True,
    validate_terms: bool = True,
    reject_signed_generated_link: bool = False,
) -> B2BEmploymentDraftResult:
    """Lock the candidate, then reuse/create exactly one compatible B2B draft.

    ``ensure_order`` and ``ensure_hired`` are enabled by the fully-signed and
    pipeline-hired paths. The regular generator can reuse the same contractor
    identity without prematurely marking employment.
    """

    if job.client_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Wybrana rekrutacja nie ma przypisanego klienta. "
                "Uzupełnij klienta przed utworzeniem kontraktora."
            ),
        )

    candidate = await db.scalar(
        select(Candidate).where(Candidate.id == candidate_id).with_for_update()
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="Kandydat nie istnieje")

    contracts = list(
        (
            await db.execute(
                select(Contract)
                .where(
                    Contract.candidate_id == candidate.id,
                    Contract.job_id == job.id,
                    Contract.status.in_(_COMPATIBLE_CONTRACT_STATUSES),
                )
                .options(
                    selectinload(Contract.b2b_detail),
                    selectinload(Contract.candidate_rate_schedule),
                )
                .order_by(Contract.created_at.desc(), Contract.id.desc())
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    if len(contracts) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_conflict_detail(
                (
                    "Dla kandydata i rekrutacji istnieje więcej niż jeden aktywny "
                    "kontrakt. Nie utworzono kolejnego — uporządkuj rekordy ręcznie."
                ),
                contract_ids=[contract.id for contract in contracts],
            ),
        )

    created_contract = not contracts
    skeletal_pipeline_draft = False
    if created_contract:
        contract = Contract(
            candidate_id=candidate.id,
            client_id=job.client_id,
            job_id=job.id,
            contract_type=ContractType.b2b,
            status=ContractStatus.draft,
            start_date=_payload_value(payload, "start_date") or default_start_date,
            rate_candidate=_payload_value(payload, "rate_candidate"),
            rate_unit=RateUnit.hourly if require_b2b else RateUnit.monthly,
            currency=_payload_value(payload, "currency") or "PLN",
            candidate_rate_schedule=[],
        )
        db.add(contract)
        await db.flush()
        existing_detail = None
    else:
        contract = contracts[0]
        existing_detail = contract.b2b_detail
        skeletal_pipeline_draft = await _is_skeletal_pipeline_draft(
            db,
            contract,
            existing_detail,
        )
        if contract.status not in allowed_statuses:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_conflict_detail(
                    (
                        f"Kontrakt #{contract.id} ma status "
                        f"'{contract.status.value}' i nie może być zmieniony "
                        "w tej operacji."
                    ),
                    contract_ids=[contract.id],
                ),
            )
        if require_b2b and contract.contract_type != ContractType.b2b:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_conflict_detail(
                    "Istniejący kontraktor dla tej rekrutacji nie jest umową B2B.",
                    contract_ids=[contract.id],
                ),
            )
        if contract.client_id != job.client_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_conflict_detail(
                    (
                        "Istniejący kontraktor wskazuje innego klienta niż wybrana "
                        "rekrutacja. Nie zmieniono żadnych danych."
                    ),
                    contract_ids=[contract.id],
                ),
            )
        if reject_signed_generated_link:
            signed_generated_id = await db.scalar(
                select(B2BGeneratedContract.id)
                .where(
                    B2BGeneratedContract.contract_id == contract.id,
                    B2BGeneratedContract.signature_status == "signed_both",
                )
                .limit(1)
            )
            if signed_generated_id is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=_conflict_detail(
                        (
                            "Kontrakt jest już powiązany z audytowanym "
                            "potwierdzeniem podpisanej umowy i nie może być "
                            "ponownie zmieniony przez generator."
                        ),
                        contract_ids=[contract.id],
                    ),
                )
        if require_b2b and validate_terms:
            _assert_compatible_terms(
                contract,
                existing_detail,
                payload,
                signing_date=signing_date,
                language=language,
                skeletal_pipeline_draft=skeletal_pipeline_draft,
            )

    if require_b2b:
        _fill_contract_terms(
            contract,
            payload,
            replace_skeletal_defaults=(
                not created_contract and skeletal_pipeline_draft
            ),
        )
        _seed_candidate_rate_schedule(contract, payload, actor_id=actor_id)
    if ensure_detail:
        await _upsert_b2b_detail(
            db,
            contract,
            existing_detail,
            payload,
            contract_number=contract_number,
            signing_date=signing_date,
            language=language,
            canonicalize_snapshot=audit_source_generated_id is not None,
        )
    await db.flush()

    order: ClientOrder | None = None
    created_order = False
    if ensure_order:
        order, created_order = await _ensure_open_order(
            db,
            contract=contract,
            candidate=candidate,
            job=job,
            actor_id=actor_id,
            source=(
                "signed_generated_contract"
                if audit_source_generated_id is not None
                else "pipeline"
            ),
        )

    created_hired_stage = False
    if ensure_hired:
        created_hired_stage = await _ensure_hired_stage(
            db,
            candidate=candidate,
            job=job,
            actor_id=actor_id,
        )

    if audit_source_generated_id is not None:
        db.add(
            Activity(
                entity_type="contract",
                entity_id=contract.id,
                action=(
                    "auto_drafted_from_generated_contract"
                    if created_contract
                    else "linked_to_generated_contract"
                ),
                user_id=actor_id,
                details={
                    "candidate_id": candidate.id,
                    "client_id": job.client_id,
                    "job_id": job.id,
                    "generated_contract_id": audit_source_generated_id,
                    "order_id": order.id if order else None,
                    "hired_stage_created": created_hired_stage,
                },
            )
        )

    return B2BEmploymentDraftResult(
        contract=contract,
        order=order,
        created_contract=created_contract,
        created_order=created_order,
        created_hired_stage=created_hired_stage,
    )
