"""Ekrany panelu konsultanta: stawka, „Do zrobienia”, Na start, sprzęt, rozliczenie, trener.

Wszystko jest listą dozwolonych pól, bo odpowiedź trafia do osoby spoza firmy:

* stawka to wyłącznie stawka konsultanta, bez stawki klienta i marży,
* sprzęt to model, numery i protokół, bez cennika, uwag i lokalizacji; pokazujemy tylko
  wydania z protokołem (decyzja Artura 05.11.2026),
* materiały to te wybrane przy aktywacji, a pobranie sprawdza kontrakt sesji.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.scheduling import DEFAULT_TZ
from app.models.admin_case import AdminCase
from app.models.consultant_panel import (
    ClientOnboardingMaterial,
    ClientSettlementRule,
    CpActivation,
    CpActivationMaterial,
    CpTrainerApplication,
)
from app.models.contract import Contract
from app.models.equipment import (
    EquipmentAssignment,
    EquipmentItem,
    EquipmentModel,
    EquipmentProtocol,
)
from app.services.admin_cases import rules
from app.services.admin_cases.hooks import _care_owner_id
from app.services.admin_cases.service import AutomaticCase, open_automatic_case
from app.services.consultant_panel_schema import (
    MATERIAL_URL_MAX,
    TRAINER_FORMS,
    TRAINER_SHORT_MAX,
    TRAINER_TEXT_MAX,
)
from app.services.consultant_portal import documents, meetings
from app.services.consultant_portal.auth import PortalContext, PortalError
from app.services.consultant_portal.content import CASE_KEY_PREFIX, waiting_label
from app.services.contract_rates import RATE_SCHEDULE_LOADS
from app.services.equipment import protocols as equipment_protocols
from app.services.hr import client_pack

#: Nabywca na fakturze konsultanta, jak w umowie B2B.
BUYER = {
    "name": "B2B.net S.A.",
    "nip": "5711707392",
    "address": "Al. Jerozolimskie 180, 02-486 Warszawa",
}
#: Tak długo po starcie albo aktywacji ekran „Na start” zostaje w menu.
START_SCREEN_DAYS = 30
MATERIAL_NOT_FOUND = "Nie ma takiego materiału."
PROTOCOL_NOT_FOUND = "Nie ma takiego protokołu."
CLOSED_PROTOCOL = "anulowany"
PROTOCOL_LABELS = {
    "oczekuje": "Czeka na Twoje potwierdzenie",
    "podpisany": "Potwierdzony przez Ciebie, czeka na recepcję",
    "potwierdzony": "Potwierdzony",
}
TRAINER_TITLE = "Zgłoszenie: chcę zostać trenerem"
TRAINER_FORM_LABELS = {
    "online_or_onsite": "online lub u klienta",
    "online": "tylko online",
    "onsite": "tylko u klienta",
}
TRAINER_TOPICS_MAX = 20


# ── Współpraca i menu ────────────────────────────────────────────────────────


def format_pln(amount: str) -> str:
    """„12345.00” → „12 345,00 zł” (jak na fakturze)."""

    whole, _, cents = f"{float(amount):.2f}".partition(".")
    grouped = f"{int(whole):,}".replace(",", " ")
    return f"{grouped},{cents} zł"


def local_date(moment: datetime) -> date:
    return moment.astimezone(ZoneInfo(DEFAULT_TZ)).date()


async def _contract_with_rates(
    db: AsyncSession, contract_id: int
) -> Optional[Contract]:
    return await db.scalar(
        select(Contract)
        .options(*RATE_SCHEDULE_LOADS)
        .where(Contract.id == contract_id)
        .execution_options(populate_existing=True)
    )


def _rate(contract: Contract, today: date) -> Optional[dict[str, str]]:
    amount = Contract._as_decimal(contract.effective_candidate_rate(today))
    if amount is None:
        return None
    return {
        "amount": f"{amount:.2f}",
        "currency": contract.resolved_rate_candidate_currency or "PLN",
        "unit": contract.rate_unit.value if contract.rate_unit else "hourly",
    }


async def _has_equipment(db: AsyncSession, contract_ids: tuple[int, ...]) -> bool:
    return bool(
        await db.scalar(
            select(
                exists().where(
                    EquipmentProtocol.contract_id.in_(contract_ids),
                    EquipmentProtocol.status != CLOSED_PROTOCOL,
                )
            )
        )
    )


def _start_visible(
    contract: Optional[Contract], activation: Optional[CpActivation], today: date
) -> bool:
    """Do 30 dni od późniejszej z dat: startu albo aktywacji, bo materiały dostaje też
    osoba pracująca od dawna, której panel włączamy dopiero teraz."""

    days = [contract.start_date] if contract and contract.start_date else []
    if activation is not None:
        days.append(local_date(activation.activated_at))
    if not days:
        return contract is not None
    return today <= max(days) + timedelta(days=START_SCREEN_DAYS)


async def overview_extra(
    db: AsyncSession, context: PortalContext, *, today: date
) -> dict[str, Any]:
    consultant = context.consultant
    contract = await _contract_with_rates(db, consultant.contract_id)
    activation = await db.scalar(
        select(CpActivation).where(CpActivation.contract_id == consultant.contract_id)
    )
    return {
        "rate": _rate(contract, today) if contract else None,
        "support_phone": settings.CONSULTANT_PORTAL_SUPPORT_PHONE.strip() or None,
        "menu": {
            "start": _start_visible(contract, activation, today),
            "equipment": await _has_equipment(db, consultant.contract_ids),
        },
    }


# ── Do zrobienia ─────────────────────────────────────────────────────────────


async def todo(
    db: AsyncSession, context: PortalContext, *, today: date, now: datetime
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    months = await documents.overview(db, context, today=today)
    activation = await db.scalar(
        select(CpActivation).where(
            CpActivation.contract_id == context.consultant.contract_id
        )
    )
    since = (
        (activation.activated_at.year, activation.activated_at.month)
        if activation
        else (today.year, today.month)
    )
    from app.services.client_settlements import consultant as settlement_view

    contract = await db.get(Contract, context.consultant.contract_id)
    plan = await settlement_view.estimate_todo(
        db,
        context.consultant.contract_id,
        contract.client_id if contract else None,
        today,
    )
    if plan is not None:
        items.append(plan)
    for row in months:
        # Tylko miesiące zamknięte i od aktywacji: wcześniejsze rozliczano mailem,
        # więc zadanie dublowałoby dokumenty u Finansów.
        period = (row["year"], row["month"])
        if not since <= period < (today.year, today.month):
            continue
        settlement = row.get("settlement") or {}
        for index, task in enumerate(settlement.get("todo") or []):
            items.append(
                {
                    "key": f"settlement-{row['year']}-{row['month']}-{index}",
                    "title": task,
                    "detail": f"Za {row['month']:02d}.{row['year']}",
                    "href": "/konsultant/faktury",
                }
            )
        if settlement.get("status") == "needs_fix":
            items.append(
                {
                    "key": f"fix-{row['year']}-{row['month']}",
                    "title": "Popraw RCP",
                    "detail": settlement.get("fix_reason")
                    or f"Za {row['month']:02d}.{row['year']}",
                    "href": "/konsultant/faktury",
                }
            )
            continue
        if row["action"] == "send_invoice":
            amount = (settlement.get("invoice") or {}).get("amount_net")
            items.append(
                {
                    "key": f"invoice-{row['year']}-{row['month']}",
                    "title": "Wyślij fakturę",
                    "detail": f"Za {row['month']:02d}.{row['year']}"
                    + (f" · {format_pln(amount)} netto" if amount else ""),
                    "href": "/konsultant/faktury",
                }
            )
        elif row["action"] == "send_report":
            items.append(
                {
                    "key": f"report-{row['year']}-{row['month']}",
                    "title": "Wyślij raport godzin",
                    "detail": f"Za {row['month']:02d}.{row['year']}",
                    "href": "/konsultant/faktury",
                }
            )
    waiting = await db.scalars(
        select(EquipmentProtocol)
        .where(
            EquipmentProtocol.contract_id.in_(context.consultant.contract_ids),
            EquipmentProtocol.status == "oczekuje",
        )
        .order_by(EquipmentProtocol.protocol_date.desc(), EquipmentProtocol.id.desc())
    )
    for protocol in waiting:
        items.append(
            {
                "key": f"protocol-{protocol.id}",
                "title": "Potwierdź odbiór sprzętu",
                "detail": f"Protokół {protocol.number}",
                "href": "/konsultant/sprzet",
            }
        )
    for meeting in await meetings.own_meetings(db, context, now=now):
        if meeting["can_rate"]:
            items.append(
                {
                    "key": f"rating-{meeting['id']}",
                    "title": "Oceń rozmowę",
                    "detail": meeting["topic_label"],
                    "href": "/konsultant/rozmowy",
                }
            )
    return items


# ── Na start ─────────────────────────────────────────────────────────────────


def material_row(material: ClientOnboardingMaterial) -> dict[str, Any]:
    return {
        "id": material.id,
        "title": material.title,
        "kind": material.kind,
        "url": material.url,
        "file_name": material.file_name,
        "shared": material.client_id is None,
    }


async def _own_materials(
    db: AsyncSession, contract_ids: tuple[int, ...]
) -> list[ClientOnboardingMaterial]:
    rows = await db.scalars(
        select(ClientOnboardingMaterial)
        .join(
            CpActivationMaterial,
            CpActivationMaterial.material_id == ClientOnboardingMaterial.id,
        )
        .join(CpActivation, CpActivation.id == CpActivationMaterial.activation_id)
        .where(
            CpActivation.contract_id.in_(contract_ids),
            CpActivation.deactivated_at.is_(None),
            ClientOnboardingMaterial.active.is_(True),
        )
        .order_by(
            ClientOnboardingMaterial.client_id.is_not(None),
            ClientOnboardingMaterial.position,
            ClientOnboardingMaterial.id,
        )
    )
    return list(rows.unique())


def _document_row(item: client_pack.PackItem) -> dict[str, Any]:
    return {
        "name": item.name,
        "note": item.note,
        "offset_days": item.offset_days,
        "required": item.required,
    }


async def start_screen(
    db: AsyncSession, context: PortalContext, *, today: date
) -> dict[str, Any]:
    consultant = context.consultant
    contract = await db.get(Contract, consultant.contract_id)
    # Osoba już pracuje: pierwszy dzień i dokumenty na start nie mają sensu, zostają materiały.
    started = bool(contract and contract.start_date and contract.start_date < today)
    first_day = (
        None if started else await client_pack.first_day(db, consultant.contract_id)
    )
    pack = (
        await client_pack.load_pack(db, contract.client_id)
        if contract and contract.client_id and not started
        else None
    )
    return {
        "start_date": contract.start_date.isoformat()
        if contract and contract.start_date and not started
        else None,
        "first_day": {
            "place": first_day.place,
            "time": first_day.time,
            "bring": first_day.bring,
            "contact_name": first_day.contact_name,
        }
        if first_day
        else None,
        "documents": [_document_row(item) for item in pack.documents] if pack else [],
        "materials": [
            material_row(material)
            for material in await _own_materials(db, consultant.contract_ids)
        ],
    }


async def own_material_file(
    db: AsyncSession, context: PortalContext, material_id: int
) -> tuple[ClientOnboardingMaterial, Path]:
    for material in await _own_materials(db, context.consultant.contract_ids):
        if material.id == material_id and material.file_path:
            try:
                return material, documents.path_for(material.file_path)
            except FileNotFoundError:
                break
    raise PortalError(MATERIAL_NOT_FOUND, status=404, code="material_not_found")


# ── Sprzęt ───────────────────────────────────────────────────────────────────


async def equipment_screen(db: AsyncSession, context: PortalContext) -> dict[str, Any]:
    contract_ids = context.consultant.contract_ids
    protocols = (
        await db.scalars(
            select(EquipmentProtocol)
            .where(
                EquipmentProtocol.contract_id.in_(contract_ids),
                EquipmentProtocol.status != CLOSED_PROTOCOL,
            )
            .order_by(
                EquipmentProtocol.protocol_date.desc(), EquipmentProtocol.id.desc()
            )
        )
    ).all()
    by_id = {protocol.id: protocol for protocol in protocols}
    held = (
        await db.execute(
            select(EquipmentAssignment, EquipmentItem, EquipmentModel)
            .join(EquipmentItem, EquipmentItem.id == EquipmentAssignment.item_id)
            .join(EquipmentModel, EquipmentModel.id == EquipmentItem.model_id)
            .where(
                EquipmentAssignment.contract_id.in_(contract_ids),
                EquipmentAssignment.returned_at.is_(None),
                EquipmentAssignment.issue_protocol_id.is_not(None),
            )
            .order_by(
                EquipmentAssignment.issued_at.desc(), EquipmentAssignment.id.desc()
            )
        )
    ).all()
    items = []
    for assignment, item, model in held:
        protocol = by_id.get(assignment.issue_protocol_id)
        if protocol is None:
            continue
        items.append(
            {
                "id": assignment.id,
                "name": model.name,
                "category": model.category,
                "inventory_number": item.inventory_number,
                "serial_number": item.serial_number,
                "since": protocol.protocol_date.isoformat(),
                "protocol_id": protocol.id,
                "protocol_number": protocol.number,
                "protocol_status": protocol.status,
                "protocol_label": PROTOCOL_LABELS.get(protocol.status, protocol.status),
            }
        )
    rows = []
    for protocol in protocols:
        lines = await equipment_protocols.protocol_lines(db, protocol.id)
        rows.append(
            {
                "id": protocol.id,
                "number": protocol.number,
                "kind": protocol.kind,
                "date": protocol.protocol_date.isoformat(),
                "status": protocol.status,
                "label": PROTOCOL_LABELS.get(protocol.status, protocol.status),
                "items": [line.name for line in lines],
                "can_confirm": protocol.status == "oczekuje",
            }
        )
    return {"items": items, "protocols": rows}


async def own_protocol(
    db: AsyncSession, context: PortalContext, protocol_id: int
) -> EquipmentProtocol:
    protocol = await db.get(EquipmentProtocol, protocol_id)
    if (
        protocol is None
        or protocol.status == CLOSED_PROTOCOL
        or protocol.contract_id not in context.consultant.contract_ids
    ):
        raise PortalError(PROTOCOL_NOT_FOUND, status=404, code="protocol_not_found")
    return protocol


# ── Rozliczenie ──────────────────────────────────────────────────────────────


async def settlement_screen(db: AsyncSession, context: PortalContext) -> dict[str, Any]:
    contract = await db.get(Contract, context.consultant.contract_id)
    rule = (
        await db.get(ClientSettlementRule, contract.client_id)
        if contract and contract.client_id
        else None
    )
    from app.core.scheduling import business_today
    from app.services.client_settlements import consultant as settlement_view

    today = business_today()
    return {
        "mode": rule.mode if rule else None,
        "instructions": (rule.instructions or None) if rule else None,
        "buyer": BUYER,
        # Termin z reguły klienta (E3.2); bez reguły — 14 dni z umowy B2B.
        "payment_days": await settlement_view.payment_days(
            db,
            contract.client_id if contract else None,
            f"{today.year}-{today.month:02d}",
        ),
    }


# ── Zostań trenerem ──────────────────────────────────────────────────────────


def _clean(value: str, limit: int) -> str:
    return value.replace("\x00", "").strip()[:limit]


async def _trainer_row(
    db: AsyncSession, application: Optional[CpTrainerApplication]
) -> Optional[dict[str, Any]]:
    if application is None:
        return None
    case = await db.get(AdminCase, application.case_id) if application.case_id else None
    return {
        "topics": application.topics,
        "experience": application.experience,
        "form": application.form,
        "day_rate": application.day_rate,
        "availability": application.availability,
        "materials": application.materials,
        "sent_at": application.updated_at.isoformat(),
        "waiting": waiting_label(case.status, None)
        if case
        else {"who": "nobody", "label": "Czeka na przydzielenie osoby"},
    }


async def trainer_application(
    db: AsyncSession, context: PortalContext
) -> Optional[dict[str, Any]]:
    application = await db.scalar(
        select(CpTrainerApplication).where(
            CpTrainerApplication.contract_id.in_(context.consultant.contract_ids)
        )
    )
    return await _trainer_row(db, application)


def _trainer_description(application: CpTrainerApplication) -> str:
    return "\n".join(
        [
            f"Tematy: {', '.join(application.topics) or 'nie podano'}",
            f"Forma: {TRAINER_FORM_LABELS[application.form]}",
            f"Stawka za dzień: {application.day_rate or 'nie podano'}",
            f"Dostępność: {application.availability or 'nie podano'}",
            f"Materiały: {application.materials or 'nie podano'}",
            "",
            application.experience,
        ]
    )


async def save_trainer_application(
    db: AsyncSession,
    context: PortalContext,
    *,
    topics: list[str],
    experience: str,
    form: str,
    day_rate: str,
    availability: str,
    materials: str,
) -> dict[str, Any]:
    """Pierwsze wysłanie zakłada sprawę, a kolejne poprawiają to samo zgłoszenie."""

    clean_topics = [
        topic for topic in dict.fromkeys(_clean(value, 60) for value in topics) if topic
    ][:TRAINER_TOPICS_MAX]
    clean_experience = _clean(experience, TRAINER_TEXT_MAX)
    if not clean_topics or not clean_experience:
        raise PortalError("Podaj tematy szkoleń i swoje doświadczenie.")
    if form not in TRAINER_FORMS:
        raise PortalError("Wybierz formę szkoleń.")
    contract_id = context.consultant.contract_id
    application = await db.scalar(
        select(CpTrainerApplication)
        .where(CpTrainerApplication.contract_id.in_(context.consultant.contract_ids))
        .with_for_update()
    )
    if application is None:
        application = CpTrainerApplication(contract_id=contract_id)
        db.add(application)
    application.topics = clean_topics
    application.experience = clean_experience
    application.form = form
    application.day_rate = _clean(day_rate, TRAINER_SHORT_MAX)
    application.availability = _clean(availability, TRAINER_SHORT_MAX)
    application.materials = _clean(materials, MATERIAL_URL_MAX)
    await db.flush()
    description = _trainer_description(application)
    case = await db.get(AdminCase, application.case_id) if application.case_id else None
    if case is None:
        case, _created = await open_automatic_case(
            db,
            AutomaticCase(
                title=TRAINER_TITLE[: rules.TITLE_MAX],
                area="administration",
                priority="P3",
                source="portal",
                source_key=f"{CASE_KEY_PREFIX}trainer:{uuid4().hex}",
                description=description,
                contract_id=contract_id,
                assignee_user_id=await _care_owner_id(db, contract_id),
            ),
        )
        application.case_id = case.id
    else:
        case.description = description
    await db.flush()
    await db.refresh(application)
    return await _trainer_row(db, application) or {}
