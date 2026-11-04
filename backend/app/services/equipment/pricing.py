"""Cennik sprzętu: modele z kategorią i ceną (wartość w protokołach).

Karta SIM i karta dostępu nie mają wartości (D6). Zmiana ceny nie rusza
protokołów — wartości są w nich zamrożone.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.equipment import EquipmentItem, EquipmentModel
from app.models.user import User
from app.services import equipment_schema as schema
from app.services.equipment import identifiers
from app.services.equipment.errors import (
    EquipmentConflict,
    EquipmentError,
    EquipmentNotFound,
)


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
