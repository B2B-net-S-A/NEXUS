"""Bramka „to już klient NEXUSA”: szansy nie zakładamy, popyt idzie do Delivery Leada.

Decyzja Artura z 22.10.2026 (leady, ``is_existing_client``), ta sama reguła
rozpoznania: nazwa, nazwa wyświetlana albo prawna i aktywne aliasy widocznych
klientów, a do tego jawne powiązanie ``sales_companies.client_id``. Handlowiec
nie ma podglądu Delivery, więc dostaje tylko nazwę klienta i osobę, do której
ma przekazać temat.

Nasza spółka też jest w ``clients`` (projekty wewnętrzne, bez Delivery Leada)
i ma kartę w Sprzedaży, ale to nie klient do przekazania: nie dostaje szansy
ani polecenia „zgłoś do Heada”.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User
from app.services.client_duplicates import ClientNameIndex, load_client_name_index

NO_LEAD_LABEL = "Klient bez Delivery Leada: zgłoś do Heada"
#: ``normalize_company_name`` naszej spółki.
OWN_COMPANY_KEY = "b2b net"
OWN_COMPANY_REFUSAL = "To nasza firma, szansy nie zakładamy."


@dataclass(frozen=True)
class ClientMatch:
    client_name: str
    delivery_lead: Optional[str]

    @property
    def refusal(self) -> str:
        if self.delivery_lead is None:
            return f"{self.client_name} to klient NEXUSA. {NO_LEAD_LABEL}."
        return (
            f"{self.client_name} to klient NEXUSA, szansy nie zakładamy. "
            f"Przekaż do: {self.delivery_lead}."
        )


@dataclass(frozen=True)
class CompanyIdentity:
    company_id: int
    client_id: Optional[int]
    normalized_name: Optional[str]


def _client_ids(index: ClientNameIndex, company: CompanyIdentity) -> list[int]:
    """Jawne powiązanie ma pierwszeństwo przed zgodnością nazwy."""

    linked = company.client_id if company.client_id in index.display_by_id else None
    named = sorted(index.ids_by_key.get(company.normalized_name or "", ()))
    return ([linked] if linked is not None else []) + [
        client_id for client_id in named if client_id != linked
    ]


async def _leads_by_client(
    db: AsyncSession, client_ids: Sequence[int]
) -> dict[int, str]:
    """Główny DL klienta, a bez niego pierwszy przypisany; tylko aktywne konta."""

    if not client_ids:
        return {}
    rows = (
        await db.execute(
            select(DeliveryLeadClientAssignment.client_id, User.name)
            .join(User, User.id == DeliveryLeadClientAssignment.delivery_lead_user_id)
            .where(
                DeliveryLeadClientAssignment.client_id.in_(sorted(set(client_ids))),
                User.is_active.is_(True),
            )
            .order_by(
                DeliveryLeadClientAssignment.is_head.desc(),
                User.name,
            )
        )
    ).all()
    leads: dict[int, str] = {}
    for client_id, name in rows:
        leads.setdefault(client_id, name)
    return leads


async def match_companies(
    db: AsyncSession, companies: Sequence[CompanyIdentity]
) -> dict[int, ClientMatch]:
    """Firmy, które są klientem NEXUSA: id firmy → klient i jego Delivery Lead."""

    index = await load_client_name_index(db)
    candidates = {
        company.company_id: ids
        for company in companies
        if (ids := _client_ids(index, company))
    }
    leads = await _leads_by_client(
        db, [client_id for ids in candidates.values() for client_id in ids]
    )
    matches: dict[int, ClientMatch] = {}
    for company_id, ids in candidates.items():
        chosen = next((client_id for client_id in ids if client_id in leads), ids[0])
        matches[company_id] = ClientMatch(
            client_name=index.display_by_id[chosen],
            delivery_lead=leads.get(chosen),
        )
    return matches
