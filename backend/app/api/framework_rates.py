"""Cennik umowy ramowej klienta, dopłaty i kategoria na kontrakcie (F1, 15.11.2026).

Bramki (decyzja Artura z 15.11.2026: kwoty widzi DL swojego klienta i Finanse):

* odczyt cennika, dopłat i kategorii kontraktu — ``DeliveryViewUser`` na trasie
  i ``can_read_client_finance`` w handlerze (DL tylko u klientów z przypisania);
* zapis cennika, dopłat i import z załącznika — ``FinanceManageUser``
  („reszta kart stawek zostaje przy Finansach”, jak przy BNP);
* kategoria i dopłata na kontrakcie oraz „Przelicz z COA” —
  ``ContractsOrdersOrAmountsEditUser`` (jak PATCH kontraktu) i w handlerze kwoty
  klienta z portfela (``can_read_client_finance``). Prowadzi Delivery Lead, który
  domyślnie nie ma „Stawki i kwoty: zmiana”.
"""

from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.candidate_access import NOT_READ_ONLY
from app.api.financial_access import FinanceManageUser, can_read_client_finance
from app.api.permission_access import ContractsOrdersOrAmountsEditUser, DeliveryViewUser
from app.api.section_access import DELIVERY_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.core.scheduling import business_today
from app.models.contract import Contract, RateUnit
from app.models.rate_card import RateCard, RateCardAdder
from app.models.user import User
from app.services.access_scope import (
    DL_CLIENT_OUT_OF_SCOPE_DETAIL,
    resolve_delivery_lead_finance_client_ids,
)
from app.services.client_access import assert_client_assignable
from app.services.framework_category import (
    ClientTerms,
    FrameworkCategoryError,
    load_terms,
    recompute_from_coa,
    set_by_delivery_lead,
)
from app.services.framework_limits import (
    addon_choices,
    category_label,
    framework_limit,
    percent_text,
)
from app.services.framework_overview import (
    Overview,
    build_overview,
    classify,
    quarter_ends,
)
from app.services.framework_terms_import import parse_terms_docx

# Odczyt i praca DL — sekcja Delivery jak kontrakty; cennik zapisują Finanse
# (bramka capability, bez sekcji Delivery).
router = APIRouter(dependencies=DELIVERY_SECTION_DEPENDENCIES)
finance_router = APIRouter()

MAX_APPENDIX_BYTES = 5 * 1024 * 1024


async def _assert_client_finance(user: User, db: AsyncSession, client_id: int) -> None:
    ids = await resolve_delivery_lead_finance_client_ids(user, db)
    if not can_read_client_finance(
        user, client_id=client_id, delivery_lead_finance_client_ids=ids
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail=DL_CLIENT_OUT_OF_SCOPE_DETAIL
        )


# --- Schematy -------------------------------------------------------------------


class AdderOut(BaseModel):
    id: int
    technology: str
    percent: Decimal
    eligible: list[dict]
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    notes: Optional[str] = None


class CardOut(BaseModel):
    id: int
    label: str
    role: str
    seniority: Optional[str] = None
    rate_max: Optional[int] = None
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    addons: list[str] = Field(default_factory=list)


class TermsOut(BaseModel):
    client_id: int
    cards: list[CardOut]
    adders: list[AdderOut]


class AdderIn(BaseModel):
    technology: str = Field(min_length=1, max_length=100)
    percent: Decimal = Field(gt=0, le=100)
    eligible: list[dict] = Field(default_factory=list, max_length=200)
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    notes: Optional[str] = Field(default=None, max_length=2000)


class ImportRateOut(BaseModel):
    label: str
    rate: Decimal
    action: str


class ImportAdderOut(BaseModel):
    technology: str
    percent: Decimal
    eligible: list[str]
    action: str


class ImportOut(BaseModel):
    applied: bool
    rates: list[ImportRateOut]
    adders: list[ImportAdderOut]
    warnings: list[str]


class CategoryIn(BaseModel):
    rate_card_id: int
    addon_technology: Optional[str] = Field(default=None, max_length=100)
    confirmed_by: Optional[str] = Field(default=None, max_length=255)
    confirmed_on: Optional[date] = None
    evidence: Optional[str] = Field(default=None, max_length=4000)
    effective_from: Optional[date] = None


class AddonOut(BaseModel):
    technology: str
    percent: Decimal
    confirmed_by: Optional[str] = None
    confirmed_on: Optional[date] = None
    evidence: Optional[str] = None


class CategoryOut(BaseModel):
    contract_id: int
    client_id: int
    rate_client: Optional[Decimal] = None
    framework_limit: Optional[Decimal] = None
    gap: Optional[Decimal] = None
    status: str
    card: Optional[CardOut] = None
    source: Optional[str] = None
    coa_label: Optional[str] = None
    addon: Optional[AddonOut] = None
    cards: list[CardOut]


class RecomputeRowOut(BaseModel):
    contract_id: int
    outcome: str
    coa_label: Optional[str] = None
    category_before: Optional[str] = None
    category_after: Optional[str] = None
    limit_before: Optional[Decimal] = None
    limit_after: Optional[Decimal] = None


class RecomputeOut(BaseModel):
    rows: list[RecomputeRowOut]
    next_after_id: Optional[int] = None


# --- Widoki ---------------------------------------------------------------------


def _card_out(terms: ClientTerms, card, on: date) -> CardOut:
    return CardOut(
        id=card.id,
        label=category_label(card.role, card.seniority),
        role=card.role,
        seniority=card.seniority,
        rate_max=card.rate_client_max,
        valid_from=card.valid_from,
        valid_to=card.valid_to,
        addons=[
            f"{a.technology} {percent_text(a.percent)}%"
            for a in addon_choices(terms.adders, card, on=on)
        ],
    )


def _adder_out(row: RateCardAdder) -> AdderOut:
    return AdderOut(
        id=row.id,
        technology=row.technology,
        percent=row.percent,
        eligible=list(row.eligible or []),
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        notes=row.notes,
    )


# --- Cennik i dopłaty -----------------------------------------------------------


@router.get("/clients/{client_id}/framework-terms", response_model=TermsOut)
async def get_framework_terms(
    client_id: int,
    current_user: DeliveryViewUser,
    db: AsyncSession = Depends(get_db),
):
    await _assert_client_finance(current_user, db, client_id)
    terms = await load_terms(db, client_id)
    today = business_today()
    adders = (
        await db.execute(
            select(RateCardAdder)
            .where(RateCardAdder.client_id == client_id)
            .order_by(RateCardAdder.technology)
        )
    ).scalars()
    return TermsOut(
        client_id=client_id,
        cards=[_card_out(terms, c, today) for c in terms.cards],
        adders=[_adder_out(a) for a in adders],
    )


@finance_router.post(
    "/clients/{client_id}/framework-adders", response_model=AdderOut, status_code=201
)
async def create_framework_adder(
    client_id: int,
    payload: AdderIn,
    current_user: FinanceManageUser,
    db: AsyncSession = Depends(get_db),
):
    await assert_client_assignable(db, client_id)
    row = RateCardAdder(client_id=client_id, **payload.model_dump())
    db.add(row)
    await db.flush()
    return _adder_out(row)


@finance_router.patch("/framework-adders/{adder_id}", response_model=AdderOut)
async def update_framework_adder(
    adder_id: int,
    payload: AdderIn,
    current_user: FinanceManageUser,
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(RateCardAdder, adder_id)
    if row is None:
        raise HTTPException(404, detail="Nie ma takiej dopłaty.")
    await assert_client_assignable(db, row.client_id)
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    await db.flush()
    return _adder_out(row)


@finance_router.delete("/framework-adders/{adder_id}", status_code=204)
async def delete_framework_adder(
    adder_id: int,
    current_user: FinanceManageUser,
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(RateCardAdder, adder_id)
    if row is None:
        raise HTTPException(404, detail="Nie ma takiej dopłaty.")
    await db.delete(row)


@finance_router.post(
    "/clients/{client_id}/framework-terms/import", response_model=ImportOut
)
async def import_framework_terms(
    client_id: int,
    current_user: FinanceManageUser,
    file: UploadFile = File(...),
    apply: bool = Form(False),
    valid_from: Optional[date] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Podgląd (``apply=false``) albo zapis cennika z załącznika umowy (.docx)."""
    await assert_client_assignable(db, client_id)
    if not (file.filename or "").casefold().endswith(".docx"):
        raise HTTPException(
            422, detail="Wgraj załącznik umowy w formacie Word (.docx)."
        )
    data = await file.read(MAX_APPENDIX_BYTES + 1)
    if len(data) > MAX_APPENDIX_BYTES:
        raise HTTPException(413, detail="Plik przekracza 5 MB.")
    if not data.startswith(b"PK"):
        raise HTTPException(422, detail="To nie jest plik Word (.docx).")
    try:
        proposal = parse_terms_docx(data)
    except Exception as exc:  # noqa: BLE001 — uszkodzony plik to błąd użytkownika
        raise HTTPException(
            422, detail="Nie udało się odczytać tabel z pliku Word."
        ) from exc

    existing = (
        (
            await db.execute(
                select(RateCard).where(
                    RateCard.client_id == client_id, RateCard.valid_to.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    by_label = {category_label(c.role, c.seniority).casefold(): c for c in existing}
    adders = (
        (
            await db.execute(
                select(RateCardAdder).where(RateCardAdder.client_id == client_id)
            )
        )
        .scalars()
        .all()
    )
    adder_by_tech = {a.technology.casefold(): a for a in adders}
    warnings = list(proposal.warnings)
    rates_out: list[ImportRateOut] = []
    for rate in proposal.rates:
        if rate.rate != rate.rate.to_integral_value():
            warnings.append(
                f"{rate.label}: stawka z groszami — wpisz ją ręcznie w cenniku."
            )
            continue
        card = by_label.get(rate.label.casefold())
        if card is None:
            action = "create"
        elif (
            card.rate_client_max == int(rate.rate) and card.rate_unit == RateUnit.hourly
        ):
            action = "unchanged"
        else:
            action = "update"
        rates_out.append(ImportRateOut(label=rate.label, rate=rate.rate, action=action))
        if not apply or action == "unchanged":
            continue
        if card is None:
            card = RateCard(
                client_id=client_id,
                role=rate.role,
                seniority=rate.seniority,
                currency="PLN",
            )
            db.add(card)
        card.rate_client_max = int(rate.rate)
        card.rate_unit = RateUnit.hourly
        card.valid_from = valid_from or card.valid_from
        card.notes = (
            f"Import z załącznika umowy ramowej ({business_today().isoformat()})"
        )
    adders_out: list[ImportAdderOut] = []
    for item in proposal.adders:
        row = adder_by_tech.get(item.technology.casefold())
        same = (
            row is not None
            and row.percent == item.percent
            and list(row.eligible or []) == item.eligible
        )
        action = "create" if row is None else ("unchanged" if same else "update")
        adders_out.append(
            ImportAdderOut(
                technology=item.technology,
                percent=item.percent,
                eligible=[
                    category_label(p["role"], p["seniority"]) for p in item.eligible
                ],
                action=action,
            )
        )
        if not apply or action == "unchanged":
            continue
        if row is None:
            row = RateCardAdder(client_id=client_id, technology=item.technology)
            db.add(row)
        row.percent = item.percent
        row.eligible = item.eligible
        row.valid_from = valid_from or row.valid_from
    if apply:
        await db.flush()
    return ImportOut(
        applied=apply, rates=rates_out, adders=adders_out, warnings=warnings
    )


@router.post(
    "/clients/{client_id}/framework-categories/recompute", response_model=RecomputeOut
)
async def recompute_framework_categories(
    client_id: int,
    current_user: ContractsOrdersOrAmountsEditUser,
    after_id: int = Query(0, ge=0),
    apply: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """Porcja kontraktów: kategoria z najnowszego zapisanego COA (``next_after_id``)."""
    await _assert_client_finance(current_user, db, client_id)
    if apply:
        await assert_client_assignable(db, client_id)
    try:
        report = await recompute_from_coa(
            db, client_id, after_id=after_id, apply=apply, actor_id=current_user.id
        )
    except FrameworkCategoryError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    if apply:
        await db.flush()
    return RecomputeOut(
        rows=[RecomputeRowOut(**vars(r)) for r in report.rows],
        next_after_id=report.next_after_id,
    )


# --- Kontrakt -------------------------------------------------------------------


async def _contract(
    db: AsyncSession, contract_id: int, *, lock: bool = False
) -> Contract:
    query = (
        select(Contract)
        .options(
            selectinload(Contract.framework_rate_schedule),
            selectinload(Contract.client_rate_schedule),
        )
        .where(Contract.id == contract_id)
    )
    if lock:
        query = query.with_for_update(of=Contract)
    contract = await db.scalar(query)
    if contract is None:
        raise HTTPException(404, detail="Nie ma takiego kontraktu.")
    return contract


def _category_out(contract: Contract, terms: ClientTerms) -> CategoryOut:
    today = business_today()
    card = terms.card(contract.client_rate_card_id)
    rate = contract.effective_client_rate(today)
    limit = contract.effective_framework_rate(today)
    base = framework_limit(card, None) if card else None
    addon = None
    if contract.framework_addon_technology:
        addon = AddonOut(
            technology=contract.framework_addon_technology,
            percent=contract.framework_addon_percent,
            confirmed_by=contract.framework_addon_confirmed_by,
            confirmed_on=contract.framework_addon_confirmed_on,
            evidence=contract.framework_addon_evidence,
        )
    return CategoryOut(
        contract_id=contract.id,
        client_id=contract.client_id,
        rate_client=rate,
        framework_limit=limit,
        gap=(rate - limit) if rate is not None and limit is not None else None,
        status=classify(rate, limit, base),
        card=_card_out(terms, card, today) if card else None,
        source=contract.rate_card_source,
        coa_label=contract.rate_card_coa_label,
        addon=addon,
        cards=[_card_out(terms, c, today) for c in terms.cards],
    )


@router.get("/contracts/{contract_id}/framework-category", response_model=CategoryOut)
async def get_contract_framework_category(
    contract_id: int,
    current_user: DeliveryViewUser,
    db: AsyncSession = Depends(get_db),
):
    contract = await _contract(db, contract_id)
    await _assert_client_finance(current_user, db, contract.client_id)
    return _category_out(contract, await load_terms(db, contract.client_id))


@router.put("/contracts/{contract_id}/framework-category", response_model=CategoryOut)
async def put_contract_framework_category(
    contract_id: int,
    payload: CategoryIn,
    current_user: ContractsOrdersOrAmountsEditUser,
    db: AsyncSession = Depends(get_db),
):
    """Kategoria i przyznana dopłata. Nie zmienia zamówienia ani stawki przychodowej."""
    contract = await _contract(db, contract_id, lock=True)
    await _assert_client_finance(current_user, db, contract.client_id)
    await assert_client_assignable(db, contract.client_id)
    terms = await load_terms(db, contract.client_id)
    try:
        set_by_delivery_lead(
            db,
            contract,
            terms,
            rate_card_id=payload.rate_card_id,
            addon_technology=payload.addon_technology,
            confirmed_by=payload.confirmed_by,
            confirmed_on=payload.confirmed_on,
            evidence=payload.evidence,
            effective_from=payload.effective_from or business_today(),
            actor_id=current_user.id,
        )
    except FrameworkCategoryError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    await db.flush()
    return _category_out(contract, terms)


# --- Przegląd i raport kwartalny (F2) ---------------------------------------------


class LeverOut(BaseModel):
    kind: str
    label: str
    limit: Decimal


class OverviewRowOut(BaseModel):
    contract_id: int
    person: str
    category: Optional[str] = None
    source: Optional[str] = None
    coa_label: Optional[str] = None
    rate: Optional[Decimal] = None
    limit: Optional[Decimal] = None
    base: Optional[Decimal] = None
    addon: Optional[str] = None
    status: str
    gap: Optional[Decimal] = None
    order_end: Optional[date] = None
    levers: list[LeverOut] = Field(default_factory=list)
    limit_mismatch: bool = False


class CategoryCountOut(BaseModel):
    category: str
    counts: dict[str, int]


class PointOut(BaseModel):
    on: date
    counts: dict[str, int]


class OverviewOut(BaseModel):
    client_id: int
    on: date
    counts: dict[str, int]
    over_gap: Decimal
    by_category: list[CategoryCountOut]
    trend: list[PointOut]
    rows: list[OverviewRowOut]


def _rows_out(ov: Overview) -> list[OverviewRowOut]:
    return [
        OverviewRowOut(
            **{k: v for k, v in vars(r).items() if k != "levers"},
            levers=[
                LeverOut(kind=lv.kind, label=lv.label, limit=lv.limit)
                for lv in r.levers
            ],
        )
        for r in ov.rows
    ]


@router.get("/clients/{client_id}/framework-overview", response_model=OverviewOut)
async def get_framework_overview(
    client_id: int,
    current_user: DeliveryViewUser,
    on: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Kto jest w limicie z umowy ramowej, kto ponad i co daje umowa (stan na dzień)."""
    await _assert_client_finance(current_user, db, client_id)
    today = business_today()
    day = on or today
    ov = await build_overview(db, client_id, on=day, today=today)
    trend = []
    for point in [*quarter_ends(today), today] if on is None else []:
        snap = (
            ov
            if point == day
            else await build_overview(db, client_id, on=point, today=today)
        )
        trend.append(PointOut(on=point, counts=snap.counts))
    return OverviewOut(
        client_id=client_id,
        on=day,
        counts=ov.counts,
        over_gap=ov.over_gap,
        by_category=[
            CategoryCountOut(category=k, counts=v) for k, v in ov.by_category()
        ],
        trend=trend,
        rows=_rows_out(ov),
    )


_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_STATUS_PL = {
    "in": "W stawce",
    "in_addon": "W stawce dzięki dopłacie",
    "over": "Ponad stawką",
    "no_limit": "Bez stawki z umowy",
}


def governance_xlsx(ov: Overview) -> bytes:
    """Raport kwartalny dla klienta: liczby i lista osób. Bez marży i kosztu."""
    from io import BytesIO

    from openpyxl import Workbook

    from app.core.export_safety import safe_row

    book = Workbook()
    summary = book.active
    summary.title = "Podsumowanie"
    summary.append(safe_row([f"Stan na {ov.on.isoformat()}"]))
    summary.append([])
    summary.append(safe_row(["Status", "Liczba osób"]))
    for key, count in ov.counts.items():
        summary.append(safe_row([_STATUS_PL[key], count]))
    summary.append([])
    summary.append(
        safe_row(["Kategoria", "W stawce", "Dzięki dopłacie", "Ponad stawką"])
    )
    for family, counts in ov.by_category():
        summary.append(
            safe_row([family, counts["in"], counts["in_addon"], counts["over"]])
        )
    people = book.create_sheet("Konsultanci")
    people.append(
        safe_row(
            [
                "Konsultant",
                "Kategoria",
                "Dopłata",
                "Stawka (PLN/h)",
                "Limit z umowy (PLN/h)",
                "Status",
            ]
        )
    )
    for row in ov.rows:
        people.append(
            safe_row(
                [
                    row.person,
                    row.category or "",
                    row.addon or "",
                    float(row.rate) if row.rate is not None else None,
                    float(row.limit) if row.limit is not None else None,
                    _STATUS_PL[row.status],
                ]
            )
        )
    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()


@router.get(
    "/clients/{client_id}/framework-overview/report.xlsx", dependencies=NOT_READ_ONLY
)
async def get_framework_governance_report(
    client_id: int,
    current_user: DeliveryViewUser,
    on: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    await _assert_client_finance(current_user, db, client_id)
    today = business_today()
    ov = await build_overview(db, client_id, on=on or today, today=today)
    name = f"stawki-ramowe-{(on or today).isoformat()}.xlsx"
    return Response(
        content=governance_xlsx(ov),
        media_type=_XLSX,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
