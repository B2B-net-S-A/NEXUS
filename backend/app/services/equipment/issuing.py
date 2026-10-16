"""Wydanie i zwrot sprzętu z protokołem — jedna transakcja na operację.

Wydanie: posiadacz → pozycje → protokół. Posiadacz to konto, kontrakt, osoba
spoza NEXUSA albo uczestnik Akademii po zaliczonym zadaniu (rezygnacja
i wykluczenie zamykają wydawanie). Egzemplarze są blokowane
(``FOR UPDATE``), każdy musi być „na stanie” i bez aktywnego wydania;
statusy, wydania, protokół i — dla konsultanta — pozycje zakładki „Sprzęt”
kontraktu powstają razem albo wcale. Wartość pozycji pochodzi z cennika
modelu; zmiana przy wydaniu dotyczy tylko tego protokołu. Karta SIM i karta
dostępu są w protokole bez wartości (D6).

Zwrot: jeden protokół na jednego posiadacza; stan przy zwrocie decyduje
o stanie egzemplarza (uszkodzony → serwis, zgubiony → zgubiony).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.academy import AcademyApplication
from app.models.contract import Contract
from app.models.contract_equipment import (
    ContractEquipment,
    EquipmentItemType,
    EquipmentOwner,
    EquipmentReturnStatus,
)
from app.models.equipment import (
    EquipmentAssignment,
    EquipmentItem,
    EquipmentModel,
    EquipmentProtocol,
)
from app.models.user import User
from app.services import equipment_schema as schema
from app.services.equipment import identifiers, protocols, tasks
from app.services.equipment.registry import (
    ISSUABLE_ACADEMY_STATUSES,
    ISSUABLE_CONTRACT_STATUSES,
    EquipmentConflict,
    EquipmentError,
    EquipmentNotFound,
    Holder,
    holder_columns,
    holder_of,
    resolve_holder,
)
from app.services.hr import audit

CONTRACT_ITEM_TYPES: dict[str, EquipmentItemType] = {
    "laptop": EquipmentItemType.laptop,
    "telefon": EquipmentItemType.phone,
    "monitor": EquipmentItemType.monitor,
    "karta_sim": EquipmentItemType.sim_card,
    "karta_dostepu": EquipmentItemType.keycard,
    "akcesorium": EquipmentItemType.other,
    "inne": EquipmentItemType.other,
}

_NAME_PREFIX = {
    "laptop": "Laptop",
    "telefon": "Telefon",
    "monitor": "Monitor",
}

_STATUS_AFTER_RETURN = {
    "sprawny": "na_stanie",
    "niekompletny": "na_stanie",
    "uszkodzony": "serwis",
    "zgubiony": "zgubiony",
}


@dataclass(frozen=True)
class IssueLine:
    item_id: int
    unit_value: Optional[Decimal] = None
    accessories: Optional[str] = None


@dataclass(frozen=True)
class ReturnLine:
    assignment_id: int
    condition: str
    notes: Optional[str] = None


@dataclass(frozen=True)
class IssueResult:
    protocol: EquipmentProtocol
    assignments: list[EquipmentAssignment]
    link_token: Optional[str]


def line_name(
    item: EquipmentItem, model: EquipmentModel, accessories: Optional[str]
) -> str:
    """Nazwa pozycji jak w protokole recepcji: „Laptop DELL Vostro 3530 (221) zasilacz…”."""
    if model.category == "karta_sim":
        number = identifiers.phone_display(item.phone_number)
        base = "Karta SIM" + (f" {number}" if number else "")
    elif model.category == "karta_dostepu":
        number = item.access_card_number or item.inventory_number
        base = "Karta dostępu" + (f" nr {number}" if number else "")
    else:
        prefix = _NAME_PREFIX.get(model.category)
        name = model.name
        if prefix and not name.casefold().startswith(prefix.casefold()):
            name = f"{prefix} {name}"
        base = name + (f" ({item.inventory_number})" if item.inventory_number else "")
    extra = " ".join((accessories or "").split())
    return f"{base} {extra}".strip()


def line_identifier(item: EquipmentItem, category: str) -> Optional[str]:
    if category == "telefon":
        if item.imei:
            return f"IMEI: {item.imei}"
        return f"S/N:{item.serial_number}" if item.serial_number else None
    if category == "karta_sim":
        if item.iccid:
            return f"ICCID: {item.iccid}"
        return identifiers.phone_display(item.phone_number)
    if category == "karta_dostepu":
        return item.access_card_number or item.inventory_number
    if category == "laptop":
        return item.serial_number
    return f"S/N:{item.serial_number}" if item.serial_number else None


def item_label(item: EquipmentItem, model: EquipmentModel) -> str:
    number = (
        item.inventory_number
        or item.serial_number
        or item.phone_number
        or f"#{item.id}"
    )
    return f"{model.name} ({number})"


async def _locked_items(
    db: AsyncSession, item_ids: Sequence[int]
) -> dict[int, tuple[EquipmentItem, EquipmentModel]]:
    rows = (
        await db.execute(
            select(EquipmentItem, EquipmentModel)
            .join(EquipmentModel, EquipmentModel.id == EquipmentItem.model_id)
            .where(EquipmentItem.id.in_(item_ids))
            .order_by(EquipmentItem.id)
            .with_for_update(of=EquipmentItem)
        )
    ).all()
    return {item.id: (item, model) for item, model in rows}


async def _check_holder(db: AsyncSession, holder: Holder) -> Optional[Contract]:
    if holder.kind == "user":
        user = await db.get(User, holder.id)
        if user is None or not user.is_active:
            raise EquipmentError("To konto jest nieaktywne — sprzętu nie wydamy.")
        return None
    if holder.kind == "contract":
        contract = await db.get(Contract, holder.id)
        if contract is None:
            raise EquipmentNotFound("Nie ma takiego kontraktu.")
        if contract.status not in ISSUABLE_CONTRACT_STATUSES:
            raise EquipmentError("Kontrakt jest zakończony — sprzętu nie wydamy.")
        return contract
    if holder.kind == "academy":
        application = await db.get(AcademyApplication, holder.id)
        if application is None:
            raise EquipmentNotFound("Nie ma takiego zgłoszenia Akademii.")
        if application.status not in ISSUABLE_ACADEMY_STATUSES:
            raise EquipmentConflict(
                "Ta osoba nie jest uczestnikiem edycji (rezygnacja, wykluczenie "
                "albo przed zaliczonym zadaniem) — sprzętu nie wydamy."
            )
    return None


async def issue(
    db: AsyncSession,
    *,
    holder_kind: str,
    holder_id: int,
    lines: Sequence[IssueLine],
    protocol_date: date,
    actor: User,
    with_link: bool = False,
) -> IssueResult:
    if not lines:
        raise EquipmentError("Dodaj co najmniej jedną pozycję.")
    ids = [line.item_id for line in lines]
    if len(set(ids)) != len(ids):
        raise EquipmentError("Ta sama pozycja jest na liście dwa razy.")
    holder = await resolve_holder(db, holder_kind, holder_id)
    contract = await _check_holder(db, holder)
    locked = await _locked_items(db, ids)
    missing = [item_id for item_id in ids if item_id not in locked]
    if missing:
        raise EquipmentNotFound("Nie ma takiej pozycji w rejestrze.")
    busy = set(
        (
            await db.scalars(
                select(EquipmentAssignment.item_id).where(
                    EquipmentAssignment.item_id.in_(ids),
                    EquipmentAssignment.returned_at.is_(None),
                )
            )
        ).all()
    )
    for item_id in ids:
        item, model = locked[item_id]
        if item.status != "na_stanie" or item_id in busy:
            label = identifiers.STATUS_LABELS.get(item.status, item.status)
            raise EquipmentConflict(
                f"Pozycji {item_label(item, model)} nie da się wydać: stan „{label}”."
            )
    snapshot: list[dict[str, Any]] = []
    for line in lines:
        item, model = locked[line.item_id]
        value: Optional[Decimal] = None
        if model.category not in schema.NO_VALUE_CATEGORIES:
            value = line.unit_value if line.unit_value is not None else model.price_pln
            if value is not None and value < 0:
                raise EquipmentError("Wartość pozycji nie może być ujemna.")
        snapshot.append(
            {
                "item_id": item.id,
                "category": model.category,
                "name": line_name(item, model, line.accessories),
                "identifier": line_identifier(item, model.category),
                "quantity": 1,
                "unit_value": value,
            }
        )
    protocol = await protocols.create_protocol(
        db,
        kind="wydanie",
        holder=holder,
        lines=snapshot,
        protocol_date=protocol_date,
        actor=actor,
    )
    now = datetime.now(timezone.utc)
    assignments: list[EquipmentAssignment] = []
    for line in lines:
        item, _model = locked[line.item_id]
        assignment = EquipmentAssignment(
            item_id=item.id,
            issued_at=now,
            issue_protocol_id=protocol.id,
            issued_by=actor.id,
            **holder_columns(holder.kind, holder.id),
        )
        db.add(assignment)
        item.status = "wydany"
        item.updated_by = actor.id
        assignments.append(assignment)
    await db.flush()
    by_item = {a.item_id: a for a in assignments}
    for protocol_line in await protocols.protocol_lines(db, protocol.id):
        if protocol_line.item_id in by_item:
            protocol_line.assignment_id = by_item[protocol_line.item_id].id
    if contract is not None:
        for line in lines:
            item, model = locked[line.item_id]
            assignment = by_item[item.id]
            db.add(
                ContractEquipment(
                    contract_id=contract.id,
                    item_type=CONTRACT_ITEM_TYPES[model.category],
                    owner=(
                        EquipmentOwner.ours
                        if item.ownership == "nasz"
                        else EquipmentOwner.client
                    ),
                    brand_model=model.name[:200],
                    serial_number=(
                        item.serial_number
                        or item.imei
                        or item.iccid
                        or item.access_card_number
                    ),
                    description=f"Protokół {protocol.number}",
                    handed_over_date=protocol_date,
                    return_due_date=contract.end_date,
                    item_id=item.id,
                    assignment_id=assignment.id,
                )
            )
    link_token: Optional[str] = None
    if with_link:
        _link, link_token = await protocols.create_link(db, protocol, actor=actor)
    await tasks.ensure_signature_task(db, protocol)
    await tasks.close_holder_tasks(
        db,
        kind="wydanie",
        holder=holder_columns(holder.kind, holder.id),
        actor=actor,
    )
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=holder.id if holder.kind == "user" else None,
        entity_type="equipment_protocol",
        entity_id=protocol.id,
        action="equipment_issued",
        details={
            "holder_kind": holder.kind,
            "holder_id": holder.id,
            "items": len(lines),
        },
    )
    return IssueResult(
        protocol=protocol, assignments=assignments, link_token=link_token
    )


async def return_items(
    db: AsyncSession,
    *,
    lines: Sequence[ReturnLine],
    protocol_date: date,
    actor: User,
) -> EquipmentProtocol:
    if not lines:
        raise EquipmentError("Wybierz co najmniej jedną pozycję do zwrotu.")
    ids = [line.assignment_id for line in lines]
    if len(set(ids)) != len(ids):
        raise EquipmentError("Ta sama pozycja jest na liście dwa razy.")
    for line in lines:
        if line.condition not in schema.RETURN_CONDITIONS:
            raise EquipmentError("Wybierz stan przy zwrocie.")
    assignments = {
        a.id: a
        for a in (
            await db.scalars(
                select(EquipmentAssignment)
                .where(EquipmentAssignment.id.in_(ids))
                .with_for_update()
            )
        ).all()
    }
    if len(assignments) != len(ids):
        raise EquipmentNotFound("Nie ma takiego wydania.")
    if any(a.returned_at is not None for a in assignments.values()):
        raise EquipmentConflict("Część pozycji jest już zwrócona — odśwież listę.")
    holders = {holder_of(a) for a in assignments.values()}
    if len(holders) != 1:
        raise EquipmentError("Jeden protokół zwrotu dotyczy jednej osoby.")
    (holder_ref,) = holders
    assert holder_ref is not None
    holder = await resolve_holder(db, holder_ref[0], holder_ref[1])
    locked = await _locked_items(db, [a.item_id for a in assignments.values()])
    snapshot = []
    for line in lines:
        assignment = assignments[line.assignment_id]
        item, model = locked[assignment.item_id]
        snapshot.append(
            {
                "item_id": item.id,
                "assignment_id": assignment.id,
                "category": model.category,
                "name": line_name(item, model, None),
                "identifier": line_identifier(item, model.category),
                "quantity": 1,
                "unit_value": None,
                "condition": line.condition,
                "notes": (" ".join((line.notes or "").split()) or None),
            }
        )
    protocol = await protocols.create_protocol(
        db,
        kind="zwrot",
        holder=holder,
        lines=snapshot,
        protocol_date=protocol_date,
        actor=actor,
    )
    now = datetime.now(timezone.utc)
    for line in lines:
        assignment = assignments[line.assignment_id]
        item, _model = locked[assignment.item_id]
        assignment.returned_at = max(now, assignment.issued_at)
        assignment.return_condition = line.condition
        assignment.return_notes = " ".join((line.notes or "").split()) or None
        assignment.return_protocol_id = protocol.id
        assignment.returned_by = actor.id
        item.status = _STATUS_AFTER_RETURN[line.condition]
        item.updated_by = actor.id
    rows = (
        await db.scalars(
            select(ContractEquipment).where(ContractEquipment.assignment_id.in_(ids))
        )
    ).all()
    conditions = {line.assignment_id: line.condition for line in lines}
    for row in rows:
        lost = conditions.get(row.assignment_id or 0) == "zgubiony"
        row.return_status = (
            EquipmentReturnStatus.lost if lost else EquipmentReturnStatus.returned
        )
        row.returned_date = protocol_date
    await db.flush()
    columns = holder_columns(holder.kind, holder.id)
    still_active = await db.scalar(
        select(EquipmentAssignment.id)
        .where(
            EquipmentAssignment.returned_at.is_(None),
            *(
                getattr(EquipmentAssignment, column) == value
                for column, value in columns.items()
                if value is not None
            ),
        )
        .limit(1)
    )
    if still_active is None:
        await tasks.close_holder_tasks(db, kind="zwrot", holder=columns, actor=actor)
    await tasks.ensure_signature_task(db, protocol)
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=holder.id if holder.kind == "user" else None,
        entity_type="equipment_protocol",
        entity_id=protocol.id,
        action="equipment_returned",
        details={
            "holder_kind": holder.kind,
            "holder_id": holder.id,
            "items": len(lines),
            "conditions": sorted({line.condition for line in lines}),
        },
    )
    return protocol
