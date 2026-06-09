"""Phase 9 B1 — contract template CRUD + preview/render.

Keeps the rendered output as HTML. The frontend uses the browser's built-in
print-to-PDF dialog for actual document generation — no weasyprint/pango
in the Coolify image.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from jinja2 import Environment, StrictUndefined, TemplateError, select_autoescape
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import AdminUser, CurrentUser
from app.core.database import get_db
from app.models.contract import Contract
from app.models.contract_template import ContractTemplate
from app.models.b2b_contract_detail import B2BContractDetail

router = APIRouter()


# ── Pydantic DTOs ────────────────────────────────────────────────────────────


class TemplateBase(BaseModel):
    name: str
    contract_type: str
    content_jinja: str
    is_default: bool = False


class TemplateCreate(TemplateBase):
    pass


class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    contract_type: Optional[str] = None
    content_jinja: Optional[str] = None
    is_default: Optional[bool] = None


class TemplateResponse(TemplateBase):
    id: int
    created_by: Optional[int] = None

    model_config = {"from_attributes": True}


# ── Jinja sandbox ────────────────────────────────────────────────────────────

_jinja_env = Environment(
    autoescape=select_autoescape(["html", "xml"]),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)

# Generator Umów B2B — filtr formatujący daty (PL/EN), współdzielony z renderem
# DOCX. Import modułu-liścia (bez zależności od `app`) → brak cyklu importów.
from app.services.b2b_contract_generator.formatting import (  # noqa: E402
    pl_date as _pl_date,
)
from app.services.b2b_contract_generator.formatting import (  # noqa: E402
    start_clause as _start_clause,
)
from app.services.b2b_contract_generator.gender import (  # noqa: E402
    gender_forms as _gender_forms,
)

_jinja_env.filters["pl_date"] = _pl_date


def _contract_vars(contract: Contract) -> dict:
    """Shape exposed to templates (keep stable — it's part of the contract)."""
    cand = contract.candidate
    cli = contract.client
    # Generator Umów B2B — dane per-umowa (1:1) + wybrana rola (zakres usług).
    # `b2b_detail` musi być eager-loaded przy każdym wywołaniu (async).
    detail = getattr(contract, "b2b_detail", None)
    role = detail.role if detail else None
    lang = (detail.language if detail else "pl") or "pl"
    if role is not None:
        _area_label = role.area_label_pl if lang == "pl" else role.area_label_en
        _role_name = role.name_pl if lang == "pl" else role.name_en
        _role_scope = role.scope_pl if lang == "pl" else role.scope_en
    else:
        _area_label = _role_name = None
        _role_scope = []
    _scope_items = (detail.role_scope_override if detail else None) or _role_scope or []
    return {
        "contract": {
            "id": contract.id,
            "start_date": contract.start_date,
            "end_date": contract.end_date,
            "rate_candidate": contract.rate_candidate,
            "rate_client": contract.rate_client,
            "currency": contract.currency,
            "rate_unit": contract.rate_unit.value
            if hasattr(contract.rate_unit, "value")
            else str(contract.rate_unit),
            "billing_hours_per_month": contract.billing_hours_per_month,
            "contract_type": contract.contract_type.value
            if hasattr(contract.contract_type, "value")
            else str(contract.contract_type),
            "project_name": contract.project_name,
            "team_name": contract.team_name,
            "office_location": contract.office_location,
            "work_mode": contract.work_mode.value
            if contract.work_mode and hasattr(contract.work_mode, "value")
            else (contract.work_mode or None),
            "client_pm_name": contract.client_pm_name,
            "client_pm_email": contract.client_pm_email,
        },
        "candidate": {
            "id": cand.id if cand else None,
            "name": cand.name if cand else None,
            "lastname": cand.lastname if cand else None,
            "full_name": (f"{cand.name} {cand.lastname}" if cand else None),
            "email": cand.email if cand else None,
            "phone": cand.phone if cand else None,
            "address": cand.location if cand else None,
            # JDG / business entity (migracja 0058)
            "legal_name": getattr(cand, "legal_name", None) if cand else None,
            "nip": getattr(cand, "nip", None) if cand else None,
            "regon": getattr(cand, "regon", None) if cand else None,
            "business_address": (
                getattr(cand, "business_address", None) if cand else None
            ),
            "business_form": (getattr(cand, "business_form", None) if cand else None),
        },
        "client": {
            "id": cli.id if cli else None,
            "name": cli.name if cli else None,
            "address": cli.address if cli else None,
            # Legal entity (migracja 0058)
            "legal_name": getattr(cli, "legal_name", None) if cli else None,
            "nip": getattr(cli, "nip", None) if cli else None,
            "regon": getattr(cli, "regon", None) if cli else None,
        },
        "job": {
            "id": contract.job.id if contract.job else None,
            "title": contract.job.title if contract.job else None,
        },
        "b2b": {
            "contract_number": detail.contract_number if detail else None,
            "signing_date": detail.signing_date if detail else None,
            "project_city": detail.project_city if detail else None,
            "project_description": detail.project_description if detail else None,
            "correspondence_address": (
                detail.correspondence_address if detail else None
            ),
            "rate_in_words": detail.rate_in_words if detail else None,
            "language": lang,
            "area_label": _area_label,
            "role_name": _role_name,
            "scope_items": _scope_items,
            # §13 — ścieżka /generate zawsze „z dniem <data>" (brak trybu w detalu).
            "start_clause": _start_clause(
                contract.start_date if hasattr(contract, "start_date") else None,
                "exact",
                lang,
            ),
            # Komparycja: ścieżka /generate nie odmienia (brak pola) → mianownik.
            "partner_instrumental": cand.full_name if cand else None,
            # Formy gramatyczne płci: ścieżka /generate domyślnie męska
            # (B2BContractDetail nie ma kolumny płci) — standalone /render
            # podstawia właściwą formę z formularza.
            **_gender_forms(None),
        },
    }


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("", response_model=List[TemplateResponse])
async def list_templates(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    contract_type: Optional[str] = Query(None),
):
    query = select(ContractTemplate)
    if contract_type:
        query = query.where(ContractTemplate.contract_type == contract_type)
    query = query.order_by(ContractTemplate.contract_type, ContractTemplate.name)
    res = await db.execute(query)
    return list(res.scalars().all())


@router.post("", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    data: TemplateCreate,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    # Validate template syntax on save so we fail early.
    try:
        _jinja_env.from_string(data.content_jinja)
    except TemplateError as e:
        raise HTTPException(status_code=422, detail=f"Jinja error: {e}")
    tpl = ContractTemplate(**data.model_dump(), created_by=current_user.id)
    db.add(tpl)
    await db.flush()
    await db.refresh(tpl)
    return tpl


@router.get("/{template_id}", response_model=TemplateResponse)
async def get_template(
    template_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    tpl = await db.scalar(
        select(ContractTemplate).where(ContractTemplate.id == template_id)
    )
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    return tpl


@router.patch("/{template_id}", response_model=TemplateResponse)
async def update_template(
    template_id: int,
    data: TemplateUpdate,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    tpl = await db.scalar(
        select(ContractTemplate).where(ContractTemplate.id == template_id)
    )
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    updates = data.model_dump(exclude_unset=True)
    if "content_jinja" in updates:
        try:
            _jinja_env.from_string(updates["content_jinja"])
        except TemplateError as e:
            raise HTTPException(status_code=422, detail=f"Jinja error: {e}")
    for k, v in updates.items():
        setattr(tpl, k, v)
    await db.flush()
    await db.refresh(tpl)
    return tpl


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: int,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    tpl = await db.scalar(
        select(ContractTemplate).where(ContractTemplate.id == template_id)
    )
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    await db.delete(tpl)


@router.get("/{template_id}/render", response_class=HTMLResponse)
async def render_template_for_contract(
    template_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    contract_id: int = Query(...),
):
    """Render an HTML document for a contract. Browser prints it to PDF."""
    tpl = await db.scalar(
        select(ContractTemplate).where(ContractTemplate.id == template_id)
    )
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    contract = await db.scalar(
        select(Contract)
        .where(Contract.id == contract_id)
        .options(
            selectinload(Contract.candidate),
            selectinload(Contract.client),
            selectinload(Contract.job),
            selectinload(Contract.b2b_detail).selectinload(B2BContractDetail.role),
        )
    )
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    try:
        rendered = _jinja_env.from_string(tpl.content_jinja).render(
            **_contract_vars(contract)
        )
    except TemplateError as e:
        raise HTTPException(status_code=422, detail=f"Render error: {e}")
    # Wrap in a minimal printable skeleton.
    html = (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        f"<title>{tpl.name} — kontrakt #{contract.id}</title>"
        "<style>"
        "body{font-family:'Helvetica',sans-serif;max-width:780px;margin:40px auto;line-height:1.55;color:#222;}"
        "h1,h2,h3{color:#111}"
        ".meta{color:#666;font-size:0.9em;margin-bottom:2em}"
        "@media print{body{margin:0}}"
        "</style></head><body>"
        f'<div class="meta">Wygenerowano z szablonu: {tpl.name}</div>'
        f"{rendered}"
        "</body></html>"
    )
    return HTMLResponse(content=html)
