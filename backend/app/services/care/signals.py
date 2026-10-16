"""Sygnały sprzedażowe dla ATLASA (zastępują ``GET /api/internal/sales-signals`` Compassa).

Sygnał = sfinalizowana karta technologiczna z „klient zatrudnia”. ATLAS
pobiera pełny zbiór i uzgadnia go u siebie (karta, która przestała być
sygnałem, znika z odpowiedzi = wycofanie), a wynik obsługi (konwersja
w szansę albo archiwizacja) odsyła paczką statusów.

Mapowanie pole po polu, bez spreadu: co wychodzi, widać tutaj. Bez stawek,
bez e-maila konsultanta (Compass go oddawał); imię i nazwisko konsultanta
mieści się w zakresie ``contracts:read`` („osoba, klient, okres, status”).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract
from app.models.contract_care import ClientArea, TechCard
from app.models.skill import Skill
from app.models.user import User
from app.services.care import records
from app.services.care.skills import display_name


def _need(roles: list[str]) -> str:
    cleaned = [role for role in roles if role]
    return (
        ", ".join(cleaned) if cleaned else "Potrzeba rekrutacyjna zgłoszona w rozmowie."
    )


async def export(
    db: AsyncSession, *, since: Optional[datetime]
) -> list[dict[str, Any]]:
    query = (
        select(TechCard, Client.name, ClientArea.name, User.email, Candidate.name)
        .join(Client, Client.id == TechCard.client_id)
        .outerjoin(ClientArea, ClientArea.id == TechCard.client_area_id)
        .outerjoin(User, User.id == TechCard.author_user_id)
        .outerjoin(Contract, Contract.id == TechCard.contract_id)
        .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
        .where(TechCard.hiring.is_(True), TechCard.is_draft.is_(False))
        .order_by(TechCard.id)
    )
    if since is not None:
        query = query.where(TechCard.updated_at >= since)
    rows = (await db.execute(query)).all()
    card_skills, _vendors = await records.card_relations(
        db, [row[0].id for row in rows]
    )
    skill_ids = sorted({sid for ids in card_skills.values() for sid in ids})
    skill_names = (
        dict(
            (
                await db.execute(
                    select(Skill.id, Skill.canonical_name).where(
                        Skill.id.in_(skill_ids)
                    )
                )
            ).all()
        )
        if skill_ids
        else {}
    )
    out = []
    for card, client_name, area_name, author_email, consultant_name in rows:
        technologies = sorted(
            display_name(skill_names[sid])
            for sid in card_skills.get(card.id, [])
            if sid in skill_names
        )
        context_parts = []
        if area_name:
            context_parts.append(f"Obszar: {area_name}")
        if technologies:
            context_parts.append("Technologie: " + ", ".join(technologies))
        out.append(
            {
                "id": card.id,
                "compass_id": str(card.compass_card_id)
                if card.compass_card_id
                else None,
                "client_id": card.client_id,
                "company_name": client_name,
                "need": _need(list(card.hiring_roles or [])),
                "hiring_roles": list(card.hiring_roles or []),
                "hiring_source": card.hiring_source,
                "area": area_name,
                "technologies": technologies,
                "context": " · ".join(context_parts) or None,
                "reported_by_email": author_email,
                "consultant_name": consultant_name,
                "interview_on": card.interview_on,
                "created_at": card.finalized_at or card.created_at,
                "source_updated_at": card.updated_at,
                "sales_status": card.sales_status,
                "sales_handled_at": card.sales_handled_at,
            }
        )
    return out


@dataclass(frozen=True)
class StatusUpdate:
    signal_id: str
    status: str
    handled_at: datetime
    deal_title: Optional[str] = None
    handled_by_name: Optional[str] = None
    reason: Optional[str] = None


async def _card_for(db: AsyncSession, signal_id: str) -> Optional[TechCard]:
    raw = signal_id.strip()
    if raw.isdigit():
        return await db.get(TechCard, int(raw), with_for_update=True)
    try:
        legacy = uuid.UUID(raw)
    except ValueError:
        return None
    return await db.scalar(
        select(TechCard).where(TechCard.compass_card_id == legacy).with_for_update()
    )


async def apply_statuses(
    db: AsyncSession, updates: list[StatusUpdate]
) -> dict[str, Any]:
    """Zapis statusów (bez commita). Starszy ``handled_at`` niż zapisany nie wygrywa."""

    latest: dict[str, StatusUpdate] = {}
    for item in updates:
        key = item.signal_id.strip().lower()
        previous = latest.get(key)
        if previous is None or item.handled_at >= previous.handled_at:
            latest[key] = item
    accepted = 0
    ignored = 0
    unknown: list[str] = []
    for item in latest.values():
        card = await _card_for(db, item.signal_id)
        if card is None or card.hiring is not True:
            unknown.append(item.signal_id)
            continue
        if (
            card.sales_handled_at is not None
            and item.handled_at < card.sales_handled_at
        ):
            ignored += 1
            continue
        # ``updated_at`` zostaje: to wersja KARTY dla ATLASA, a status przyszedł
        # od niego — inaczej każdy zwrot statusu wyglądałby jak edycja karty.
        await db.execute(
            update(TechCard)
            .where(TechCard.id == card.id)
            .values(
                sales_status=item.status,
                sales_deal_title=item.deal_title,
                sales_handled_by=item.handled_by_name,
                sales_reason=item.reason,
                sales_handled_at=item.handled_at,
                updated_at=TechCard.updated_at,
            )
        )
        accepted += 1
    return {"accepted": accepted, "ignored_stale": ignored, "unknown": unknown}
