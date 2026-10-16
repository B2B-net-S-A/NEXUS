"""Rejestr sprzętu: cennik, egzemplarze, posiadacze, historia (kroki S1–S2).

Jedna pozycja to jeden egzemplarz. „Wolny” znaczy: stan ``na_stanie`` i brak
aktywnego wydania (indeks częściowy w bazie pilnuje, że wydanie jest najwyżej
jedno). Posiadacz to dokładnie jedno z trzech: konto NEXUSA (pracownik
biura), kontrakt (konsultant u klienta) albo osoba zewnętrzna bez konta
(np. uczestnik Akademii).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal, Optional

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus
from app.models.equipment import (
    EquipmentAssignment,
    EquipmentExternalPerson,
    EquipmentImportRow,
    EquipmentItem,
    EquipmentModel,
    EquipmentProtocol,
)
from app.models.user import User
from app.services import equipment_schema as schema
from app.services.equipment import identifiers, sanitize
from app.services.hr import audit

HolderKind = Literal["user", "contract", "external"]

#: Kontrakty, którym można wydać sprzęt (konsultant przed startem albo w trakcie).
ISSUABLE_CONTRACT_STATUSES = (
    ContractStatus.draft,
    ContractStatus.ready_for_signature,
    ContractStatus.active,
    ContractStatus.ending,
)


class EquipmentError(Exception):
    """Odmowa z polskim zdaniem dla recepcji; ``status`` = kod HTTP trasy."""

    status = 422

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        if status is not None:
            self.status = status


class EquipmentNotFound(EquipmentError):
    status = 404


class EquipmentConflict(EquipmentError):
    status = 409


@dataclass(frozen=True)
class Holder:
    kind: HolderKind
    id: int
    name: str
    email: Optional[str]
    detail: Optional[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "detail": self.detail,
        }


def candidate_name(candidate: Candidate | None) -> str:
    if candidate is None:
        return "Konsultant"
    return (
        " ".join(p for p in (candidate.name, candidate.lastname) if p) or "Konsultant"
    )


async def resolve_holder(db: AsyncSession, kind: str, holder_id: int) -> Holder:
    if kind == "user":
        user = await db.get(User, holder_id)
        if user is None:
            raise EquipmentNotFound("Nie ma takiego konta.")
        return Holder(
            "user", user.id, user.name or user.email, user.email, "Konto NEXUSA"
        )
    if kind == "contract":
        row = (
            await db.execute(
                select(Contract, Candidate, Client)
                .join(Candidate, Candidate.id == Contract.candidate_id)
                .outerjoin(Client, Client.id == Contract.client_id)
                .where(Contract.id == holder_id)
            )
        ).first()
        if row is None:
            raise EquipmentNotFound("Nie ma takiego kontraktu.")
        contract, candidate, client = row
        detail = "Kontraktor"
        if client is not None:
            detail += f" · {client.name}"
        if contract.start_date:
            detail += f" · start {contract.start_date:%d.%m.%Y}"
        email = contract.candidate_email or candidate.email
        return Holder("contract", contract.id, candidate_name(candidate), email, detail)
    if kind == "external":
        person = await db.get(EquipmentExternalPerson, holder_id)
        if person is None:
            raise EquipmentNotFound("Nie ma takiej osoby.")
        return Holder(
            "external",
            person.id,
            person.full_name,
            person.work_email,
            person.note or "Osoba spoza NEXUSA",
        )
    raise EquipmentError("Nieznany rodzaj posiadacza.")


def holder_columns(kind: HolderKind, holder_id: int) -> dict[str, Optional[int]]:
    return {
        "user_id": holder_id if kind == "user" else None,
        "contract_id": holder_id if kind == "contract" else None,
        "external_person_id": holder_id if kind == "external" else None,
    }


def holder_of(row: Any) -> tuple[HolderKind, int] | None:
    """(rodzaj, id) posiadacza z wiersza wydania albo protokołu."""
    if row.user_id is not None:
        return "user", row.user_id
    if row.contract_id is not None:
        return "contract", row.contract_id
    if row.external_person_id is not None:
        return "external", row.external_person_id
    return None


async def search_holders(db: AsyncSession, q: str, *, limit: int = 15) -> list[dict]:
    """Podpowiedzi posiadacza w kreatorze wydania: konta, kontrakty, osoby spoza."""
    needle = f"%{q.strip()}%"
    if len(q.strip()) < 2:
        return []
    out: list[dict] = []
    users = (
        await db.scalars(
            select(User)
            .where(User.is_active.is_(True))
            .where(or_(User.name.ilike(needle), User.email.ilike(needle)))
            .order_by(User.name)
            .limit(limit)
        )
    ).all()
    out += [
        Holder("user", u.id, u.name or u.email, u.email, "Konto NEXUSA").as_dict()
        for u in users
    ]
    full = func.concat_ws(" ", Candidate.name, Candidate.lastname)
    contracts = (
        await db.execute(
            select(Contract, Candidate, Client)
            .join(Candidate, Candidate.id == Contract.candidate_id)
            .outerjoin(Client, Client.id == Contract.client_id)
            .where(Contract.status.in_(ISSUABLE_CONTRACT_STATUSES))
            .where(full.ilike(needle))
            .order_by(Contract.start_date.desc().nulls_last())
            .limit(limit)
        )
    ).all()
    for contract, candidate, client in contracts:
        detail = "Kontraktor" + (f" · {client.name}" if client else "")
        if contract.start_date:
            detail += f" · start {contract.start_date:%d.%m.%Y}"
        out.append(
            Holder(
                "contract",
                contract.id,
                candidate_name(candidate),
                contract.candidate_email or candidate.email,
                detail,
            ).as_dict()
        )
    external = (
        await db.scalars(
            select(EquipmentExternalPerson)
            .where(EquipmentExternalPerson.full_name.ilike(needle))
            .order_by(EquipmentExternalPerson.full_name)
            .limit(limit)
        )
    ).all()
    out += [
        Holder(
            "external", p.id, p.full_name, p.work_email, p.note or "Osoba spoza NEXUSA"
        ).as_dict()
        for p in external
    ]
    return out


# ── Cennik ────────────────────────────────────────────────────────────────────


def model_payload(model: EquipmentModel) -> dict[str, Any]:
    return {
        "id": model.id,
        "category": model.category,
        "name": model.name,
        "manufacturer": model.manufacturer,
        "price_pln": None if model.price_pln is None else str(model.price_pln),
        "is_active": model.is_active,
    }


async def list_models(db: AsyncSession, *, include_inactive: bool = True) -> list[dict]:
    query = select(EquipmentModel).order_by(
        EquipmentModel.category, EquipmentModel.name
    )
    if not include_inactive:
        query = query.where(EquipmentModel.is_active.is_(True))
    counts = dict(
        (
            await db.execute(
                select(EquipmentItem.model_id, func.count())
                .where(EquipmentItem.status != "wycofany")
                .group_by(EquipmentItem.model_id)
            )
        ).all()
    )
    return [
        {**model_payload(m), "items": int(counts.get(m.id, 0))}
        for m in (await db.scalars(query)).all()
    ]


async def _model_name_taken(
    db: AsyncSession, category: str, name: str, *, exclude_id: int | None = None
) -> bool:
    query = select(EquipmentModel.id).where(
        EquipmentModel.category == category, EquipmentModel.name == name
    )
    if exclude_id is not None:
        query = query.where(EquipmentModel.id != exclude_id)
    return (await db.scalar(query)) is not None


def _check_price(category: str, price: Optional[Decimal]) -> Optional[Decimal]:
    if price is not None and price < 0:
        raise EquipmentError("Cena nie może być ujemna.")
    if category in schema.NO_VALUE_CATEGORIES:
        # D6: karta SIM i karta dostępu nie mają wartości w protokole.
        return None
    return price


async def create_model(
    db: AsyncSession, values: dict[str, Any], *, actor: User
) -> EquipmentModel:
    category = values["category"]
    name = " ".join(values["name"].split())
    if not name:
        raise EquipmentError("Podaj nazwę modelu.")
    if await _model_name_taken(db, category, name):
        raise EquipmentConflict("Taki model jest już w cenniku.")
    model = EquipmentModel(
        category=category,
        name=name,
        manufacturer=(values.get("manufacturer") or None),
        price_pln=_check_price(category, values.get("price_pln")),
        is_active=values.get("is_active", True),
        created_by=actor.id,
    )
    db.add(model)
    await db.flush()
    return model


async def update_model(
    db: AsyncSession, model_id: int, values: dict[str, Any], *, actor: User
) -> EquipmentModel:
    model = await db.get(EquipmentModel, model_id)
    if model is None:
        raise EquipmentNotFound("Nie ma takiego modelu.")
    if "name" in values and values["name"] is not None:
        name = " ".join(values["name"].split())
        if not name:
            raise EquipmentError("Podaj nazwę modelu.")
        if await _model_name_taken(db, model.category, name, exclude_id=model.id):
            raise EquipmentConflict("Taki model jest już w cenniku.")
        model.name = name
    if "manufacturer" in values:
        model.manufacturer = values["manufacturer"] or None
    if "price_pln" in values:
        # Zmiana ceny nie rusza protokołów: wartości są w nich zamrożone.
        model.price_pln = _check_price(model.category, values["price_pln"])
    if "is_active" in values and values["is_active"] is not None:
        model.is_active = bool(values["is_active"])
    await db.flush()
    return model


async def get_or_create_model(
    db: AsyncSession,
    *,
    category: str,
    name: str,
    manufacturer: Optional[str] = None,
    price: Optional[Decimal] = None,
    actor: User | None = None,
) -> EquipmentModel:
    clean = " ".join(name.split())[:200] or identifiers.CATEGORY_LABELS[category]
    model = await db.scalar(
        select(EquipmentModel).where(
            EquipmentModel.category == category, EquipmentModel.name == clean
        )
    )
    if model is not None:
        return model
    model = EquipmentModel(
        category=category,
        name=clean,
        manufacturer=manufacturer,
        price_pln=_check_price(category, price),
        created_by=actor.id if actor else None,
    )
    db.add(model)
    await db.flush()
    return model


# ── Egzemplarze ───────────────────────────────────────────────────────────────

ITEM_FIELDS: tuple[str, ...] = (
    "inventory_number",
    "serial_number",
    "imei",
    "iccid",
    "phone_number",
    "access_card_number",
    "ownership",
    "purchase_date",
    "location",
    "notes",
)


async def identifier_conflicts(
    db: AsyncSession, values: dict[str, Optional[str]], *, exclude_id: int | None = None
) -> list[str]:
    """Zdania „numer X jest już w rejestrze (pozycja …)” dla zajętych numerów."""
    problems: list[str] = []
    for field in schema.ITEM_UNIQUE_COLUMNS:
        value = values.get(field)
        if not value:
            continue
        column = getattr(EquipmentItem, field)
        query = select(EquipmentItem.id, EquipmentItem.inventory_number).where(
            column == value
        )
        if exclude_id is not None:
            query = query.where(EquipmentItem.id != exclude_id)
        hit = (await db.execute(query)).first()
        if hit is not None:
            label = identifiers.FIELD_LABELS[field]
            where = hit.inventory_number or f"#{hit.id}"
            problems.append(f"{label} {value} jest już w rejestrze (pozycja {where})")
    return problems


def _clean_notes(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = sanitize.clean_text(value)
    if cleaned.reasons:
        raise EquipmentError(
            "Notatka zawiera dane, których NEXUS nie przechowuje ("
            + ", ".join(cleaned.reasons)
            + ")."
        )
    return cleaned.value


def _normalized(values: dict[str, Any]) -> dict[str, Any]:
    out = dict(values)
    try:
        out.update(
            identifiers.normalize_identifiers(
                {k: values[k] for k in schema.ITEM_UNIQUE_COLUMNS if k in values}
            )
        )
    except identifiers.IdentifierError as exc:
        raise EquipmentError(str(exc)) from exc
    for field in schema.ITEM_UNIQUE_COLUMNS:
        value = out.get(field)
        if value and sanitize.is_bitlocker_key(value):
            raise EquipmentError(
                "Ten numer wygląda na klucz BitLocker — nie wpisuj go tutaj."
            )
    if "notes" in out:
        out["notes"] = _clean_notes(out["notes"])
    if "location" in out and out["location"] is not None:
        out["location"] = " ".join(str(out["location"]).split()) or None
    return out


async def create_item(
    db: AsyncSession, values: dict[str, Any], *, actor: User
) -> EquipmentItem:
    model = await db.get(EquipmentModel, values["model_id"])
    if model is None:
        raise EquipmentNotFound("Nie ma takiego modelu w cenniku.")
    data = _normalized({k: values.get(k) for k in ITEM_FIELDS if k in values})
    status = values.get("status") or "na_stanie"
    if status == "wydany":
        raise EquipmentError("Stan „Wydany” nadaje dopiero wydanie z protokołem.")
    if not any(data.get(f) for f in schema.ITEM_UNIQUE_COLUMNS):
        raise EquipmentError(
            "Podaj co najmniej jeden numer: ewidencyjny, seryjny, IMEI, ICCID, "
            "telefonu albo karty."
        )
    problems = await identifier_conflicts(db, data)
    if problems:
        raise EquipmentConflict(problems[0][0].upper() + problems[0][1:] + ".")
    item = EquipmentItem(
        model_id=model.id,
        status=status,
        ownership=data.pop("ownership", None) or "nasz",
        created_by=actor.id,
        updated_by=actor.id,
        **data,
    )
    db.add(item)
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=None,
        entity_type="equipment_item",
        entity_id=item.id,
        action="item_created",
        details={"category": model.category, "status": status},
    )
    return item


async def active_assignment(
    db: AsyncSession, item_id: int
) -> Optional[EquipmentAssignment]:
    return await db.scalar(
        select(EquipmentAssignment).where(
            EquipmentAssignment.item_id == item_id,
            EquipmentAssignment.returned_at.is_(None),
        )
    )


async def update_item(
    db: AsyncSession, item_id: int, values: dict[str, Any], *, actor: User
) -> EquipmentItem:
    item = await db.get(EquipmentItem, item_id, with_for_update=True)
    if item is None:
        raise EquipmentNotFound("Nie ma takiej pozycji.")
    data = _normalized({k: v for k, v in values.items() if k in ITEM_FIELDS})
    problems = await identifier_conflicts(db, data, exclude_id=item.id)
    if problems:
        raise EquipmentConflict(problems[0][0].upper() + problems[0][1:] + ".")
    if "model_id" in values and values["model_id"] is not None:
        model = await db.get(EquipmentModel, values["model_id"])
        if model is None:
            raise EquipmentNotFound("Nie ma takiego modelu w cenniku.")
        item.model_id = model.id
    status = values.get("status")
    if status is not None and status != item.status:
        if status == "wydany":
            raise EquipmentError("Stan „Wydany” nadaje dopiero wydanie z protokołem.")
        if await active_assignment(db, item.id) is not None:
            raise EquipmentConflict("Pozycja jest wydana — najpierw przyjmij zwrot.")
        item.status = status
    for field, value in data.items():
        setattr(
            item, field, value if field != "ownership" else (value or item.ownership)
        )
    item.updated_by = actor.id
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=None,
        entity_type="equipment_item",
        entity_id=item.id,
        action="item_updated",
        details={"fields": sorted({*data, *(["status"] if status else [])})},
    )
    return item


async def delete_item(db: AsyncSession, item_id: int, *, actor: User) -> None:
    item = await db.get(EquipmentItem, item_id, with_for_update=True)
    if item is None:
        raise EquipmentNotFound("Nie ma takiej pozycji.")
    used = await db.scalar(
        select(func.count()).where(EquipmentAssignment.item_id == item.id)
    )
    if used:
        raise EquipmentConflict(
            "Pozycja ma historię wydań — zamiast usuwać, ustaw stan „Wycofany”."
        )
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=None,
        entity_type="equipment_item",
        entity_id=item.id,
        action="item_deleted",
    )
    await db.delete(item)
    await db.flush()


def _holder_name_expr():
    """Nazwa posiadacza aktywnego wydania (konto, konsultant albo osoba spoza)."""
    return func.coalesce(
        User.name,
        func.nullif(func.concat_ws(" ", Candidate.name, Candidate.lastname), ""),
        EquipmentExternalPerson.full_name,
    )


def _active_join(query):
    active = EquipmentAssignment
    return (
        query.outerjoin(
            active,
            and_(active.item_id == EquipmentItem.id, active.returned_at.is_(None)),
        )
        .outerjoin(User, User.id == active.user_id)
        .outerjoin(Contract, Contract.id == active.contract_id)
        .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
        .outerjoin(Client, Client.id == Contract.client_id)
        .outerjoin(
            EquipmentExternalPerson,
            EquipmentExternalPerson.id == active.external_person_id,
        )
    )


def item_payload(
    item: EquipmentItem,
    model: EquipmentModel,
    assignment: EquipmentAssignment | None = None,
    holder_name: str | None = None,
    client_name: str | None = None,
    protocol: tuple[int, str, str] | None = None,
) -> dict[str, Any]:
    holder = None
    if assignment is not None:
        kind, holder_id = holder_of(assignment) or ("user", 0)
        holder = {
            "kind": kind,
            "id": holder_id,
            "name": holder_name or "—",
            "client_name": client_name,
            "assignment_id": assignment.id,
            "issued_at": assignment.issued_at.isoformat()
            if assignment.issued_at
            else None,
        }
    return {
        "id": item.id,
        "model": model_payload(model),
        "category": model.category,
        "inventory_number": item.inventory_number,
        "serial_number": item.serial_number,
        "imei": item.imei,
        "iccid": item.iccid,
        "phone_number": item.phone_number,
        "access_card_number": item.access_card_number,
        "status": item.status,
        "ownership": item.ownership,
        "purchase_date": item.purchase_date.isoformat() if item.purchase_date else None,
        "location": item.location,
        "notes": item.notes,
        "holder": holder,
        "issue_protocol": (
            {"id": protocol[0], "number": protocol[1], "status": protocol[2]}
            if protocol
            else None
        ),
    }


async def list_items(
    db: AsyncSession,
    *,
    category: Optional[str] = None,
    status: Optional[str] = None,
    holder: Optional[str] = None,
    q: Optional[str] = None,
    free_only: bool = False,
    limit: int = 200,
    offset: int = 0,
) -> dict[str, Any]:
    holder_name = _holder_name_expr()
    query = _active_join(
        select(
            EquipmentItem,
            EquipmentModel,
            EquipmentAssignment,
            holder_name.label("holder_name"),
            Client.name.label("client_name"),
            EquipmentProtocol.id,
            EquipmentProtocol.number,
            EquipmentProtocol.status,
        ).join(EquipmentModel, EquipmentModel.id == EquipmentItem.model_id)
    ).outerjoin(
        EquipmentProtocol, EquipmentProtocol.id == EquipmentAssignment.issue_protocol_id
    )
    if category:
        query = query.where(EquipmentModel.category == category)
    if status:
        query = query.where(EquipmentItem.status == status)
    if free_only:
        query = query.where(
            EquipmentItem.status == "na_stanie", EquipmentAssignment.id.is_(None)
        )
    if holder == "none":
        query = query.where(EquipmentAssignment.id.is_(None))
    elif holder in ("user", "contract", "external"):
        column = {
            "user": EquipmentAssignment.user_id,
            "contract": EquipmentAssignment.contract_id,
            "external": EquipmentAssignment.external_person_id,
        }[holder]
        query = query.where(column.is_not(None))
    if q and q.strip():
        needle = f"%{q.strip()}%"
        digits = "".join(ch for ch in q if ch.isdigit())
        conditions = [
            EquipmentItem.inventory_number.ilike(needle),
            EquipmentItem.serial_number.ilike(needle),
            EquipmentItem.access_card_number.ilike(needle),
            EquipmentModel.name.ilike(needle),
            holder_name.ilike(needle),
        ]
        if len(digits) >= 3:
            conditions += [
                EquipmentItem.imei.contains(digits),
                EquipmentItem.iccid.contains(digits),
                EquipmentItem.phone_number.contains(digits[-9:]),
            ]
        query = query.where(or_(*conditions))
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        await db.execute(
            query.order_by(
                EquipmentModel.category,
                EquipmentItem.inventory_number,
                EquipmentItem.id,
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()
    items = [
        item_payload(
            item,
            model,
            assignment,
            name,
            client,
            (pid, number, pstatus) if pid else None,
        )
        for item, model, assignment, name, client, pid, number, pstatus in rows
    ]
    return {"items": items, "total": int(total or 0)}


async def assignment_history(db: AsyncSession, *, where: Any) -> list[dict[str, Any]]:
    holder_name = _holder_name_expr()
    issue = EquipmentProtocol.__table__.alias("issue_protocol")
    back = EquipmentProtocol.__table__.alias("return_protocol")
    rows = (
        await db.execute(
            select(
                EquipmentAssignment,
                EquipmentItem,
                EquipmentModel,
                holder_name.label("holder_name"),
                Client.name.label("client_name"),
                issue.c.number,
                back.c.number,
            )
            .join(EquipmentItem, EquipmentItem.id == EquipmentAssignment.item_id)
            .join(EquipmentModel, EquipmentModel.id == EquipmentItem.model_id)
            .outerjoin(User, User.id == EquipmentAssignment.user_id)
            .outerjoin(Contract, Contract.id == EquipmentAssignment.contract_id)
            .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
            .outerjoin(Client, Client.id == Contract.client_id)
            .outerjoin(
                EquipmentExternalPerson,
                EquipmentExternalPerson.id == EquipmentAssignment.external_person_id,
            )
            .outerjoin(issue, issue.c.id == EquipmentAssignment.issue_protocol_id)
            .outerjoin(back, back.c.id == EquipmentAssignment.return_protocol_id)
            .where(where)
            .order_by(
                EquipmentAssignment.issued_at.desc(), EquipmentAssignment.id.desc()
            )
        )
    ).all()
    out = []
    for assignment, item, model, name, client, issue_no, return_no in rows:
        kind, holder_id = holder_of(assignment) or ("user", 0)
        out.append(
            {
                "assignment_id": assignment.id,
                "item_id": item.id,
                "category": model.category,
                "model_name": model.name,
                "inventory_number": item.inventory_number,
                "serial_number": item.serial_number,
                "imei": item.imei,
                "phone_number": item.phone_number,
                "access_card_number": item.access_card_number,
                "ownership": item.ownership,
                "item_status": item.status,
                "holder": {
                    "kind": kind,
                    "id": holder_id,
                    "name": name or "—",
                    "client_name": client,
                },
                "issued_at": assignment.issued_at.isoformat(),
                "returned_at": (
                    assignment.returned_at.isoformat()
                    if assignment.returned_at
                    else None
                ),
                "return_condition": assignment.return_condition,
                "return_notes": assignment.return_notes,
                "issue_protocol": issue_no,
                "issue_protocol_id": assignment.issue_protocol_id,
                "return_protocol": return_no,
                "return_protocol_id": assignment.return_protocol_id,
                "unit_value": (
                    None
                    if model.price_pln is None
                    or model.category in schema.NO_VALUE_CATEGORIES
                    else str(model.price_pln)
                ),
            }
        )
    return out


async def item_detail(db: AsyncSession, item_id: int) -> dict[str, Any]:
    listing = await db.execute(
        _active_join(
            select(
                EquipmentItem,
                EquipmentModel,
                EquipmentAssignment,
                _holder_name_expr(),
                Client.name,
            ).join(EquipmentModel, EquipmentModel.id == EquipmentItem.model_id)
        ).where(EquipmentItem.id == item_id)
    )
    row = listing.first()
    if row is None:
        raise EquipmentNotFound("Nie ma takiej pozycji.")
    item, model, assignment, name, client = row
    payload = item_payload(item, model, assignment, name, client)
    payload["history"] = await assignment_history(
        db, where=EquipmentAssignment.item_id == item_id
    )
    return payload


async def holder_equipment(
    db: AsyncSession, kind: HolderKind, holder_id: int
) -> dict[str, Any]:
    """Sprzęt osoby albo kontraktu: aktywne wydania i historia."""
    column = holder_columns(kind, holder_id)
    where = {
        "user": EquipmentAssignment.user_id == holder_id,
        "contract": EquipmentAssignment.contract_id == holder_id,
        "external": EquipmentAssignment.external_person_id == holder_id,
    }[kind]
    history = await assignment_history(db, where=where)
    active = [row for row in history if row["returned_at"] is None]
    protocols = (
        await db.scalars(
            select(EquipmentProtocol)
            .where(
                *(
                    getattr(EquipmentProtocol, field) == value
                    for field, value in column.items()
                    if value is not None
                )
            )
            .order_by(
                EquipmentProtocol.protocol_date.desc(), EquipmentProtocol.id.desc()
            )
        )
    ).all()
    return {
        "active": active,
        "history": [row for row in history if row["returned_at"] is not None],
        "protocols": [
            {
                "id": p.id,
                "number": p.number,
                "kind": p.kind,
                "status": p.status,
                "protocol_date": p.protocol_date.isoformat(),
            }
            for p in protocols
        ],
    }


async def summary(db: AsyncSession) -> dict[str, Any]:
    free = dict(
        (
            await db.execute(
                select(EquipmentModel.category, func.count())
                .select_from(EquipmentItem)
                .join(EquipmentModel, EquipmentModel.id == EquipmentItem.model_id)
                .outerjoin(
                    EquipmentAssignment,
                    and_(
                        EquipmentAssignment.item_id == EquipmentItem.id,
                        EquipmentAssignment.returned_at.is_(None),
                    ),
                )
                .where(
                    EquipmentItem.status == "na_stanie",
                    EquipmentAssignment.id.is_(None),
                )
                .group_by(EquipmentModel.category)
            )
        ).all()
    )
    by_status = dict(
        (
            await db.execute(
                select(EquipmentItem.status, func.count()).group_by(
                    EquipmentItem.status
                )
            )
        ).all()
    )
    waiting = await db.scalar(
        select(func.count()).where(
            EquipmentProtocol.status.in_(("oczekuje", "podpisany"))
        )
    )
    unresolved = await db.scalar(
        select(func.count()).where(
            EquipmentImportRow.decision == "do_wyjasnienia",
            EquipmentImportRow.item_id.is_(None),
        )
    )
    return {
        "free_by_category": {c: int(free.get(c, 0)) for c in schema.CATEGORIES},
        "by_status": {s: int(by_status.get(s, 0)) for s in schema.ITEM_STATUSES},
        "protocols_waiting": int(waiting or 0),
        "import_unresolved": int(unresolved or 0),
    }


# ── Osoby spoza NEXUSA ────────────────────────────────────────────────────────


def external_payload(person: EquipmentExternalPerson) -> dict[str, Any]:
    return {
        "id": person.id,
        "full_name": person.full_name,
        "work_email": person.work_email,
        "note": person.note,
    }


async def list_external_people(db: AsyncSession, q: Optional[str]) -> list[dict]:
    query = select(EquipmentExternalPerson).order_by(EquipmentExternalPerson.full_name)
    if q and q.strip():
        query = query.where(EquipmentExternalPerson.full_name.ilike(f"%{q.strip()}%"))
    return [external_payload(p) for p in (await db.scalars(query.limit(100))).all()]


async def create_external_person(
    db: AsyncSession, values: dict[str, Any], *, actor: User
) -> EquipmentExternalPerson:
    name = " ".join((values.get("full_name") or "").split())
    if not name:
        raise EquipmentError("Podaj imię i nazwisko.")
    email = (values.get("work_email") or "").strip() or None
    if email and sanitize.is_private_email(email):
        raise EquipmentError(
            "Podaj e-mail służbowy — prywatnych adresów NEXUS nie przechowuje."
        )
    person = EquipmentExternalPerson(
        full_name=name,
        work_email=email,
        note=(values.get("note") or None),
        created_by=actor.id,
    )
    db.add(person)
    await db.flush()
    return person


# ── Zakładka „Sprzęt” kontraktu ↔ rejestr ─────────────────────────────────────


async def link_contract_equipment(db: AsyncSession) -> None:
    """Jednoznaczne dopasowanie pozycji kontraktów do egzemplarzy (jak przy starcie)."""
    await db.execute(text(schema.LINK_CONTRACT_EQUIPMENT_SQL))
    await db.execute(text(schema.LINK_CONTRACT_ASSIGNMENTS_SQL))


async def client_provider(db: AsyncSession, client_id: int) -> Optional[str]:
    return await db.scalar(
        text("SELECT equipment_provider FROM clients WHERE id = :id"), {"id": client_id}
    )


async def set_client_provider(
    db: AsyncSession, client_id: int, provider: str, *, actor: User
) -> str:
    if provider not in schema.PROVIDERS:
        raise EquipmentError("Nieznana wartość: od nas, od klienta albo nie wiadomo.")
    result = await db.execute(
        text(
            "UPDATE clients SET equipment_provider = :p WHERE id = :id "
            "RETURNING equipment_provider"
        ),
        {"p": provider, "id": client_id},
    )
    value = result.scalar()
    if value is None:
        raise EquipmentNotFound("Nie ma takiego klienta.")
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=None,
        entity_type="client",
        entity_id=client_id,
        action="equipment_provider_set",
        details={"equipment_provider": provider},
    )
    return value
