"""Generator Umów B2B — katalog ról (CRUD) + generowanie umowy + eksport DOCX.

Reużywa istniejący system draftów: po `POST /generate` powstaje `Contract`
(typ b2b, status draft) z wyrenderowanym `draft_content_html`, więc działają
istniejące endpointy draftu (edycja Tiptap, render-pdf) oraz Autenti. DOCX jest
jedynym genuinnie nowym wyjściem (eksport na oryginalnym szablonie prawnym).
"""

from __future__ import annotations

import unicodedata
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.contracts import _load_contract_with_relations, _render_draft_body
from app.api.deps import AdminUser, CurrentUser, TacPlus
from app.core.database import get_db
from app.models.activity import Activity
from app.models.b2b_contract_detail import B2BContractDetail
from app.models.b2b_contract_role import B2BContractRole
from app.models.contract import (
    Contract,
    ContractStatus,
    ContractType,
    RateUnit,
)
from app.models.contract_template import ContractTemplate
from app.models.job import Job
from app.schemas.b2b_contract_generator import (
    B2BContractDetailResponse,
    B2BGenerateRequest,
    B2BGenerateResponse,
    B2BRoleCreate,
    B2BRoleResponse,
    B2BRoleUpdate,
)
from app.services.b2b_contract_generator.docx_renderer import (
    normalize_language,
    render_contract_docx,
)

router = APIRouter()

_DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _ascii_filename(name: str) -> str:
    """Transliteruj na ASCII i oczyść do bezpiecznej nazwy pliku."""
    norm = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in norm)
    return safe.strip("._") or "umowa"


# ── Katalog ról ──────────────────────────────────────────────────────────────


@router.get("/roles", response_model=list[B2BRoleResponse])
async def list_roles(
    current_user: CurrentUser,
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
    await db.commit()
    await db.refresh(role)
    return role


@router.get("/roles/{role_id}", response_model=B2BRoleResponse)
async def get_role(
    role_id: int,
    current_user: CurrentUser,
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
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
):
    role = await db.get(B2BContractRole, payload.role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Rola nie znaleziona")
    lang = normalize_language(payload.language)
    tpl = await _b2b_template_for(db, lang)

    # 1. Utwórz lub wczytaj draft Contract (typ b2b).
    if payload.contract_id is not None:
        contract = await db.get(Contract, payload.contract_id)
        if not contract:
            raise HTTPException(status_code=404, detail="Umowa nie znaleziona")
        if contract.contract_type != ContractType.b2b:
            raise HTTPException(status_code=409, detail="To nie jest umowa B2B")
    else:
        # client_id można wyprowadzić z wybranej rekrutacji (job → klient).
        client_id = payload.client_id
        if not client_id and payload.job_id:
            job = await db.get(Job, payload.job_id)
            client_id = job.client_id if job else None
        if not payload.candidate_id or not client_id:
            raise HTTPException(
                status_code=422,
                detail="Wymagany candidate_id oraz client_id lub job_id z klientem",
            )
        contract = Contract(
            candidate_id=payload.candidate_id,
            client_id=client_id,
            job_id=payload.job_id,
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
    contract.draft_content_html = _render_draft_body(tpl, contract)
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
    current_user: TacPlus,
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
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
    language: str | None = Query(None),
):
    contract = await _load_contract_with_relations(db, contract_id)
    detail_lang = contract.b2b_detail.language if contract.b2b_detail else "pl"
    lang = normalize_language(language or detail_lang)
    data = render_contract_docx(contract, language=lang)

    cand = contract.candidate
    label = f"{cand.name}_{cand.lastname}" if cand else f"contract_{contract.id}"
    filename = _ascii_filename(f"Umowa_B2B_{label}_{lang}") + ".docx"
    return Response(
        content=data,
        media_type=_DOCX_MEDIA,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
