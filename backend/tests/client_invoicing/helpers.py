"""Pomocnicze dla testów faktur do klientów (E8): klient, zamówienia, osoby, konta.

Dane wyłącznie fikcyjne: NIP-y z poprawną sumą kontrolną, ale zmyślone
(1111111111 — „Bank Testowy S.A.”, 3333333333 — nabywca spoza NEXUSA),
numery KSeF i kwoty zmyślone. Faktury FA(3) w ``tests/data/ksef/sales``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup
from app.models.client_sales_invoice import (
    ClientSalesInvoice,
    ClientSalesInvoicePayment,
)
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.hr_ops import HrJobRun
from app.models.md_consumption import ClientOrderMdConsumption
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.services.client_invoicing import settings as module_settings
from app.services.client_invoicing import sync

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "ksef" / "sales"
COMPANY_NIP = "9876543210"
CLIENT_NIP = "1111111111"
OTHER_CLIENT_NIP = "2222222222"
UNKNOWN_NIP = "3333333333"
FIXTURE_NIPS = (CLIENT_NIP, OTHER_CLIENT_NIP, UNKNOWN_NIP)

KSEF_118 = "9876543210-20261103-A1180C0FFEE1-5C"
KSEF_121 = "9876543210-20261103-A1210C0FFEE2-55"
KSEF_124 = "9876543210-20261104-A1240C0FFEE3-7D"
KSEF_UNKNOWN = "9876543210-20261105-B0070C0FFEE4-2E"
KSEF_CORRECTION = "9876543210-20261109-C0010C0FFEE5-C5"


def headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def make_user(db: AsyncSession, role: str, *, name: Optional[str] = None) -> User:
    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"invoicing-{marker}@example.com",
        name=name or f"Osoba Przykładowa {marker}",
        role=UserRole(role),
        roles=[role],
        is_active=True,
        profile_completed=True,
    )
    db.add(user)
    await db.flush()
    return user


async def set_module(enabled: Optional[bool]) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, module_settings.SETTING_KEY)
        if enabled is None:
            if row is not None:
                await db.delete(row)
        elif row is None:
            db.add(
                AppSetting(key=module_settings.SETTING_KEY, value={"enabled": enabled})
            )
        else:
            row.value = {"enabled": enabled}
        await db.commit()


@dataclass
class Seed:
    client_id: int
    other_client_id: int
    groups: dict[str, int] = field(default_factory=dict)
    orders: dict[str, int] = field(default_factory=dict)
    lines: dict[str, int] = field(default_factory=dict)
    users: dict[str, User] = field(default_factory=dict)


async def _person(db: AsyncSession, client_id: int, first: str, last: str) -> Contract:
    marker = uuid.uuid4().hex[:8]
    candidate = Candidate(
        name=first, lastname=last, email=f"konsultant-{marker}@example.com"
    )
    db.add(candidate)
    await db.flush()
    contract = Contract(
        candidate_id=candidate.id,
        client_id=client_id,
        status=ContractStatus.active,
        start_date=date(2026, 1, 1),
        rate_candidate=Decimal("100.000"),
        rate_client=Decimal("150.000"),
    )
    db.add(contract)
    await db.flush()
    return contract


async def md_group(
    db: AsyncSession,
    client_id: int,
    number: str,
    *,
    people: list[tuple[str, str, str, Optional[str]]],
    cost: bool = False,
) -> tuple[int, list[int]]:
    """Zamówienie MD z osobami: (imię, nazwisko, stawka MD, zużycie MD w październiku)."""

    group = ClientOrderGroup(
        client_id=client_id,
        order_number=number,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        status="active",
        order_type="cost" if cost else "md",
        is_cost_based=cost,
        is_md_budget_based=False,
        budget_amount=Decimal("500000") if cost else None,
        budget_remaining=Decimal("500000") if cost else None,
    )
    db.add(group)
    await db.flush()
    line_ids = []
    for first, last, rate, md in people:
        contract = await _person(db, client_id, first, last)
        line = ClientOrder(
            client_id=client_id,
            contract_id=contract.id,
            order_group_id=group.id,
            title=f"Zamówienie {number} — {first} {last}",
            status=ClientOrderStatus.active,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            md_rate_revenue=Decimal(rate),
            md_rate_cost=Decimal("800"),
            md_total=None if cost else Decimal("100"),
            md_remaining=None if cost else Decimal("100"),
            md_input_mode=None if cost else "md",
            md_input_value=None if cost else Decimal("100"),
        )
        db.add(line)
        await db.flush()
        if md is not None:
            db.add(
                ClientOrderMdConsumption(
                    order_id=line.id,
                    period_month="2026-10",
                    md_reported=Decimal(md),
                    source="import",
                )
            )
        line_ids.append(line.id)
    await db.flush()
    return group.id, line_ids


async def periodic_order(
    db: AsyncSession,
    client_id: int,
    number: str,
    *,
    rate: str,
    unit: RateUnit,
    start: date = date(2026, 1, 1),
    end: Optional[date] = None,
    person: tuple[str, str] = ("Ewa", "Przykładowa"),
    status: ClientOrderStatus = ClientOrderStatus.active,
    currency: str = "PLN",
) -> int:
    contract = await _person(db, client_id, *person)
    order = ClientOrder(
        client_id=client_id,
        contract_id=contract.id,
        title=number,
        status=status,
        start_date=start,
        end_date=end,
        rate_client=Decimal(rate),
        rate_unit=unit,
        rate_client_currency=currency,
    )
    db.add(order)
    await db.flush()
    return order.id


async def client(db: AsyncSession, name: str, nip: Optional[str]) -> int:
    row = Client(name=f"{name} {uuid.uuid4().hex[:6]}", nip=nip)
    db.add(row)
    await db.flush()
    return row.id


async def seed_month() -> Seed:
    """Bank Testowy S.A. z czterema zamówieniami za październik 2026 (jak makieta E8)."""

    await wipe()
    async with AsyncSessionLocal() as db:
        client_id = await client(db, "Bank Testowy S.A.", CLIENT_NIP)
        other_id = await client(db, "Ubezpieczenia Przykładowe S.A.", OTHER_CLIENT_NIP)
        seed = Seed(client_id=client_id, other_client_id=other_id)
        g118, (l118,) = await md_group(
            db, client_id, "ZAM/2026/118", people=[("Jan", "Przykładowy", "1200", "21")]
        )
        g124, (l124,) = await md_group(
            db, client_id, "ZAM/2026/124", people=[("Adam", "Testowy", "1150", "19.5")]
        )
        g130, (l130,) = await md_group(
            db, client_id, "ZAM/2026/130", people=[("Tomasz", "Wzorcowy", "1200", "20")]
        )
        o121 = await periodic_order(
            db, client_id, "ZAM/2026/121", rate="190", unit=RateUnit.hourly
        )
        seed.groups.update({"118": g118, "124": g124, "130": g130})
        seed.lines.update({"118": l118, "124": l124, "130": l130})
        seed.orders["121"] = o121
        seed.users["finance"] = await make_user(db, "finance", name="Filip Finansowy")
        seed.users["dl"] = await make_user(
            db, "delivery_lead", name="Kamil Przykładowy"
        )
        seed.users["other_dl"] = await make_user(db, "delivery_lead")
        seed.users["recruiter"] = await make_user(db, "recruiter")
        seed.users["tcm"] = await make_user(db, "talent_community_manager")
        seed.users["admin"] = await make_user(db, "admin")
        db.add(
            DeliveryLeadClientAssignment(
                delivery_lead_user_id=seed.users["dl"].id,
                client_id=client_id,
                is_head=True,
            )
        )
        db.add(
            DeliveryLeadClientAssignment(
                delivery_lead_user_id=seed.users["other_dl"].id,
                client_id=other_id,
                is_head=True,
            )
        )
        await db.commit()
    return seed


async def wipe() -> None:
    """Faktury z fikcyjnych numerów KSeF, stan pobierania i NIP-y fikcyjnych klientów."""

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(ClientSalesInvoicePayment).where(
                ClientSalesInvoicePayment.statement_sha256.is_not(None)
                | ClientSalesInvoicePayment.invoice_id.in_(
                    select(ClientSalesInvoice.id).where(
                        ClientSalesInvoice.ksef_number.like(f"{COMPANY_NIP}-%")
                    )
                )
            )
        )
        await db.execute(
            update(ClientSalesInvoice)
            .where(ClientSalesInvoice.ksef_number.like(f"{COMPANY_NIP}-%"))
            .values(corrects_invoice_id=None)
        )
        await db.execute(
            delete(ClientSalesInvoice).where(
                ClientSalesInvoice.ksef_number.like(f"{COMPANY_NIP}-%")
            )
        )
        await db.execute(
            update(Client).where(Client.nip.in_(FIXTURE_NIPS)).values(nip=None)
        )
        await db.execute(delete(HrJobRun).where(HrJobRun.kind.like("sales_ksef_%")))
        await db.execute(delete(AppSetting).where(AppSetting.key == sync.STATE_KEY))
        await db.commit()


async def invoice(ksef_number: str) -> ClientSalesInvoice:
    async with AsyncSessionLocal() as db:
        found = await db.scalar(
            select(ClientSalesInvoice).where(
                ClientSalesInvoice.ksef_number == ksef_number
            )
        )
        assert found is not None, ksef_number
        return found


def as_dict(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {row[key]: row for row in rows}
