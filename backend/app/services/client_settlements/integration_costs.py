"""Koszty integracji konsultanta ze zgodą DL-a (roadmapa E5.1, reguła ``cl.integration_costs``).

Odpowiedź rozliczeń z 10.11.2026: koszty integracji konsultanta (np. wyjście
zespołu u klienta) idą na koszt B2B i klient ich nie zwraca. Zgodę daje
Delivery Lead klienta, limit to kwota na konsultanta na rok kalendarzowy
(BNP: 2 000 zł). Dotąd Finanse prowadziły to ręcznie w zestawieniu dla DL-a.

* Finanse wpisują koszt przy osobie i miesiącu → ``pending``; DL klienta go
  przyjmuje albo odrzuca (Finanse ani admin nie zastępują jego zgody).
* Limit liczymy na konsultanta (kandydat z kontraktu, bez niego kontrakt)
  u tego klienta w roku miesiąca kosztu. Wpis odmawia, gdy przyjęte
  i czekające razem z nowym przekroczą limit; zgoda odmawia, gdy przyjęte
  razem z tym przekroczą limit. Pusty limit w regule = bez limitu.
* Marżę miesiąca obniża tylko koszt przyjęty (``service.integration_by_contract``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.client_settlement import ClientSettlementExtra
from app.models.contract import Contract
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.services.client_settlements import service
from app.services.client_settlements.service import SettlementError
from app.services.client_settlements_schema import EXTRA_DESCRIPTION_MAX

RULE = "cl.integration_costs"
KIND = "integration"  # rodzaj dodatku w ``client_settlement_extras``
PENDING, APPROVED, REJECTED = "pending", "approved", "rejected"
AMOUNT_MAX = Decimal("100000")
MONEY = Decimal("0.01")
DL_ONLY_DETAIL = "Koszt integracji zatwierdza Delivery Lead tego klienta."


@dataclass(frozen=True)
class Usage:
    year: int
    limit: Optional[Decimal]
    approved: Decimal
    pending: Decimal

    @property
    def remaining(self) -> Optional[Decimal]:
        if self.limit is None:
            return None
        return max(self.limit - self.approved, Decimal("0"))

    def as_dict(self) -> dict[str, Any]:
        return {
            "year": self.year,
            "limit": None if self.limit is None else f"{self.limit:.2f}",
            "approved": f"{self.approved:.2f}",
            "pending": f"{self.pending:.2f}",
            "remaining": None if self.remaining is None else f"{self.remaining:.2f}",
        }


def _pln(value: Decimal) -> str:
    text = f"{value:,.2f}".replace(",", " ").replace(".", ",")
    return text[:-3] if text.endswith(",00") else text


def parse_limit(raw: Any) -> Optional[Decimal]:
    """Parametr ``limit`` reguły: „2000”, „2 000”, „2000,00”. Pusty = bez limitu."""

    text = str(raw or "").replace("\xa0", "").replace(" ", "").replace(",", ".")
    if not text:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return value if value > 0 else None


async def rule_state(
    db: AsyncSession, client_id: int, month: str
) -> tuple[bool, Optional[Decimal]]:
    rules = await service.rules_for(db, client_id, month)
    rule = rules[RULE]
    return rule["level"] != "off", parse_limit(rule["params"].get("limit"))


async def is_client_delivery_lead(db: AsyncSession, user: User, client_id: int) -> bool:
    """Czy konto jest Delivery Leadem tego klienta (przypisanie, także przez scalenie).

    Admin i Finanse nie zastępują zgody DL-a — tak ustaliły rozliczenia (10.11)."""

    if user is None or not user.has_role(UserRole.delivery_lead):
        return False
    client = await db.get(Client, client_id)
    ids = {client_id}
    if client is not None and client.merged_into_client_id is not None:
        ids.add(int(client.merged_into_client_id))
    merged = select(Client.id).where(Client.merged_into_client_id == client_id)
    found = await db.scalar(
        select(func.count())
        .select_from(DeliveryLeadClientAssignment)
        .where(
            DeliveryLeadClientAssignment.delivery_lead_user_id == user.id,
            or_(
                DeliveryLeadClientAssignment.client_id.in_(sorted(ids)),
                DeliveryLeadClientAssignment.client_id.in_(merged),
            ),
        )
    )
    return bool(found)


def _same_person(contract: Contract):
    if contract.candidate_id is not None:
        return Contract.candidate_id == contract.candidate_id
    return ClientSettlementExtra.contract_id == contract.id


async def usage(
    db: AsyncSession, contract: Contract, client_id: int, month: str
) -> Usage:
    """Przyjęte i czekające koszty konsultanta u klienta w roku kalendarzowym
    miesiąca; limit z reguł tego miesiąca."""

    year = int(month[:4])
    rows = await db.execute(
        select(
            ClientSettlementExtra.status,
            func.sum(ClientSettlementExtra.amount),
        )
        .join(Contract, Contract.id == ClientSettlementExtra.contract_id)
        .where(
            ClientSettlementExtra.client_id == client_id,
            ClientSettlementExtra.kind == KIND,
            _same_person(contract),
            ClientSettlementExtra.period_month.like(f"{year:04d}-%"),
            ClientSettlementExtra.status.in_((PENDING, APPROVED)),
        )
        .group_by(ClientSettlementExtra.status)
    )
    sums = {status: Decimal(total or 0) for status, total in rows.all()}
    _, limit = await rule_state(db, client_id, month)
    return Usage(
        year, limit, sums.get(APPROVED, Decimal("0")), sums.get(PENDING, Decimal("0"))
    )


def _clean_amount(amount: Decimal) -> Decimal:
    value = Decimal(amount).quantize(MONEY)
    if value <= 0 or value > AMOUNT_MAX:
        raise SettlementError("Kwota kosztu musi być większa od zera.", status=422)
    return value


def _clean_description(text: str) -> str:
    value = " ".join((text or "").replace("\x00", "").split())
    if len(value) < 3:
        raise SettlementError("Opisz koszt (np. czego dotyczy faktura).", status=422)
    return value[:EXTRA_DESCRIPTION_MAX]


def _over_limit(limit: Decimal, used: Decimal, year: int) -> SettlementError:
    left = max(limit - used, Decimal("0"))
    return SettlementError(
        f"Ponad limit kosztów integracji: w {year} zostało {_pln(left)} zł "
        f"z {_pln(limit)} zł na konsultanta."
    )


async def add(
    db: AsyncSession,
    contract_id: int,
    month: str,
    *,
    amount: Decimal,
    description: str,
    actor: User,
) -> ClientSettlementExtra:
    """Wpis kosztu przy osobie i miesiącu; czeka na zgodę DL-a klienta."""

    contract = await db.get(Contract, contract_id, with_for_update=True)
    if contract is None:
        raise SettlementError("Nie ma takiego kontraktu.", status=404)
    client_id = int(contract.client_id)
    enabled, limit = await rule_state(db, client_id, month)
    if not enabled:
        raise SettlementError(
            "Koszty integracji są wyłączone w regułach tego klienta.", status=422
        )
    value = _clean_amount(amount)
    year = int(month[:4])
    used = await usage(db, contract, client_id, month)
    if limit is not None and used.approved + used.pending + value > limit:
        raise _over_limit(limit, used.approved + used.pending, year)
    cost = ClientSettlementExtra(
        client_id=client_id,
        contract_id=contract_id,
        period_month=month,
        kind=KIND,
        amount=value,
        description=_clean_description(description),
        status=PENDING,
        created_by=actor.id,
    )
    db.add(cost)
    await db.flush()
    return cost


async def _cost(
    db: AsyncSession, cost_id: int, client_id: Optional[int]
) -> ClientSettlementExtra:
    cost = await db.get(ClientSettlementExtra, cost_id, with_for_update=True)
    if (
        cost is None
        or cost.kind != KIND
        or (client_id is not None and cost.client_id != client_id)
    ):
        raise SettlementError("Nie ma takiego kosztu integracji.", status=404)
    return cost


async def decide(
    db: AsyncSession,
    cost_id: int,
    *,
    approve: bool,
    actor: User,
    now: datetime,
    client_id: Optional[int] = None,
) -> ClientSettlementExtra:
    """Zgoda albo odmowa DL-a klienta. Zgoda pilnuje limitu roku."""

    cost = await _cost(db, cost_id, client_id)
    if not await is_client_delivery_lead(db, actor, cost.client_id):
        raise SettlementError(DL_ONLY_DETAIL, status=403)
    if cost.status != PENDING:
        raise SettlementError("Ten koszt jest już rozstrzygnięty.")
    if approve:
        contract = await db.get(Contract, cost.contract_id, with_for_update=True)
        used = await usage(db, contract, cost.client_id, cost.period_month)
        if used.limit is not None and used.approved + Decimal(cost.amount) > used.limit:
            raise _over_limit(used.limit, used.approved, used.year)
    cost.status = APPROVED if approve else REJECTED
    cost.decided_by = actor.id
    cost.decided_at = now
    await db.flush()
    return cost


async def withdraw(db: AsyncSession, cost_id: int, contract_id: int) -> None:
    """Finanse cofają wpis, który czeka na DL-a (pomyłka nie blokuje limitu)."""

    cost = await _cost(db, cost_id, None)
    if cost.contract_id != contract_id:
        raise SettlementError("Nie ma takiego kosztu integracji.", status=404)
    if cost.status != PENDING:
        raise SettlementError("Rozstrzygniętego kosztu nie da się cofnąć.")
    await db.delete(cost)
    await db.flush()


def _item(cost: ClientSettlementExtra, person: Optional[str] = None) -> dict[str, Any]:
    out = {
        "id": cost.id,
        "contract_id": cost.contract_id,
        "month": cost.period_month,
        "amount": f"{Decimal(cost.amount):.2f}",
        "description": cost.description,
        "status": cost.status,
        "decided_at": cost.decided_at.isoformat() if cost.decided_at else None,
    }
    if person is not None:
        out["person"] = person
    return out


async def card(db: AsyncSession, contract_id: int, month: str) -> dict[str, Any]:
    """Sekcja „Koszty integracji” na karcie osoby: rok konsultanta i licznik."""

    contract = await db.get(Contract, contract_id)
    if contract is None:
        raise SettlementError("Nie ma takiego kontraktu.", status=404)
    client_id = int(contract.client_id)
    enabled, _ = await rule_state(db, client_id, month)
    year = int(month[:4])
    items = (
        await db.scalars(
            select(ClientSettlementExtra)
            .join(Contract, Contract.id == ClientSettlementExtra.contract_id)
            .where(
                ClientSettlementExtra.client_id == client_id,
                ClientSettlementExtra.kind == KIND,
                _same_person(contract),
                ClientSettlementExtra.period_month.like(f"{year:04d}-%"),
            )
            .order_by(
                ClientSettlementExtra.period_month,
                ClientSettlementExtra.id,
            )
        )
    ).all()
    return {
        "enabled": enabled,
        "usage": (await usage(db, contract, client_id, month)).as_dict(),
        "items": [_item(c) for c in items],
    }


async def client_month(db: AsyncSession, client_id: int, month: str) -> dict[str, Any]:
    """Koszty klienta do decyzji DL-a: czekające z całego roku i rozstrzygnięte
    w miesiącu, z licznikiem roku każdej osoby."""

    enabled, limit = await rule_state(db, client_id, month)
    year = int(month[:4])
    rows = (
        await db.execute(
            select(ClientSettlementExtra, Contract)
            .join(Contract, Contract.id == ClientSettlementExtra.contract_id)
            .where(
                ClientSettlementExtra.client_id == client_id,
                ClientSettlementExtra.kind == KIND,
                or_(
                    ClientSettlementExtra.period_month == month,
                    (ClientSettlementExtra.status == PENDING)
                    & ClientSettlementExtra.period_month.like(f"{year:04d}-%"),
                ),
            )
            .order_by(
                ClientSettlementExtra.status != PENDING,
                ClientSettlementExtra.period_month,
                ClientSettlementExtra.id,
            )
        )
    ).all()
    items = []
    for cost, contract in rows:
        person = await service._contract(db, contract.id)
        used = await usage(db, contract, client_id, cost.period_month)
        items.append({**_item(cost, person.name), "usage": used.as_dict()})
    return {
        "enabled": enabled,
        "limit": None if limit is None else f"{limit:.2f}",
        "year": year,
        "items": items,
    }
