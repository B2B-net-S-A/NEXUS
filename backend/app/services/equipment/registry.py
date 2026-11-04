"""Rejestr sprzętu: egzemplarze (zapis) i flaga klienta „sprzęt od nas” (kroki S1–S2).

Jedna pozycja to jeden egzemplarz. Reszta rejestru leży obok:

* ``errors`` — odmowy (``EquipmentError`` i pochodne),
* ``holders`` — posiadacze (konto, kontrakt, osoba spoza, uczestnik Akademii),
* ``pricing`` — cennik modeli,
* ``queries`` — lista, szczegół, historia wydań, podsumowanie.

Ten moduł re-eksportuje ich nazwy, więc ``registry.X`` i importy z innych
modułów (np. ``api/candidates.py``, ``candidate_merge.py``) działają jak dotąd.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.equipment import EquipmentAssignment, EquipmentItem, EquipmentModel
from app.models.user import User
from app.services import equipment_schema as schema
from app.services.equipment import identifiers, sanitize
from app.services.equipment.errors import (
    EquipmentConflict,
    EquipmentError,
    EquipmentNotFound,
)
from app.services.equipment.holders import (
    ACADEMY_EQUIPMENT_HELD,
    DELETED_PERSON,
    ISSUABLE_ACADEMY_STATUSES,
    ISSUABLE_CONTRACT_STATUSES,
    AcademyCandidate,
    Holder,
    HolderKind,
    academy_detail,
    academy_participant_name,
    active_academy_assignments,
    candidate_name,
    create_external_person,
    external_payload,
    holder_columns,
    holder_of,
    list_external_people,
    move_external_to_user,
    resolve_holder,
    search_academy_holders,
    search_holders,
)
from app.services.equipment.pricing import (
    create_model,
    get_or_create_model,
    list_models,
    model_payload,
    update_model,
)
from app.services.equipment.queries import (
    assignment_history,
    holder_equipment,
    item_detail,
    item_payload,
    join_academy_holder,
    list_items,
    summary,
)
from app.services.hr import audit

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


def clean_notes(value: Optional[str], *, label: str = "Notatka") -> Optional[str]:
    """Wolny tekst bez kluczy BitLocker, PUK, PIN, PESEL i prywatnych e-maili (D10) — inaczej błąd."""
    if value is None:
        return None
    cleaned = sanitize.clean_text(value)
    if cleaned.reasons:
        raise EquipmentError(
            f"{label} zawiera dane, których NEXUS nie przechowuje ("
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
        out["notes"] = clean_notes(out["notes"])
    if "location" in out and out["location"] is not None:
        # D10: lokalizacja to też wolny tekst (widać ją w rejestrze i eksporcie).
        out["location"] = clean_notes(str(out["location"]), label="Lokalizacja")
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


__all__ = [
    "ACADEMY_EQUIPMENT_HELD",
    "DELETED_PERSON",
    "ISSUABLE_ACADEMY_STATUSES",
    "ISSUABLE_CONTRACT_STATUSES",
    "ITEM_FIELDS",
    "AcademyCandidate",
    "EquipmentConflict",
    "EquipmentError",
    "EquipmentNotFound",
    "Holder",
    "HolderKind",
    "academy_detail",
    "academy_participant_name",
    "active_academy_assignments",
    "active_assignment",
    "assignment_history",
    "candidate_name",
    "clean_notes",
    "client_provider",
    "create_external_person",
    "create_item",
    "create_model",
    "delete_item",
    "external_payload",
    "get_or_create_model",
    "holder_columns",
    "holder_equipment",
    "holder_of",
    "identifier_conflicts",
    "item_detail",
    "item_payload",
    "join_academy_holder",
    "link_contract_equipment",
    "list_external_people",
    "move_external_to_user",
    "list_items",
    "list_models",
    "model_payload",
    "resolve_holder",
    "search_academy_holders",
    "search_holders",
    "set_client_provider",
    "summary",
    "update_item",
    "update_model",
]
