"""Generator Umów B2B — katalog ról (CRUD) + generowanie umowy + eksport DOCX.

Reużywa istniejący system draftów: po `POST /generate` powstaje `Contract`
(typ b2b, status draft) z wyrenderowanym `draft_content_html`, więc działają
istniejące endpointy draftu (edycja Tiptap, render-pdf) oraz Autenti. DOCX jest
jedynym genuinnie nowym wyjściem (eksport na oryginalnym szablonie prawnym).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.concurrency import run_in_threadpool
from jinja2 import TemplateError
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.contract_access import ContractLegalAccess
from app.api.contract_templates import _jinja_env
from app.api.contracts import _load_contract_with_relations, _render_draft_body
from app.api.deps import AdminUser, TacPlus
from app.api.recruitment_access import ensure_job_membership
from app.core.database import get_db
from app.models.activity import Activity
from app.models.b2b_contract_detail import B2BContractDetail
from app.models.b2b_contract_role import B2BContractRole
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder
from app.models.contract import (
    Contract,
    ContractStatus,
    ContractType,
    RateUnit,
)
from app.models.contract_candidate_rate import ContractCandidateRate
from app.models.contract_template import ContractTemplate
from app.models.job import Job
from app.models.job_collaborator import JobCollaborator
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User, UserRole
from app.schemas.b2b_contract_generator import (
    B2BCompanyLookupResponse,
    B2BContractDetailResponse,
    B2BGenerateRequest,
    B2BGenerateResponse,
    B2BConfirmFullySignedRequest,
    B2BConfirmFullySignedResponse,
    B2BGeneratedContractItem,
    B2BGeneratedContractUpdate,
    B2BNextNumberResponse,
    B2BRenderHtmlResponse,
    B2BRenderRequest,
    B2BRoleCreate,
    B2BRoleResponse,
    B2BRoleUpdate,
    B2BUopCheckRequest,
    B2BUopCheckResponse,
)
from app.services.b2b_contract_automation import ensure_b2b_employment_draft
from app.services.b2b_contract_generator.clause_overrides import (
    apply_ops_html,
    overrides_for_client,
)
from app.services.b2b_contract_generator.docx_renderer import (
    normalize_language,
    render_contract_docx,
    render_from_context,
)
from app.services.b2b_contract_generator.registry_lookup import lookup_company
from app.services.b2b_contract_generator.render_context import build_render_context
from app.services.b2b_contract_generator.uop_check import (
    CVGeneratorAIError,
    check_employment_hallmarks,
)

router = APIRouter()

_DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _ascii_filename(name: str) -> str:
    """Transliteruj na ASCII i oczyść do bezpiecznej nazwy pliku."""
    norm = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in norm)
    return safe.strip("._") or "umowa"


def _contract_docx_filename(contract_number: str | None) -> str:
    """Publiczna nazwa pobieranego DOCX: ``Umowa B2B 1472-2026.docx``."""
    number = re.sub(r"\s*/\s*", "-", (contract_number or "").strip())
    label = _ascii_filename(number) if number else ""
    return f"Umowa B2B {label}.docx" if label else "Umowa B2B.docx"


def _docx_response(data: bytes, contract_number: str | None) -> Response:
    """Zwróć DOCX z nazwą widoczną dla frontendu także przez CORS."""
    filename = _contract_docx_filename(contract_number)
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Access-Control-Expose-Headers": "Content-Disposition, X-Contract-Number",
    }
    if contract_number:
        headers["X-Contract-Number"] = contract_number
    return Response(content=data, media_type=_DOCX_MEDIA, headers=headers)


def _has_signature_role(user: User) -> bool:
    return user.has_any_role(
        UserRole.admin,
        UserRole.delivery_lead,
        UserRole.tac,
    )


async def _require_signature_job_scope(db: AsyncSession, user: User, job: Job) -> None:
    await ensure_job_membership(db, user, job.id)


async def _validate_candidate_job_link(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
) -> tuple[Candidate, Job]:
    candidate = await db.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Kandydat nie istnieje")
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Rekrutacja nie istnieje")
    has_pipeline = await db.scalar(
        select(CandidateStage.id)
        .where(
            CandidateStage.candidate_id == candidate.id,
            CandidateStage.job_id == job.id,
        )
        .limit(1)
    )
    if has_pipeline is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Kandydat nie uczestniczy w wybranej rekrutacji. "
                "Nie utworzono powiązania ani kontraktora."
            ),
        )
    return candidate, job


async def _serialize_generated_contracts(
    db: AsyncSession,
    rows: list[B2BGeneratedContract],
    current_user: User,
) -> list[B2BGeneratedContractItem]:
    """One serializer for list, PATCH and signature command responses."""

    user_ids = {
        uid
        for row in rows
        for uid in (row.created_by, row.signed_by_user_id)
        if uid is not None
    }
    candidate_ids = {row.candidate_id for row in rows if row.candidate_id is not None}
    job_ids = {row.job_id for row in rows if row.job_id is not None}
    client_ids = {row.client_id for row in rows if row.client_id is not None}

    users: dict[int, str] = {}
    if user_ids:
        result = await db.execute(
            select(User.id, User.name).where(User.id.in_(user_ids))
        )
        users = {uid: name for uid, name in result.all()}

    candidates: dict[int, str] = {}
    if candidate_ids:
        result = await db.execute(
            select(Candidate.id, Candidate.name, Candidate.lastname).where(
                Candidate.id.in_(candidate_ids)
            )
        )
        candidates = {
            cid: f"{name} {lastname}".strip() for cid, name, lastname in result.all()
        }

    jobs: dict[int, Job] = {}
    if job_ids:
        result = await db.execute(select(Job).where(Job.id.in_(job_ids)))
        jobs = {job.id: job for job in result.scalars().all()}

    clients: dict[int, str] = {}
    if client_ids:
        result = await db.execute(
            select(Client.id, Client.name).where(Client.id.in_(client_ids))
        )
        clients = {cid: name for cid, name in result.all()}

    scoped_job_ids: set[int] = set()
    if _has_signature_role(current_user):
        if current_user.has_role(UserRole.admin):
            scoped_job_ids = set(job_ids)
        else:
            scoped_job_ids = {
                job.id
                for job in jobs.values()
                if current_user.id
                in {
                    job.recruiter_id,
                    job.delivery_lead_id,
                    job.tac_id,
                }
            }
            if job_ids:
                result = await db.execute(
                    select(JobCollaborator.job_id).where(
                        JobCollaborator.job_id.in_(job_ids),
                        JobCollaborator.user_id == current_user.id,
                        JobCollaborator.removed_from_auto_cc.is_(False),
                    )
                )
                scoped_job_ids.update(job_id for (job_id,) in result.all())

    is_admin = current_user.has_role(UserRole.admin)
    items: list[B2BGeneratedContractItem] = []
    for row in rows:
        is_signed = row.signature_status == "signed_both"
        can_manage = not is_signed and (is_admin or row.created_by == current_user.id)
        can_confirm = _has_signature_role(current_user) and not is_signed
        blocked_reason: str | None = None
        if is_signed:
            blocked_reason = "Umowa została już oznaczona jako podpisana obustronnie."
        elif not _has_signature_role(current_user):
            blocked_reason = (
                "Oznaczenie podpisu wymaga roli administratora, Delivery Lead lub TAC."
            )
            can_confirm = False
        elif row.job_id is not None and row.job_id not in scoped_job_ids:
            blocked_reason = "Brak przypisania do powiązanej rekrutacji."
            can_confirm = False

        job = jobs.get(row.job_id) if row.job_id is not None else None
        items.append(
            B2BGeneratedContractItem(
                # Zmiana statusu handlowego celowo NIE wygasa po podpisaniu:
                # wypowiedzenie i porozumienie o rozwiązaniu dotyczą właśnie
                # umów podpisanych. Blokuje ją wyłącznie brak uprawnień.
                can_change_status=is_admin or row.created_by == current_user.id,
                contract_status=row.contract_status,
                closure_reason=row.closure_reason,
                closure_reason_other=row.closure_reason_other,
                closure_date=row.closure_date,
                id=row.id,
                contract_number=row.contract_number,
                partner_name=row.partner_name,
                client_name=row.client_name,
                language=row.language,
                signing_date=row.signing_date,
                created_at=row.created_at.isoformat() if row.created_at else None,
                created_by_name=users.get(row.created_by),
                can_delete=can_manage,
                can_edit=can_manage,
                can_download=row.render_payload is not None,
                signature_status=row.signature_status,
                signature_source=row.signature_source,
                candidate_id=row.candidate_id,
                job_id=row.job_id,
                client_id=row.client_id,
                contract_id=row.contract_id,
                candidate_name=candidates.get(row.candidate_id),
                job_title=job.title if job else None,
                canonical_client_name=clients.get(row.client_id),
                signed_at=row.signed_at.isoformat() if row.signed_at else None,
                signed_by_name=users.get(row.signed_by_user_id),
                can_confirm_signed=can_confirm,
                blocked_reason=blocked_reason,
            )
        )
    return items


async def _serialize_generated_contract(
    db: AsyncSession,
    row: B2BGeneratedContract,
    current_user: User,
) -> B2BGeneratedContractItem:
    return (await _serialize_generated_contracts(db, [row], current_user))[0]


# ── Katalog ról ──────────────────────────────────────────────────────────────


@router.get("/roles", response_model=list[B2BRoleResponse])
async def list_roles(
    current_user: ContractLegalAccess,
    db: AsyncSession = Depends(get_db),
    include_inactive: bool = Query(False),
):
    """Lista ról (pogrupowanie wg `category_key` robi frontend)."""
    query = select(B2BContractRole)
    if not include_inactive:
        query = query.where(B2BContractRole.is_active.is_(True))
    query = query.order_by(B2BContractRole.display_order, B2BContractRole.name_pl)
    res = await db.execute(query)
    return list(res.scalars().all())


@router.post(
    "/roles", response_model=B2BRoleResponse, status_code=status.HTTP_201_CREATED
)
async def create_role(
    data: B2BRoleCreate,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    dup = await db.scalar(
        select(B2BContractRole.id).where(B2BContractRole.slug == data.slug)
    )
    if dup:
        raise HTTPException(status_code=409, detail="Rola o tym slug już istnieje")
    from app.data.b2b_roles import CATEGORY_LABELS

    if data.category_key not in CATEGORY_LABELS:
        raise HTTPException(
            status_code=422,
            detail=f"Nieznana kategoria: {data.category_key}",
        )
    cat_pl, cat_en = CATEGORY_LABELS[data.category_key]
    role = B2BContractRole(
        category_key=data.category_key,
        category_label_pl=cat_pl,
        category_label_en=cat_en,
        slug=data.slug,
        name_pl=data.name_pl,
        name_en=data.name_en,
        area_label_pl=data.area_label_pl,
        area_label_en=data.area_label_en,
        scope_pl=data.scope_pl,
        scope_en=data.scope_en,
        display_order=data.display_order,
    )
    db.add(role)
    # The slug check above is racy; the UNIQUE constraint on
    # b2b_contract_roles.slug is the real guard. Give the loser of a concurrent
    # create the same 409 as the read path, not a 500.
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="Rola o tym slug już istnieje"
        ) from None
    await db.refresh(role)
    return role


@router.get("/roles/{role_id}", response_model=B2BRoleResponse)
async def get_role(
    role_id: int,
    current_user: ContractLegalAccess,
    db: AsyncSession = Depends(get_db),
):
    role = await db.get(B2BContractRole, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Rola nie znaleziona")
    return role


@router.patch("/roles/{role_id}", response_model=B2BRoleResponse)
async def update_role(
    role_id: int,
    data: B2BRoleUpdate,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    role = await db.get(B2BContractRole, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Rola nie znaleziona")
    updates = data.model_dump(exclude_unset=True)
    if "category_key" in updates:
        from app.data.b2b_roles import CATEGORY_LABELS

        if updates["category_key"] not in CATEGORY_LABELS:
            raise HTTPException(status_code=422, detail="Nieznana kategoria")
        role.category_label_pl, role.category_label_en = CATEGORY_LABELS[
            updates["category_key"]
        ]
    for k, v in updates.items():
        setattr(role, k, v)
    await db.commit()
    await db.refresh(role)
    return role


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: int,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    role = await db.get(B2BContractRole, role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Rola nie znaleziona")
    # FK b2b_contract_details.b2b_role_id = ON DELETE SET NULL → bezpieczne.
    await db.delete(role)
    await db.commit()


# ── Generowanie umowy ────────────────────────────────────────────────────────


async def _b2b_template_for(db: AsyncSession, lang: str) -> ContractTemplate:
    tpl = await db.scalar(
        select(ContractTemplate).where(
            ContractTemplate.contract_type == "b2b",
            ContractTemplate.language == lang,
        )
    )
    if not tpl:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Brak szablonu umowy B2B ({lang}). "
                "Seed nie został uruchomiony — zrestartuj aplikację."
            ),
        )
    return tpl


@router.post("/generate", response_model=B2BGenerateResponse)
async def generate(
    payload: B2BGenerateRequest,
    current_user: ContractLegalAccess,
    db: AsyncSession = Depends(get_db),
):
    role = await db.get(B2BContractRole, payload.role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Rola nie znaleziona")
    lang = normalize_language(payload.language)
    tpl = await _b2b_template_for(db, lang)

    # 1. Utwórz lub wczytaj draft Contract (typ b2b).
    if payload.contract_id is not None:
        # selectinload harmonogramu: replace relacji niżej musi znać stan
        # bieżący (delete-orphan) — lazy-load w async wywala MissingGreenlet.
        contract = await db.scalar(
            select(Contract)
            .where(Contract.id == payload.contract_id)
            .options(selectinload(Contract.candidate_rate_schedule))
            .with_for_update()
        )
        if not contract:
            raise HTTPException(status_code=404, detail="Umowa nie znaleziona")
        if contract.contract_type != ContractType.b2b:
            raise HTTPException(status_code=409, detail="To nie jest umowa B2B")
        if contract.status != ContractStatus.draft:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": (
                        f"Kontrakt #{contract.id} ma status "
                        f"'{contract.status.value}' i nie może być edytowany "
                        "przez generator."
                    ),
                    "contract_ids": [contract.id],
                },
            )
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
                detail={
                    "message": (
                        "Kontrakt jest już powiązany z audytowanym "
                        "potwierdzeniem podpisanej umowy i nie może być "
                        "ponownie zmieniony przez generator."
                    ),
                    "contract_ids": [contract.id],
                },
            )
        if (
            (
                payload.candidate_id is not None
                and payload.candidate_id != contract.candidate_id
            )
            or (payload.job_id is not None and payload.job_id != contract.job_id)
            or (
                payload.client_id is not None
                and payload.client_id != contract.client_id
            )
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": (
                        "candidate_id, job_id lub client_id nie odpowiadają "
                        "istniejącemu draftowi."
                    ),
                    "contract_ids": [contract.id],
                },
            )
        if contract.job_id is not None:
            _, existing_job = await _validate_candidate_job_link(
                db,
                candidate_id=contract.candidate_id,
                job_id=contract.job_id,
            )
            if existing_job.client_id != contract.client_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "message": (
                            "Klient kontraktu nie odpowiada klientowi rekrutacji."
                        ),
                        "contract_ids": [contract.id],
                    },
                )
    else:
        # client_id można wyprowadzić z wybranej rekrutacji (job → klient).
        client_id = payload.client_id
        job: Job | None = None
        if payload.job_id and payload.candidate_id:
            _, job = await _validate_candidate_job_link(
                db,
                candidate_id=payload.candidate_id,
                job_id=payload.job_id,
            )
            if client_id is not None and client_id != job.client_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="client_id nie odpowiada klientowi wybranej rekrutacji",
                )
            client_id = job.client_id
        elif payload.job_id:
            job = await db.get(Job, payload.job_id)
            client_id = job.client_id if job else None
        if not payload.candidate_id or not client_id:
            raise HTTPException(
                status_code=422,
                detail="Wymagany candidate_id oraz client_id lub job_id z klientem",
            )
        if job is not None:
            ensured = await ensure_b2b_employment_draft(
                db,
                candidate_id=payload.candidate_id,
                job=job,
                actor_id=current_user.id,
                payload=payload,
                contract_number=payload.contract_number,
                signing_date=payload.signing_date,
                language=lang,
                allowed_statuses=(ContractStatus.draft,),
                # A draft is the generator's editable workspace. Identity,
                # client and lifecycle are still guarded by the shared
                # service, but form fields below intentionally replace its
                # current terms.
                validate_terms=False,
                reject_signed_generated_link=True,
            )
            contract = ensured.contract
        else:
            # Legacy ad-hoc path without a recruitment cannot be safely
            # deduplicated. New UI flows always send job_id.
            contract = Contract(
                candidate_id=payload.candidate_id,
                client_id=client_id,
                job_id=None,
                contract_type=ContractType.b2b,
                status=ContractStatus.draft,
                start_date=payload.start_date,
                rate_unit=RateUnit.hourly,
                currency=payload.currency,
            )
            db.add(contract)
            await db.flush()

    # 2. Pola finansowe/daty na Contract.
    contract.start_date = payload.start_date
    contract.rate_candidate = payload.rate_candidate
    contract.currency = payload.currency
    contract.rate_unit = RateUnit.hourly
    # Stawka progresywna → harmonogram `candidate_rate_schedule`. Formularz
    # generatora wysyła zawsze PEŁNY stan, więc replace bezwarunkowy: brak
    # `rate_stages` czyści harmonogram z poprzedniej generacji (inaczej stary
    # rozkład dalej sterowałby zdaniem o stawce w umowie). Reassignment =
    # replace (delete-orphan). Etap startowy bez „Obowiązuje od" dziedziczy
    # datę rozpoczęcia usług.
    contract.candidate_rate_schedule = [
        ContractCandidateRate(
            rate=s.rate,
            effective_from=s.effective_from or payload.start_date,
            effective_to=s.effective_to,
            created_by=current_user.id,
        )
        for s in (payload.rate_stages or [])
    ]
    if contract.candidate_rate_schedule:
        # Cache spójny z harmonogramem — etap obowiązujący dziś (wzorzec z
        # PATCH /api/contracts).
        contract.rate_candidate = contract.effective_candidate_rate(date.today())

    # 3. Upsert B2BContractDetail.
    detail = await db.scalar(
        select(B2BContractDetail).where(B2BContractDetail.contract_id == contract.id)
    )
    if detail is None:
        detail = B2BContractDetail(contract_id=contract.id)
        db.add(detail)
    detail.contract_number = payload.contract_number
    detail.signing_date = payload.signing_date
    detail.project_city = payload.project_city
    detail.project_description = payload.project_description
    detail.correspondence_address = payload.correspondence_address
    detail.rate_in_words = payload.rate_in_words
    detail.language = lang
    detail.b2b_role_id = role.id
    detail.role_scope_override = payload.scope_items_override
    await db.flush()

    # 4. Render draftu HTML z szablonu B2B (eager-load relacji incl. b2b_detail).
    contract = await _load_contract_with_relations(db, contract.id)
    contract.draft_content_html = await run_in_threadpool(
        _render_draft_body, tpl, contract
    )
    contract.draft_template_id = tpl.id
    contract.draft_updated_at = datetime.now(timezone.utc)
    contract.draft_updated_by = current_user.id

    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract.id,
            action="b2b_generated",
            user_id=current_user.id,
            details={"role": role.slug, "language": lang},
        )
    )
    await db.commit()
    return B2BGenerateResponse(
        contract_id=contract.id, draft_template_id=tpl.id, language=lang
    )


@router.get("/contracts/{contract_id}/detail", response_model=B2BContractDetailResponse)
async def get_detail(
    contract_id: int,
    current_user: ContractLegalAccess,
    db: AsyncSession = Depends(get_db),
):
    contract = await _load_contract_with_relations(db, contract_id)
    d = contract.b2b_detail
    return B2BContractDetailResponse(
        contract_id=contract.id,
        candidate_id=contract.candidate_id,
        client_id=contract.client_id,
        job_id=contract.job_id,
        role_id=d.b2b_role_id if d else None,
        language=(d.language if d else "pl"),
        contract_number=d.contract_number if d else None,
        signing_date=d.signing_date if d else None,
        start_date=contract.start_date,
        project_city=d.project_city if d else None,
        project_description=d.project_description if d else None,
        correspondence_address=d.correspondence_address if d else None,
        rate_candidate=contract.rate_candidate,
        currency=contract.currency,
        rate_in_words=d.rate_in_words if d else None,
        scope_items_override=d.role_scope_override if d else None,
    )


@router.get("/contracts/{contract_id}/docx")
async def download_docx(
    contract_id: int,
    current_user: ContractLegalAccess,
    db: AsyncSession = Depends(get_db),
    language: str | None = Query(None),
):
    contract = await _load_contract_with_relations(db, contract_id)
    detail_lang = contract.b2b_detail.language if contract.b2b_detail else "pl"
    lang = normalize_language(language or detail_lang)
    data = await run_in_threadpool(render_contract_docx, contract, language=lang)

    number = contract.b2b_detail.contract_number if contract.b2b_detail else None
    return _docx_response(data, number)


# ── Numeracja umów (auto, uwzględnia wcześniej wygenerowane) ──────────────────

# Numer umowy w formacie „<liczba>/<rok>" (np. „1434/2026"). Prefiks liczbowy
# jest faktycznym numerem porządkowym — kolumna `seq` to tylko licznik wierszy.
_NUMBER_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d{4})\s*$")


def _parse_seq(contract_number: str | None, year: int | None = None) -> int | None:
    """Wyłuskaj numer porządkowy z `contract_number` („1434/2026" → 1434).

    Gdy podano `year`, dopasuj tylko numery z tego roku (inaczej zwróć None)."""
    if not contract_number:
        return None
    m = _NUMBER_RE.match(contract_number)
    if not m:
        return None
    if year is not None and int(m.group(2)) != year:
        return None
    return int(m.group(1))


def _validate_contract_number(number: str, suggested: str) -> tuple[int, int, str]:
    """Zwaliduj format „liczba/rok” i zwróć `(seq, rok, postać kanoniczna)`.

    Postać kanoniczna (`"1434/2026"`, bez spacji) jest jedyną zapisywaną do DB —
    inaczej „1434 / 2026” ominąłby string-owy check unikalności."""
    m = _NUMBER_RE.match(number)
    if not m:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Numer umowy musi być w formacie „liczba/rok”, np. {suggested}.",
        )
    seq, year = int(m.group(1)), int(m.group(2))
    return seq, year, f"{seq}/{year}"


async def _next_seq(db: AsyncSession, year: int) -> int:
    """Następny numer porządkowy = max(liczbowy prefiks `contract_number`) + 1.

    Liczone z REALNYCH numerów (string „1434/2026"), NIE z kolumny `seq` (zwykły
    licznik wierszy) — dzięki temu sugestia respektuje ręcznie wpisane numery
    (kontynuacja zewnętrznej numeracji, np. 1433→1434→1435) zamiast cofać się do
    „8/2026". Duplikaty nie zawyżają wyniku (max po wartości, nie po liczbie wierszy)."""
    rows = await db.execute(
        select(B2BGeneratedContract.contract_number).where(
            B2BGeneratedContract.year == year
        )
    )
    max_seq = 0
    for (number,) in rows.all():
        parsed = _parse_seq(number, year)
        if parsed is not None and parsed > max_seq:
            max_seq = parsed
    return max_seq + 1


@router.get("/next-number", response_model=B2BNextNumberResponse)
async def next_number(
    current_user: ContractLegalAccess,
    db: AsyncSession = Depends(get_db),
):
    """Sugerowany kolejny WOLNY numer umowy `<seq>/<rok>` (edytowalny w UI)."""
    year = datetime.now(timezone.utc).year
    seq = await _next_seq(db, year)
    return B2BNextNumberResponse(contract_number=f"{seq}/{year}", year=year, seq=seq)


# ── Auto-uzupełnianie danych firmy z rejestru (NIP / KRS) ────────────────────


@router.get("/company-lookup", response_model=B2BCompanyLookupResponse)
async def company_lookup(
    current_user: ContractLegalAccess,
    nip: str | None = Query(None),
    krs: str | None = Query(None),
):
    """Dane firmy z rejestru: Biała Lista MF po NIP (JDG + spółki) lub KRS."""
    data = await lookup_company(nip=nip, krs=krs)
    if not data:
        raise HTTPException(
            status_code=404,
            detail="Nie znaleziono firmy w rejestrze (sprawdź NIP / KRS).",
        )
    return data


# ── Standalone render (DOCX / HTML) — bez rekordu Contract ───────────────────


@router.post("/render")
async def render_standalone(
    payload: B2BRenderRequest,
    current_user: ContractLegalAccess,
    db: AsyncSession = Depends(get_db),
    fmt: str = Query("docx", alias="format", pattern="^(docx|html)$"),
):
    """Generuje umowę wprost z pól formularza (tryb ręczny / standalone).

    `format=html` → podgląd (nie loguje numeru). `format=docx` → przypisuje
    numer, loguje wygenerowanie i zwraca plik DOCX.
    """
    lang = normalize_language(payload.language)
    role = await db.get(B2BContractRole, payload.role_id) if payload.role_id else None
    linked_job: Job | None = None
    if payload.candidate_id is not None and payload.job_id is not None:
        _, linked_job = await _validate_candidate_job_link(
            db,
            candidate_id=payload.candidate_id,
            job_id=payload.job_id,
        )
    context = build_render_context(payload, role)

    if fmt == "html":
        tpl = await _b2b_template_for(db, lang)
        try:
            html = await run_in_threadpool(
                lambda: _jinja_env.from_string(tpl.content_jinja).render(**context)
            )
        except TemplateError as exc:
            raise HTTPException(status_code=422, detail=f"Render error: {exc}")
        # Per-klient modyfikacje umowy (§ 10, § 4 BNP, Załączniki CA/BIK…).
        ops = overrides_for_client(payload.client_name, lang)
        if ops:
            html = apply_ops_html(html, ops)
        return B2BRenderHtmlResponse(html=html, contract_number=payload.contract_number)

    # format == docx → numer + log + plik
    default_year = (
        payload.signing_date.year
        if payload.signing_date
        else datetime.now(timezone.utc).year
    )
    suggested_seq = await _next_seq(db, default_year)
    suggested = f"{suggested_seq}/{default_year}"
    raw_number = (payload.contract_number or "").strip() or suggested

    # Format „liczba/rok" (np. 1435/2026) — wymagany; zapis tylko kanoniczny.
    row_seq, row_year, number = _validate_contract_number(raw_number, suggested)

    # Unikalność: ten sam numer umowy nie może być użyty dwa razy.
    clash = await db.scalar(
        select(B2BGeneratedContract.id).where(
            B2BGeneratedContract.contract_number == number
        )
    )
    if clash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Numer umowy „{number}” jest już użyty — wybierz inny. "
                f"Następny wolny: {suggested}."
            ),
        )

    db.add(
        B2BGeneratedContract(
            year=row_year,
            seq=row_seq,
            contract_number=number,
            partner_name=payload.partner_name,
            client_name=payload.client_name,
            language=lang,
            signing_date=payload.signing_date,
            created_by=current_user.id,
            candidate_id=payload.candidate_id,
            job_id=payload.job_id,
            client_id=linked_job.client_id if linked_job else None,
            # Zapis surowych pól → ponowne pobranie DOCX z listy (re-render).
            render_payload=payload.model_dump(mode="json"),
        )
    )
    try:
        await db.commit()
    except IntegrityError:
        # Race: dwa równoległe rendery z tym samym numerem przeszły SELECT-check;
        # constraint UNIQUE(year, seq) ubija drugi INSERT (migracja 0128).
        await db.rollback()
        fresh = await _next_seq(db, row_year)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Numer umowy „{number}” został właśnie użyty przez kogoś innego "
                f"— wybierz inny. Następny wolny: {fresh}/{row_year}."
            ),
        )
    context["b2b"]["contract_number"] = number

    data = await run_in_threadpool(render_from_context, context, language=lang)
    return _docx_response(data, number)


def _like_needle(raw: str) -> str:
    """Zamień frazę użytkownika na bezpieczny wzorzec ILIKE.

    Escapujemy `%`, `_` i `\\`, żeby wpisanie ich w wyszukiwarce szukało tych
    znaków, a nie działało jak wildcard (`%` bez escapu zwracał całą listę)."""
    escaped = raw.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@router.get("/generated", response_model=list[B2BGeneratedContractItem])
async def list_generated_contracts(
    current_user: ContractLegalAccess,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    q: str | None = Query(
        None,
        max_length=120,
        description=(
            "Szukaj po numerze umowy, nazwie Partnera/Klienta lub imieniu "
            "i nazwisku powiązanego kandydata."
        ),
    ),
    contract_status: str | None = Query(
        None,
        pattern="^(active|closed)$",
        description="Filtr statusu handlowego umowy.",
    ),
):
    """Ostatnio wygenerowane umowy (numer, partner, klient, data) — do zakładki
    „Wygenerowane umowy", by potwierdzić poprawność numeru.

    ``q`` filtruje po stronie serwera (nie po `limit` pobranych wierszy), więc
    znajduje też umowy starsze niż widoczna strona listy.

    ``can_delete`` mówi UI, czy bieżący użytkownik może usunąć dany wpis (autor
    wpisu lub admin)."""
    query = select(B2BGeneratedContract)

    needle = (q or "").strip()
    if needle:
        pattern = _like_needle(needle)
        # OUTER JOIN, bo większość wierszy nie ma dowiązanego kandydata —
        # INNER wyciąłby je z wyników wyszukiwania po numerze umowy.
        query = query.outerjoin(
            Candidate, Candidate.id == B2BGeneratedContract.candidate_id
        ).where(
            or_(
                B2BGeneratedContract.contract_number.ilike(pattern, escape="\\"),
                B2BGeneratedContract.partner_name.ilike(pattern, escape="\\"),
                B2BGeneratedContract.client_name.ilike(pattern, escape="\\"),
                Candidate.name.ilike(pattern, escape="\\"),
                Candidate.lastname.ilike(pattern, escape="\\"),
                # Pełne „Imię Nazwisko" wpisane jednym ciągiem — pojedyncze
                # kolumny wyżej same tego nie dopasują.
                func.concat(Candidate.name, " ", Candidate.lastname).ilike(
                    pattern, escape="\\"
                ),
            )
        )

    if contract_status:
        query = query.where(B2BGeneratedContract.contract_status == contract_status)

    rows = list(
        (
            await db.execute(
                query.order_by(B2BGeneratedContract.created_at.desc()).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return await _serialize_generated_contracts(db, rows, current_user)


@router.get("/generated/{generated_id}/docx")
async def download_generated_contract(
    generated_id: int,
    current_user: ContractLegalAccess,
    db: AsyncSession = Depends(get_db),
):
    """Pobierz ponownie DOCX wygenerowanej umowy — odtworzony z zapisanego payloadu.

    Render jest deterministyczny z zapisanych pól formularza, więc dokument jest
    treściowo tożsamy z pierwotnie pobranym (numer umowy bierzemy z wiersza logu,
    nie z payloadu). Wiersze sprzed wdrożenia tej funkcji nie mają payloadu → 422
    z prośbą o ponowne wygenerowanie."""
    row = await db.get(B2BGeneratedContract, generated_id)
    if not row:
        raise HTTPException(status_code=404, detail="Wpis nie został znaleziony")
    if not row.render_payload:
        raise HTTPException(
            status_code=422,
            detail=(
                "Ta umowa została wygenerowana zanim dodaliśmy zapis danych — "
                "nie można jej odtworzyć. Wygeneruj ją ponownie z formularza."
            ),
        )
    payload = B2BRenderRequest(**row.render_payload)
    lang = normalize_language(payload.language)
    role = await db.get(B2BContractRole, payload.role_id) if payload.role_id else None
    context = build_render_context(payload, role)
    context["b2b"]["contract_number"] = row.contract_number

    data = await run_in_threadpool(render_from_context, context, language=lang)
    return _docx_response(data, row.contract_number)


@router.post(
    "/generated/{generated_id}/confirm-fully-signed",
    response_model=B2BConfirmFullySignedResponse,
)
async def confirm_generated_contract_fully_signed(
    generated_id: int,
    payload: B2BConfirmFullySignedRequest,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
):
    """One-way, audited manual confirmation with atomic employment automation."""

    try:
        row = await db.scalar(
            select(B2BGeneratedContract)
            .where(B2BGeneratedContract.id == generated_id)
            .with_for_update()
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Wpis nie został znaleziony")

        # Idempotent replay: do not recreate an order/stage after the original
        # workflow has completed (the order may legitimately be completed or
        # deleted later). Return the durable links that still exist.
        if row.signature_status == "signed_both":
            if (
                row.contract_id is None
                or row.candidate_id is None
                or row.job_id is None
                or row.client_id is None
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Podpisany wpis ma niepełne powiązania. Wymaga naprawy "
                        "administracyjnej; automatyzacja nie zostanie powtórzona."
                    ),
                )
            signed_job = await db.get(Job, row.job_id)
            if signed_job is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Powiązana rekrutacja już nie istnieje.",
                )
            await _require_signature_job_scope(db, current_user, signed_job)
            order_id = await db.scalar(
                select(ClientOrder.id)
                .where(
                    ClientOrder.contract_id == row.contract_id,
                    ClientOrder.job_id == row.job_id,
                )
                .order_by(ClientOrder.created_at.desc(), ClientOrder.id.desc())
                .limit(1)
            )
            item = await _serialize_generated_contract(db, row, current_user)
            await db.commit()
            return B2BConfirmFullySignedResponse(
                outcome="already_processed",
                contract_id=row.contract_id,
                order_id=order_id,
                candidate_id=row.candidate_id,
                job_id=row.job_id,
                client_id=row.client_id,
                message=(
                    "Umowa była już oznaczona jako podpisana. "
                    "Nie utworzono żadnych dodatkowych rekordów."
                ),
                generated_contract=item,
            )

        if (
            row.candidate_id is not None
            and payload.candidate_id is not None
            and row.candidate_id != payload.candidate_id
        ) or (
            row.job_id is not None
            and payload.job_id is not None
            and row.job_id != payload.job_id
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Wpis ma już inne powiązanie źródłowe. Nie można przepiąć "
                    "go podczas potwierdzania podpisu."
                ),
            )

        candidate_id = row.candidate_id or payload.candidate_id
        job_id = row.job_id or payload.job_id
        if candidate_id is None or job_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Historyczna umowa wymaga wskazania kandydata i konkretnej "
                    "rekrutacji przed potwierdzeniem podpisu."
                ),
            )

        _, job = await _validate_candidate_job_link(
            db,
            candidate_id=candidate_id,
            job_id=job_id,
        )
        await _require_signature_job_scope(db, current_user, job)
        if row.client_id is not None and row.client_id != job.client_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Klient zapisany przy umowie nie odpowiada klientowi "
                    "wybranej rekrutacji."
                ),
            )

        render_payload = (
            B2BRenderRequest(**row.render_payload) if row.render_payload else None
        )
        result = await ensure_b2b_employment_draft(
            db,
            candidate_id=candidate_id,
            job=job,
            actor_id=current_user.id,
            payload=render_payload,
            contract_number=row.contract_number,
            signing_date=row.signing_date,
            language=row.language,
            ensure_order=True,
            ensure_hired=True,
            audit_source_generated_id=row.id,
        )
        if result.order is None:  # defensive; ensure_order=True guarantees it
            raise RuntimeError("employment automation returned no ClientOrder")

        row.signature_status = "signed_both"
        row.signature_source = "manual_confirmation"
        row.candidate_id = candidate_id
        row.job_id = job.id
        row.client_id = job.client_id
        row.contract_id = result.contract.id
        row.signed_at = datetime.now(timezone.utc)
        row.signed_by_user_id = current_user.id
        if row.render_payload is not None:
            row.render_payload = {
                **row.render_payload,
                "candidate_id": candidate_id,
                "job_id": job.id,
            }
        db.add(
            Activity(
                entity_type="b2b_generated_contract",
                entity_id=row.id,
                action="fully_signed_confirmed",
                user_id=current_user.id,
                details={
                    "contract_number": row.contract_number,
                    "candidate_id": candidate_id,
                    "job_id": job.id,
                    "client_id": job.client_id,
                    "contract_id": result.contract.id,
                    "order_id": result.order.id,
                    "source": "manual_confirmation",
                    "outcome": (
                        "created" if result.created_contract else "linked_existing"
                    ),
                },
            )
        )
        # Build the public projection before committing so even a serializer
        # failure rolls back the entire handoff instead of returning a 500
        # after employment was already persisted.
        await db.flush()
        item = await _serialize_generated_contract(db, row, current_user)
        await db.commit()
        outcome = "created" if result.created_contract else "linked_existing"
        message = (
            "Utworzono szkic kontraktora i zamówienia oraz oznaczono "
            "kandydata jako zatrudnionego."
            if result.created_contract
            else (
                "Kontraktor już istniał — umowę powiązano bez tworzenia "
                "duplikatu, a zatrudnienie zsynchronizowano."
            )
        )
        return B2BConfirmFullySignedResponse(
            outcome=outcome,
            contract_id=result.contract.id,
            order_id=result.order.id,
            candidate_id=candidate_id,
            job_id=job.id,
            client_id=job.client_id,
            message=message,
            generated_contract=item,
        )
    except HTTPException:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise


@router.patch("/generated/{generated_id}", response_model=B2BGeneratedContractItem)
async def update_generated_contract(
    generated_id: int,
    payload: B2BGeneratedContractUpdate,
    current_user: ContractLegalAccess,
    db: AsyncSession = Depends(get_db),
):
    """Popraw wpis na liście „Wygenerowane umowy": nazwa Klienta i/lub status.

    ``client_name`` aktualizuje zarówno kolumnę (widoczną na liście), jak i
    ``render_payload['client_name']`` — dzięki temu ponowne pobranie DOCX ma już
    poprawioną nazwę, a per-klienta klauzule (§/załączniki) dobiorą się pod nią.
    Edytować może wyłącznie autor wpisu lub administrator (jak przy usuwaniu).

    Zmiana treści dokumentu jest zablokowana po podpisaniu, ale zmiana **statusu
    handlowego** — nie: wypowiedzenie i porozumienie o rozwiązaniu dotyczą z
    definicji umów już podpisanych. Zamknięcie nie usuwa wiersza."""
    row = await db.scalar(
        select(B2BGeneratedContract)
        .where(B2BGeneratedContract.id == generated_id)
        .with_for_update()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Wpis nie został znaleziony")
    fields = payload.model_fields_set
    wants_client_name = "client_name" in fields
    wants_status = "contract_status" in fields
    if not wants_client_name and not wants_status:
        raise HTTPException(
            status_code=422,
            detail="Nie przesłano żadnej zmiany.",
        )
    if wants_client_name and row.signature_status == "signed_both":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Podpisana umowa jest częścią historii zatrudnienia i nie może "
                "być edytowana."
            ),
        )
    is_admin = current_user.has_role(UserRole.admin)
    if not is_admin and row.created_by != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Możesz edytować tylko umowy, które samodzielnie wygenerowałeś.",
        )

    if wants_client_name:
        old_client = row.client_name
        new_client = (payload.client_name or "").strip() or None
        row.client_name = new_client
        # Zsynchronizuj zapisany payload → ponowny render DOCX i klauzule
        # per-klient użyją już poprawionej nazwy. Reassign (nie mutacja
        # in-place), by SQLAlchemy wykrył zmianę kolumny JSON.
        if row.render_payload is not None:
            row.render_payload = {**row.render_payload, "client_name": new_client}
        db.add(
            Activity(
                entity_type="b2b_generated_contract",
                entity_id=row.id,
                action="updated",
                user_id=current_user.id,
                details={
                    "contract_number": row.contract_number,
                    "field": "client_name",
                    "old": old_client,
                    "new": new_client,
                },
            )
        )

    if wants_status:
        old_status = row.contract_status
        row.contract_status = payload.contract_status
        if payload.contract_status == "closed":
            row.closure_reason = payload.closure_reason
            row.closure_reason_other = (
                (payload.closure_reason_other or "").strip() or None
                if payload.closure_reason == "other"
                else None
            )
            row.closure_date = payload.closure_date
        else:
            # Powrót na „Aktywna" czyści komplet pól zamknięcia — inaczej
            # zostawałby osierocony powód, którego CHECK i tak by nie przepuścił.
            row.closure_reason = None
            row.closure_reason_other = None
            row.closure_date = None
        db.add(
            Activity(
                entity_type="b2b_generated_contract",
                entity_id=row.id,
                action="status_changed",
                user_id=current_user.id,
                details={
                    "contract_number": row.contract_number,
                    "field": "contract_status",
                    "old": old_status,
                    "new": row.contract_status,
                    "closure_reason": row.closure_reason,
                    "closure_reason_other": row.closure_reason_other,
                    "closure_date": (
                        row.closure_date.isoformat() if row.closure_date else None
                    ),
                },
            )
        )

    await db.commit()
    await db.refresh(row)

    return await _serialize_generated_contract(db, row, current_user)


@router.delete("/generated/{generated_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_generated_contract(
    generated_id: int,
    current_user: ContractLegalAccess,
    db: AsyncSession = Depends(get_db),
):
    """Usuń wpis z listy „Wygenerowane umowy".

    Może to zrobić wyłącznie autor wpisu (osoba, która wygenerowała umowę) lub
    administrator. Usunięcie nie zwalnia numeru wstecz — sugestia kolejnego numeru
    liczona jest jako ``max(numer)+1``, więc skasowanie najnowszego wpisu pozwala
    ponownie użyć jego numeru (świadome — to log/audyt, nie rejestr nadań)."""
    row = await db.scalar(
        select(B2BGeneratedContract)
        .where(B2BGeneratedContract.id == generated_id)
        .with_for_update()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Wpis nie został znaleziony")
    if row.signature_status == "signed_both":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Podpisana umowa jest częścią historii zatrudnienia i nie może "
                "być usunięta."
            ),
        )
    if not current_user.has_role(UserRole.admin) and row.created_by != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Możesz usunąć tylko umowy, które samodzielnie wygenerowałeś.",
        )
    number, partner, rid = row.contract_number, row.partner_name, row.id
    await db.delete(row)
    db.add(
        Activity(
            entity_type="b2b_generated_contract",
            entity_id=rid,
            action="deleted",
            user_id=current_user.id,
            details={"contract_number": number, "partner_name": partner},
        )
    )
    await db.commit()


@router.post("/check-uop", response_model=B2BUopCheckResponse)
async def check_uop(
    payload: B2BUopCheckRequest,
    current_user: ContractLegalAccess,
):
    """AI-sprawdzenie opisu/zakresu pod kątem znamion umowy o pracę (art. 22 §1 KP).

    Zwraca wykryte ryzykowne sformułowania + bezpieczniejszą redakcję. Wymaga
    skonfigurowanego ``ANTHROPIC_API_KEY`` (inaczej 503)."""
    text = (payload.text or "").strip()
    if not text:
        return B2BUopCheckResponse(ok=True, issues=[], rewritten="", summary="")
    try:
        result = await run_in_threadpool(
            check_employment_hallmarks, text, payload.language
        )
    except CVGeneratorAIError as exc:
        raise HTTPException(
            status_code=503,
            detail="Sprawdzanie AI jest chwilowo niedostępne — spróbuj ponownie później.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail="AI zwróciło nieprawidłową odpowiedź — spróbuj ponownie.",
        ) from exc
    return B2BUopCheckResponse(**result)
