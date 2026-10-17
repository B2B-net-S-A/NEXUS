"""Odczyty rejestru sprzętu: lista egzemplarzy, szczegół, historia wydań, podsumowanie.

„Wolny” znaczy: stan ``na_stanie`` i brak aktywnego wydania (indeks częściowy
w bazie pilnuje, że wydanie jest najwyżej jedno). Nazwę posiadacza składa
jedno wyrażenie SQL (``_holder_name_expr``) dla listy, szczegółu i historii.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.academy import AcademyApplication
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract
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
from app.services.equipment.errors import EquipmentNotFound
from app.services.equipment.holders import (
    DELETED_PERSON,
    AcademyCandidate,
    HolderKind,
    holder_columns,
    holder_of,
)
from app.services.equipment.pricing import model_payload


def _holder_name_expr():
    """Nazwa posiadacza wydania (konto, konsultant, osoba spoza, uczestnik Akademii).

    Kontrakt bez kandydata (usunięty na żądanie) i zwrócone wydanie bez
    posiadacza (usunięte zgłoszenie Akademii) to „Osoba usunięta”, nie „—”.
    """
    gone = or_(
        and_(Contract.id.is_not(None), Candidate.id.is_(None)),
        and_(
            EquipmentAssignment.id.is_not(None),
            func.num_nonnulls(
                EquipmentAssignment.user_id,
                EquipmentAssignment.contract_id,
                EquipmentAssignment.external_person_id,
                EquipmentAssignment.academy_application_id,
            )
            == 0,
        ),
    )
    return func.coalesce(
        User.name,
        func.nullif(func.concat_ws(" ", Candidate.name, Candidate.lastname), ""),
        EquipmentExternalPerson.full_name,
        func.nullif(
            func.concat_ws(" ", AcademyCandidate.name, AcademyCandidate.lastname), ""
        ),
        case((gone, DELETED_PERSON)),
    )


def join_academy_holder(query, academy_application_id):
    """Dołącz kandydata zgłoszenia Akademii (alias ``AcademyCandidate``)."""
    return query.outerjoin(
        AcademyApplication, AcademyApplication.id == academy_application_id
    ).outerjoin(
        AcademyCandidate, AcademyCandidate.id == AcademyApplication.candidate_id
    )


def _active_join(query):
    active = EquipmentAssignment
    return join_academy_holder(
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
        ),
        active.academy_application_id,
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
    elif holder in ("user", "contract", "external", "academy"):
        column = {
            "user": EquipmentAssignment.user_id,
            "contract": EquipmentAssignment.contract_id,
            "external": EquipmentAssignment.external_person_id,
            "academy": EquipmentAssignment.academy_application_id,
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
    query = join_academy_holder(
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
        ),
        EquipmentAssignment.academy_application_id,
    )
    rows = (
        await db.execute(
            query.outerjoin(issue, issue.c.id == EquipmentAssignment.issue_protocol_id)
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
    """Sprzęt osoby, kontraktu albo uczestnika Akademii: aktywne wydania i historia."""
    column = holder_columns(kind, holder_id)
    where = {
        "user": EquipmentAssignment.user_id == holder_id,
        "contract": EquipmentAssignment.contract_id == holder_id,
        "external": EquipmentAssignment.external_person_id == holder_id,
        "academy": EquipmentAssignment.academy_application_id == holder_id,
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
