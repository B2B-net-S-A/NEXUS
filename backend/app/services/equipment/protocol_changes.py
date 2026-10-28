"""Poprawka i anulowanie protokołu sprzętu (decyzja Artura 28.10.2026).

* **Poprawka** — tylko protokół ``oczekuje`` (przed podpisem). Zmienia datę,
  imię i nazwisko w protokole (nie nazwę konta), a per pozycja wartość
  (wydanie, bez SIM i karty dostępu — D6), dodatki w nazwie (wydanie) oraz
  stan i uwagi (zwrot). Pozycji się nie dodaje ani nie usuwa. Numer zostaje,
  aktywne linki do podpisu przestają działać (osoba podpisałaby starą treść),
  różnice idą do audytu.
* **Anulowanie** — protokół ``oczekuje`` albo ``podpisany``; potwierdzony
  zostaje (pomyłkę po potwierdzeniu prostuje zwrot i nowe wydanie). Anulowane
  wydanie zwraca egzemplarze na stan i zdejmuje pozycje z zakładki „Sprzęt”
  kontraktu, anulowany zwrot przywraca wydania. Wszystko w jednej transakcji
  z ``FOR UPDATE`` — jak wydanie i zwrot.

Treść protokołu poza tymi polami zostaje zamrożona jak przy wydaniu.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional, Sequence

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contract_equipment import ContractEquipment, EquipmentReturnStatus
from app.models.equipment import (
    EquipmentAssignment,
    EquipmentItem,
    EquipmentModel,
    EquipmentProtocol,
    EquipmentProtocolLine,
    EquipmentProtocolLink,
    EquipmentTask,
)
from app.models.user import User
from app.services import equipment_schema as schema
from app.services.equipment import (
    issuing,
    protocol_document,
    protocols,
    registry,
    tasks,
)
from app.services.equipment.errors import (
    EquipmentConflict,
    EquipmentError,
)
from app.services.hr import audit

SIGNED_REFUSAL = (
    "Protokół jest już podpisany — poprawka niemożliwa, zrób zwrot i nowe wydanie."
)
#: Pola pozycji, które przyjmuje poprawka (reszta migawki zostaje).
LINE_FIELDS = ("unit_value", "accessories", "condition", "notes")


async def _locked_protocol(db: AsyncSession, protocol_id: int) -> EquipmentProtocol:
    protocol = await protocols.get_protocol(db, protocol_id)
    await protocols.lock(db, protocol)
    return protocol


async def _items_of(
    db: AsyncSession, item_ids: Sequence[int], *, lock: bool = False
) -> dict[int, tuple[EquipmentItem, EquipmentModel]]:
    if not item_ids:
        return {}
    query = (
        select(EquipmentItem, EquipmentModel)
        .join(EquipmentModel, EquipmentModel.id == EquipmentItem.model_id)
        .where(EquipmentItem.id.in_(item_ids))
        .order_by(EquipmentItem.id)
    )
    if lock:
        query = query.with_for_update(of=EquipmentItem)
    return {item.id: (item, model) for item, model in (await db.execute(query)).all()}


def split_name(
    line: EquipmentProtocolLine, item: EquipmentItem, model: EquipmentModel
) -> Optional[tuple[str, str]]:
    """Nazwa pozycji wydania = podstawa z rejestru + dodatki recepcji.

    ``None``, gdy podstawa nie pasuje do migawki (model zmienił nazwę po
    wydaniu) — wtedy dodatków nie da się poprawić bez ruszania reszty nazwy.
    """
    base = issuing.line_name(item, model, None)
    if line.name == base:
        return base, ""
    if line.name.startswith(base + " "):
        return base, line.name[len(base) + 1 :]
    return None


async def editable_lines(
    db: AsyncSession,
    protocol: EquipmentProtocol,
    lines: Sequence[EquipmentProtocolLine],
) -> dict[int, dict[str, Any]]:
    """Per pozycja: podstawa nazwy i dodatki do okna „Popraw protokół”."""
    if protocol.kind != "wydanie":
        return {}
    items = await _items_of(db, [line.item_id for line in lines if line.item_id])
    out: dict[int, dict[str, Any]] = {}
    for line in lines:
        pair = items.get(line.item_id or 0)
        split = split_name(line, *pair) if pair else None
        out[line.position] = {
            "base_name": split[0] if split else None,
            "accessories": split[1] if split else None,
        }
    return out


async def _revoke_links(db: AsyncSession, protocol_id: int, now: datetime) -> int:
    result = await db.execute(
        update(EquipmentProtocolLink)
        .where(
            EquipmentProtocolLink.protocol_id == protocol_id,
            EquipmentProtocolLink.used_at.is_(None),
            EquipmentProtocolLink.revoked_at.is_(None),
            EquipmentProtocolLink.expires_at > now,
        )
        .values(revoked_at=now)
    )
    return int(result.rowcount or 0)


def _text(value: Any) -> Optional[str]:
    return None if value is None else str(value)


async def _busy_items(db: AsyncSession, item_ids: Sequence[int]) -> set[int]:
    return set(
        (
            await db.scalars(
                select(EquipmentAssignment.item_id).where(
                    EquipmentAssignment.item_id.in_(item_ids),
                    EquipmentAssignment.returned_at.is_(None),
                )
            )
        ).all()
    )


async def correct(
    db: AsyncSession,
    protocol_id: int,
    *,
    fields: dict[str, Any],
    lines: Sequence[dict[str, Any]],
    actor: User,
) -> tuple[EquipmentProtocol, bool]:
    """Poprawka protokołu przed podpisem. Zwraca (protokół, czy unieważniono link).

    ``fields`` i każdy słownik ``lines`` niosą tylko pola przysłane przez
    recepcję (``position`` wskazuje pozycję); brak pola = bez zmiany.
    """
    protocol = await _locked_protocol(db, protocol_id)
    if protocol.status != "oczekuje":
        if protocol.status == "anulowany":
            raise EquipmentConflict("Protokół jest anulowany — poprawka niemożliwa.")
        raise EquipmentConflict(SIGNED_REFUSAL)
    changes: dict[str, Any] = {}

    new_date: Optional[date] = fields.get("protocol_date")
    if new_date is not None and new_date != protocol.protocol_date:
        if new_date.year != protocol.year:
            raise EquipmentError(
                f"Data musi zostać w roku {protocol.year} — numer protokołu "
                "jest z tego roku."
            )
        changes["protocol_date"] = [
            protocol.protocol_date.isoformat(),
            new_date.isoformat(),
        ]
        protocol.protocol_date = new_date

    if "holder_name" in fields:
        name = " ".join((fields["holder_name"] or "").split())
        if len(name) < 3:
            raise EquipmentError("Wpisz imię i nazwisko w protokole.")
        name = name[:200]
        if name != protocol.holder_name:
            changes["holder_name"] = [protocol.holder_name, name]
            protocol.holder_name = name

    current = {
        line.position: line for line in await protocols.protocol_lines(db, protocol.id)
    }
    positions = [fix["position"] for fix in lines]
    if len(set(positions)) != len(positions):
        raise EquipmentError("Ta sama pozycja jest na liście dwa razy.")
    if any(position not in current for position in positions):
        raise EquipmentError(
            "Pozycji nie dodaje się ani nie usuwa — popraw tylko te z protokołu."
        )
    item_ids = [current[p].item_id for p in positions if current[p].item_id]
    items = await _items_of(db, item_ids, lock=True)
    busy = await _busy_items(db, item_ids) if protocol.kind == "zwrot" else set()
    assignment_ids = [
        current[p].assignment_id for p in positions if current[p].assignment_id
    ]
    assignments = (
        {
            a.id: a
            for a in (
                await db.scalars(
                    select(EquipmentAssignment)
                    .where(EquipmentAssignment.id.in_(assignment_ids))
                    .with_for_update()
                )
            ).all()
        }
        if assignment_ids
        else {}
    )
    line_changes: dict[str, dict[str, list[Optional[str]]]] = {}
    changed_conditions: dict[int, str] = {}

    for fix in lines:
        line = current[fix["position"]]
        diff: dict[str, list[Optional[str]]] = {}
        pair = items.get(line.item_id or 0)
        if protocol.kind == "wydanie":
            if "condition" in fix or "notes" in fix:
                raise EquipmentError("Stan i uwagi poprawia się w protokole zwrotu.")
            if "unit_value" in fix:
                value: Optional[Decimal] = fix["unit_value"]
                if line.category in schema.NO_VALUE_CATEGORIES:
                    if value is not None:
                        raise EquipmentError(
                            "Karta SIM i karta dostępu są w protokole bez wartości."
                        )
                elif value is not None and value < 0:
                    raise EquipmentError("Wartość pozycji nie może być ujemna.")
                if value != line.unit_value:
                    diff["unit_value"] = [_text(line.unit_value), _text(value)]
                    line.unit_value = value
            if "accessories" in fix:
                extra = " ".join(
                    (
                        registry.clean_notes(fix["accessories"], label="Dodatki") or ""
                    ).split()
                )
                split = split_name(line, *pair) if pair else None
                if split is None:
                    raise EquipmentError(
                        f"Dodatków pozycji {line.position} nie da się poprawić — "
                        "nazwa w rejestrze zmieniła się po wydaniu."
                    )
                base, old_extra = split
                if extra != old_extra:
                    name = f"{base} {extra}".strip()[:300]
                    diff["name"] = [line.name, name]
                    line.name = name
        else:
            if "unit_value" in fix or "accessories" in fix:
                raise EquipmentError(
                    "W protokole zwrotu poprawia się tylko stan i uwagi."
                )
            if "condition" in fix:
                condition = fix["condition"]
                if condition not in schema.RETURN_CONDITIONS:
                    raise EquipmentError("Wybierz stan przy zwrocie.")
                if condition != line.condition:
                    label = issuing.item_label(*pair) if pair else f"#{line.item_id}"
                    if line.item_id in busy:
                        raise EquipmentConflict(
                            f"Pozycja {label} jest już wydana ponownie — stanu "
                            "przy zwrocie nie da się poprawić."
                        )
                    after_return = issuing._STATUS_AFTER_RETURN.get(  # noqa: SLF001
                        line.condition or ""
                    )
                    if pair and pair[0].status != after_return:
                        # Egzemplarz zmieniono w rejestrze po zwrocie (serwis →
                        # na stanie, wycofanie) — poprawka zwrotu by to nadpisała.
                        raise EquipmentConflict(
                            f"Pozycja {label} zmieniła stan w rejestrze po zwrocie — "
                            "stanu przy zwrocie nie da się poprawić."
                        )
                    diff["condition"] = [line.condition, condition]
                    line.condition = condition
                    changed_conditions[line.position] = condition
            if "notes" in fix:
                notes = (
                    " ".join(
                        (
                            registry.clean_notes(fix["notes"], label="Uwagi") or ""
                        ).split()
                    )
                    or None
                )
                if notes != line.notes:
                    diff["notes"] = [line.notes, notes]
                    line.notes = notes
            assignment = assignments.get(line.assignment_id or 0)
            if assignment is not None and assignment.return_protocol_id == protocol.id:
                assignment.return_condition = line.condition
                assignment.return_notes = line.notes
                if line.position in changed_conditions and pair:
                    item = pair[0]
                    item.status = issuing._STATUS_AFTER_RETURN[line.condition]  # noqa: SLF001
                    item.updated_by = actor.id
        if diff:
            line_changes[str(line.position)] = diff
    if line_changes:
        changes["lines"] = line_changes

    if not changes:
        return protocol, False

    all_lines = list(current.values())
    if protocol.kind == "wydanie":
        protocol.total_value = protocol_document.protocol_total(
            [
                protocol_document.LineView(
                    position=line.position,
                    name=line.name,
                    identifier=line.identifier,
                    quantity=line.quantity,
                    unit_value=line.unit_value,
                )
                for line in all_lines
            ]
        )
    await _sync_contract_rows(db, protocol, all_lines, changed_conditions)
    now = datetime.now(timezone.utc)
    revoked = await _revoke_links(db, protocol.id, now)
    await db.flush()
    # Termin i tytuł zadania podpisu idą za datą i nazwiskiem.
    await tasks.ensure_signature_task(db, protocol)
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=protocol.user_id,
        entity_type="equipment_protocol",
        entity_id=protocol.id,
        action="protocol_corrected",
        details={"changes": changes, "links_revoked": revoked},
    )
    return protocol, revoked > 0


async def _sync_contract_rows(
    db: AsyncSession,
    protocol: EquipmentProtocol,
    lines: Sequence[EquipmentProtocolLine],
    changed_conditions: dict[int, str],
) -> None:
    """Zakładka „Sprzęt” kontraktu idzie za datą i stanem z protokołu."""
    if protocol.contract_id is None:
        return
    by_assignment = {line.assignment_id: line for line in lines if line.assignment_id}
    if not by_assignment:
        return
    rows = (
        await db.scalars(
            select(ContractEquipment).where(
                ContractEquipment.assignment_id.in_(list(by_assignment))
            )
        )
    ).all()
    for row in rows:
        if protocol.kind == "wydanie":
            row.handed_over_date = protocol.protocol_date
            continue
        row.returned_date = protocol.protocol_date
        line = by_assignment[row.assignment_id]
        if line.position in changed_conditions:
            row.return_status = (
                EquipmentReturnStatus.lost
                if line.condition == "zgubiony"
                else EquipmentReturnStatus.returned
            )


async def cancel(
    db: AsyncSession, protocol_id: int, *, reason: str, actor: User
) -> EquipmentProtocol:
    """Anulowanie niepotwierdzonego protokołu z powodem (audyt i kolumny 0609)."""
    cleaned = " ".join((registry.clean_notes(reason, label="Powód") or "").split())
    if len(cleaned) < 3:
        raise EquipmentError("Wpisz powód anulowania.")
    protocol = await _locked_protocol(db, protocol_id)
    if protocol.status == "potwierdzony":
        raise EquipmentConflict(
            "Protokół jest już potwierdzony — anulowanie niemożliwe, zrób zwrot "
            "i nowe wydanie."
        )
    if protocol.status == "anulowany":
        raise EquipmentConflict("Protokół jest już anulowany.")
    now = datetime.now(timezone.utc)
    if protocol.kind == "wydanie":
        moved = await _cancel_issue(db, protocol, actor=actor, now=now)
    else:
        moved = await _cancel_return(db, protocol, actor=actor)
    revoked = await _revoke_links(db, protocol.id, now)
    await db.execute(
        update(EquipmentTask)
        .where(
            EquipmentTask.protocol_id == protocol.id,
            EquipmentTask.kind == "podpis",
            EquipmentTask.status == "otwarte",
        )
        .values(status="anulowane", done_at=now, done_by=actor.id)
    )
    protocol.status = "anulowany"
    protocol.cancelled_at = now
    protocol.cancelled_by = actor.id
    protocol.cancel_reason = cleaned[:500]
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=protocol.user_id,
        entity_type="equipment_protocol",
        entity_id=protocol.id,
        action="protocol_cancelled",
        details={
            "reason": protocol.cancel_reason,
            "kind": protocol.kind,
            "items": moved,
            "links_revoked": revoked,
        },
    )
    return protocol


async def _cancel_issue(
    db: AsyncSession, protocol: EquipmentProtocol, *, actor: User, now: datetime
) -> int:
    """Wydanie się nie odbyło: egzemplarze na stan, pozycje kontraktu znikają."""
    assignments = (
        await db.scalars(
            select(EquipmentAssignment)
            .where(EquipmentAssignment.issue_protocol_id == protocol.id)
            .order_by(EquipmentAssignment.id)
            .with_for_update()
        )
    ).all()
    returned = [a for a in assignments if a.returned_at is not None]
    if returned:
        numbers = sorted(
            {
                number
                for number in (
                    await db.scalars(
                        select(EquipmentProtocol.number).where(
                            EquipmentProtocol.id.in_(
                                [
                                    a.return_protocol_id
                                    for a in returned
                                    if a.return_protocol_id
                                ]
                            )
                        )
                    )
                ).all()
            }
        )
        where = f" ({', '.join(numbers)})" if numbers else ""
        raise EquipmentConflict(
            f"Część sprzętu z tego protokołu już wróciła{where} — najpierw anuluj zwrot."
        )
    items = await _items_of(db, [a.item_id for a in assignments], lock=True)
    note = f"Anulowany protokół {protocol.number}"
    for assignment in assignments:
        assignment.returned_at = max(now, assignment.issued_at)
        assignment.return_condition = "sprawny"
        assignment.return_notes = note
        assignment.returned_by = actor.id
        pair = items.get(assignment.item_id)
        if pair:
            pair[0].status = "na_stanie"
            pair[0].updated_by = actor.id
    if assignments:
        await db.execute(
            delete(ContractEquipment).where(
                ContractEquipment.assignment_id.in_([a.id for a in assignments])
            )
        )
    return len(assignments)


async def _cancel_return(
    db: AsyncSession, protocol: EquipmentProtocol, *, actor: User
) -> int:
    """Zwrotu nie było: wydania znów aktywne, egzemplarze „wydane”."""
    assignments = (
        await db.scalars(
            select(EquipmentAssignment)
            .where(EquipmentAssignment.return_protocol_id == protocol.id)
            .order_by(EquipmentAssignment.id)
            .with_for_update()
        )
    ).all()
    items = await _items_of(db, [a.item_id for a in assignments], lock=True)
    busy = await _busy_items(db, [a.item_id for a in assignments])
    for assignment in assignments:
        pair = items.get(assignment.item_id)
        if assignment.item_id in busy or (pair and pair[0].status == "wycofany"):
            label = issuing.item_label(*pair) if pair else f"#{assignment.item_id}"
            raise EquipmentConflict(
                f"Pozycja {label} ma już inny los (wydana ponownie albo wycofana) "
                "— zwrotu nie da się anulować."
            )
    for assignment in assignments:
        assignment.returned_at = None
        assignment.return_condition = None
        assignment.return_notes = None
        assignment.return_protocol_id = None
        assignment.returned_by = None
        pair = items.get(assignment.item_id)
        if pair:
            pair[0].status = "wydany"
            pair[0].updated_by = actor.id
    if assignments:
        await db.execute(
            update(ContractEquipment)
            .where(ContractEquipment.assignment_id.in_([a.id for a in assignments]))
            .values(return_status=EquipmentReturnStatus.pending, returned_date=None)
        )
    return len(assignments)
