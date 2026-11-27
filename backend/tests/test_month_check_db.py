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
from app.models.consultant_portal import CpDocument
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.finance_archive import FinanceArchiveDocument
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


@pytest.mark.asyncio
async def test_unchecked_person_month_and_explained_case_are_not_closed():
    candidate_id, tag, person = await _seed()
    await _run()
    user = await _finance_user()
    cases = await _cases(candidate_id)
    hours_id = cases[f"{rules.HOURS_MISMATCH}:2026-09"].id
    async with AsyncSessionLocal() as db:
        await service.decide(db, hours_id, service.TO_CORRECT, user)
        await db.commit()
    # Drugi kontrakt tej osoby od września: IX i X nie są już sprawdzane.
    async with AsyncSessionLocal() as db:
        first = await db.scalar(
            select(Contract).where(Contract.candidate_id == candidate_id)
        )
        db.add(
            Contract(
                candidate_id=candidate_id,
                client_id=first.client_id,
                status=ContractStatus.active,
                start_date=date(2026, 9, 1),
                rate_unit=RateUnit.hourly,
                rate_client=PRICE,
                rate_candidate=COST,
                rate_client_currency="PLN",
                rate_candidate_currency="PLN",
            )
        )
        await db.commit()
    await _run()
    cases = await _cases(candidate_id)
    assert cases[f"{rules.HOURS_MISMATCH}:2026-09"].state == service.TO_CORRECT
    assert cases[f"{rules.SALE_WITHOUT_COST}:2026-10"].state == service.NEW


@pytest.mark.asyncio
async def test_paper_invoice_from_ebi24_archive_counts_as_cost():
    """Faktura spoza KSeF w archiwum eBI24 zamyka „sprzedaż bez kosztu” (Finanse 27.11.2026)."""

    candidate_id, tag, person = await _seed()
    await _run()
    assert f"{rules.SALE_WITHOUT_COST}:2026-10" in await _cases(candidate_id)

    async with AsyncSessionLocal() as db:
        net = HOURS * COST
        db.add(
            FinanceArchiveDocument(
                source="ebi24",
                source_id=f"mc-{tag}-paper",
                schema_name="test",
                kind="cost",
                invoice_number=f"P/{tag}/10",
                issue_date=date(2026, 10, 30),
                partner_name=f"{person} Usługi Informatyczne",
                partner_id="2222222222",
                currency="PLN",
                net_amount=net,
                gross_amount=net,
                file_type="pdf",
                file_path=f"test/{tag}.pdf",
                file_sha256=hashlib.sha256(tag.encode()).hexdigest(),
            )
        )
        await db.commit()
    await _run()
    cases = await _cases(candidate_id)
    assert cases[f"{rules.SALE_WITHOUT_COST}:2026-10"].state == service.CLOSED


# ── Faktura PDF z poczty rozliczeń (27.11.2026): równolegle z eBI24 ──────────


def _pdf_fields(tag: str, person: str, **patch) -> dict:
    net = HOURS * COST
    fields = {
        "version": "expense_read:v1",
        "status": "read",
        "doc_type": "invoice",
        "seller_name": f"{person} Usługi Informatyczne",
        "seller_nip": None,
        "invoice_number": f"P/{tag}/10",
        "issue_date": "2026-10-30",
        "currency": "PLN",
        "net_amount": str(net),
        "vat_amount": "0.00",
        "gross_amount": str(net),
    }
    fields.update(patch)
    return fields


async def _contract_of(candidate_id: int) -> int:
    async with AsyncSessionLocal() as db:
        return (
            await db.scalars(
                select(Contract.id).where(Contract.candidate_id == candidate_id)
            )
        ).one()


def _pdf(tag: str, fields: dict, *, contract_id, status: str = "received", n: int = 0):
    return CpDocument(
        contract_id=contract_id,
        kind="invoice",
        period_year=2026,
        period_month=10,
        channel="mailbox",
        status=status,
        file_path=f"consultant_portal/test/{tag}-{n}.pdf",
        file_name=f"faktura-{n}.pdf",
        mime="application/pdf",
        size_bytes=100,
        sha256=hashlib.sha256(f"{tag}-{n}".encode()).hexdigest(),
        invoice_fields=fields,
    )


@pytest.mark.asyncio
async def test_pdf_invoice_from_settlements_mailbox_counts_as_cost():
    """Faktura PDF spoza KSeF z rozliczenia@ zamyka „sprzedaż bez kosztu”, odrzucona nie."""

    candidate_id, tag, person = await _seed()
    contract_id = await _contract_of(candidate_id)
    async with AsyncSessionLocal() as db:
        db.add(
            _pdf(
                tag,
                _pdf_fields(tag, person),
                contract_id=contract_id,
                status="rejected",
            )
        )
        await db.commit()
    await _run()
    cases = await _cases(candidate_id)
    assert cases[f"{rules.SALE_WITHOUT_COST}:2026-10"].state == service.NEW

    async with AsyncSessionLocal() as db:
        db.add(_pdf(tag, _pdf_fields(tag, person), contract_id=contract_id, n=1))
        await db.commit()
    await _run()
    cases = await _cases(candidate_id)
    assert cases[f"{rules.SALE_WITHOUT_COST}:2026-10"].state == service.CLOSED


@pytest.mark.asyncio
async def test_same_invoice_in_ebi24_and_pdf_counts_once():
    """eBI24 i NEXUS równolegle: ta sama faktura z archiwum i z maila to jeden koszt.

    Liczona dwa razy dałaby 320 h kosztu przy 160 h sprzedaży (inna liczba godzin)."""

    candidate_id, tag, person = await _seed()
    contract_id = await _contract_of(candidate_id)
    net = HOURS * COST
    async with AsyncSessionLocal() as db:
        db.add(
            FinanceArchiveDocument(
                source="ebi24",
                source_id=f"mc-{tag}-twin",
                schema_name="test",
                kind="cost",
                invoice_number=f"P/{tag}/10",
                issue_date=date(2026, 10, 30),
                partner_name=f"{person} Usługi Informatyczne",
                partner_id="2222222222",
                currency="PLN",
                net_amount=net,
                gross_amount=net,
                file_type="pdf",
                file_path=f"test/{tag}-twin.pdf",
                file_sha256=hashlib.sha256(f"{tag}-twin".encode()).hexdigest(),
            )
        )
        # Ten sam numer zapisany inaczej i drugi plik tej samej faktury bez numeru.
        db.add(
            _pdf(
                tag,
                _pdf_fields(tag, person, invoice_number=f"p {tag} 10"),
                contract_id=contract_id,
                n=2,
            )
        )
        db.add(
            _pdf(
                tag,
                _pdf_fields(tag, person, invoice_number=None),
                contract_id=contract_id,
                n=3,
            )
        )
        await db.commit()
    await _run()
    cases = await _cases(candidate_id)
    # Koszt jest od pierwszego przebiegu: ani „bez kosztu”, ani „inna liczba godzin”.
    assert f"{rules.SALE_WITHOUT_COST}:2026-10" not in cases
    assert f"{rules.HOURS_MISMATCH}:2026-10" not in cases


@pytest.mark.asyncio
async def test_pdf_without_contract_is_bound_by_invoice_nip():
    """Dokument czeka na „Przypisz”, ale NIP z faktury wskazuje jedną osobę z kontraktem."""

    candidate_id, tag, person = await _seed()
    await _run()
    assert f"{rules.SALE_WITHOUT_COST}:2026-10" in await _cases(candidate_id)
    # Zmyślony, unikatowy w bazie testów (wspólnej i nieczyszczonej).
    nip = "9" + str(int(tag, 16) % 10**9).zfill(9)
    async with AsyncSessionLocal() as db:
        cand = await db.get(Candidate, candidate_id)
        cand.nip = nip
        db.add(
            _pdf(
                tag,
                _pdf_fields(tag, "Inna Nazwa Firmy", seller_nip=nip),
                contract_id=None,
                n=4,
            )
        )
        await db.commit()
    await _run()
    cases = await _cases(candidate_id)
    assert cases[f"{rules.SALE_WITHOUT_COST}:2026-10"].state == service.CLOSED
