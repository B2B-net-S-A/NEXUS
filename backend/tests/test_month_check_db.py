"""Kontrola miesiąca (0784): przebieg na bazie, stany spraw, decyzje Finansów, karta DL.

Faktury sprzedaży i faktury konsultanta wstawiane wprost. Baza wspólna
i nieczyszczona: asercje wyłącznie na wierszach własnej osoby. Osoby, firmy,
numery faktur i kwoty zmyślone.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_sales_invoice import ClientSalesInvoice
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.hr_approval import ApprovalDocument
from app.models.month_check_case import MonthCheckCase
from app.models.user import User, UserRole
from app.services.month_check import cards, rules, service

TODAY = date(2026, 11, 25)
HOURS = Decimal("160")
PRICE = Decimal("200")
COST = Decimal("150")


def _hex(text: str, size: int) -> str:
    return hashlib.sha256(text.encode()).hexdigest().upper()[:size]


def _sale(tag: str, client_id: int, month: int, person: str) -> ClientSalesInvoice:
    key = f"mc-{tag}-{month}"
    return ClientSalesInvoice(
        ksef_number=f"1234567890-2026{month:02d}10-{_hex(key, 12)}-{_hex(key, 2)}",
        xml_sha256=hashlib.sha256(key.encode()).hexdigest(),
        client_id=client_id,
        invoice_number=f"FS/{tag}/{month}",
        issue_date=date(2026, month + 1, 3),
        period_year=2026,
        period_month=month,
        period_source="invoice",
        net_amount=HOURS * PRICE,
        gross_amount=HOURS * PRICE,
        items=[
            {
                "name": f"Usługi IT, Contractor: {person}",
                "unit": "godz.",
                "quantity": str(HOURS),
                "unit_price": str(PRICE),
                "net": str(HOURS * PRICE),
            }
        ],
    )


def _cost(tag: str, person: str, issued: date, hours: Decimal) -> ApprovalDocument:
    key = f"mc-{tag}-k{issued.isoformat()}"
    return ApprovalDocument(
        source="ksef",
        status="unmatched",
        ksef_number=f"9876543210-{issued:%Y%m%d}-{_hex(key, 12)}-{_hex(key, 2)}",
        seller_nip="1111111111",
        seller_name=f"{person} Usługi Informatyczne",
        invoice_number=f"K/{tag}/{issued.month}",
        issue_date=issued,
        net_amount=hours * COST,
        vat_amount=Decimal("0"),
        gross_amount=hours * COST,
    )


async def _seed() -> tuple[int, str, str]:
    tag = uuid.uuid4().hex[:8]
    first, last = "Testowy", f"Kontrolny{tag}"
    person = f"{first} {last}"
    async with AsyncSessionLocal() as db:
        cand = Candidate(name=first, lastname=last, email=f"mc-{tag}@example.com")
        client = Client(name=f"Klient kontroli {tag}")
        db.add_all([cand, client])
        await db.flush()
        db.add(
            Contract(
                candidate_id=cand.id,
                client_id=client.id,
                status=ContractStatus.active,
                start_date=date(2025, 1, 1),
                rate_unit=RateUnit.hourly,
                rate_client=PRICE,
                rate_candidate=COST,
                rate_client_currency="PLN",
                rate_candidate_currency="PLN",
            )
        )
        for month in (8, 9, 10):
            db.add(_sale(tag, client.id, month, person))
        # VIII zgodny, IX konsultant 200 h zamiast 160 h, X bez faktury konsultanta.
        db.add(_cost(tag, person, date(2026, 8, 31), HOURS))
        db.add(_cost(tag, person, date(2026, 9, 30), Decimal("200")))
        await db.commit()
        return cand.id, tag, person


async def _cases(candidate_id: int) -> dict[str, MonthCheckCase]:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(
                select(MonthCheckCase).where(
                    MonthCheckCase.candidate_id == candidate_id
                )
            )
        ).all()
        return {f"{r.kind}:{r.period_month}": r for r in rows}


async def _run() -> dict:
    async with AsyncSessionLocal() as db:
        return await service.run(db, TODAY)


async def _finance_user() -> User:
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"mc-fin-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("not-a-login"),
            name="Finanse Testowe",
            role=UserRole.finance,
            roles=["finance"],
            is_active=True,
        )
        db.add(user)
        await db.commit()
        return user


@pytest.mark.asyncio
async def test_run_finds_cases_and_closes_them_when_data_is_fixed():
    candidate_id, tag, person = await _seed()
    summary = await _run()
    assert summary["months"] == ["2026-08", "2026-09", "2026-10"]
    cases = await _cases(candidate_id)
    assert set(cases) == {
        f"{rules.HOURS_MISMATCH}:2026-09",
        f"{rules.SALE_WITHOUT_COST}:2026-10",
    }
    hours = cases[f"{rules.HOURS_MISMATCH}:2026-09"]
    assert hours.state == service.NEW
    assert hours.amount == Decimal("6000.00")
    assert hours.details["sales_invoices"] == [f"FS/{tag}/9"]
    missing = cases[f"{rules.SALE_WITHOUT_COST}:2026-10"]
    # Kontrakt bez zamówienia: sprawa danych dla DL.
    assert missing.data_issue == rules.NO_ORDER

    async with AsyncSessionLocal() as db:
        found = [c for c in await cards.open_data_cases(db) if c.case_id == missing.id]
    assert len(found) == 1
    title, message = cards.describe(found[0], "Klient")
    assert person in title and "zł" not in message and "FS/" not in message

    # Faktura konsultanta za X dochodzi — sprawa zamyka się sama.
    async with AsyncSessionLocal() as db:
        db.add(_cost(tag, person, date(2026, 10, 30), HOURS))
        await db.commit()
    await _run()
    cases = await _cases(candidate_id)
    assert cases[f"{rules.SALE_WITHOUT_COST}:2026-10"].state == service.CLOSED
    assert cases[f"{rules.HOURS_MISMATCH}:2026-09"].state == service.NEW


@pytest.mark.asyncio
async def test_finance_decisions_survive_the_next_run():
    candidate_id, _, _ = await _seed()
    await _run()
    user = await _finance_user()
    case_id = (await _cases(candidate_id))[f"{rules.HOURS_MISMATCH}:2026-09"].id

    async with AsyncSessionLocal() as db:
        with pytest.raises(service.MonthCheckError) as refused:
            await service.decide(db, case_id, service.EXPLAINED, user, reason="  ")
        assert refused.value.status == 422
        row = await service.decide(
            db,
            case_id,
            service.EXPLAINED,
            user,
            reason="Nadgodziny w październiku za zgodą klienta",
        )
        assert row.state == service.EXPLAINED
        await db.commit()

    await _run()
    row = (await _cases(candidate_id))[f"{rules.HOURS_MISMATCH}:2026-09"]
    assert row.state == service.EXPLAINED
    assert row.reason == "Nadgodziny w październiku za zgodą klienta"
    assert row.decided_by == user.id

    async with AsyncSessionLocal() as db:
        view = await service.month_view(db, "2026-09", amounts=False, today=TODAY)
    mine = [c for c in view["cases"] if c["candidate_id"] == candidate_id]
    assert mine and all(c["amount"] is None for c in mine)
    assert "contractor_net" not in mine[0]["details"]
    assert view["summary"]["cases_amount"] is None
    assert view["checked_at"] is not None


@pytest.mark.asyncio
async def test_unknown_case_is_404():
    user = await _finance_user()
    async with AsyncSessionLocal() as db:
        with pytest.raises(service.MonthCheckError) as missing:
            await service.decide(db, 987654321, service.TO_CORRECT, user)
    assert missing.value.status == 404
