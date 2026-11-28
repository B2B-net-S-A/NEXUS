"""Kolejka zamyka sama dokument, który powtarza zapisane zamówienie (28.11.2026).

Zgłoszenie: w „Do weryfikacji” czekały PDF-y z planem ``revision`` (zamówienie
o tym numerze już jest — ten sam okres, stawka w innej jednostce) i ``group``
(osoba już jest na linii zamówienia MD z tym numerem). Godzinowa ponowna
weryfikacja przelicza każdy wstrzymany wpis, więc to ona zamyka i nowe,
i dawno czekające dokumenty. Odczyt PDF-a jest podmieniony, resolver, planer
i bramka są prawdziwe. Osoby, numery i stawki są zmyślone. Postgres — CI.

Plik świadomie nie importuje nowego modułu: te same testy odpalone na kodzie
sprzed zmiany padają na ``outcome == "needs_review"``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Optional

import pytest
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.order_mail import OrderMailDocument
from app.services import order_mail_ingest as ingest
from app.services import order_mail_recheck as recheck
from app.services.order_document_text import OrderDocumentText

#: Dokumenty tego pliku. Baza testowa jest wspólna, a każdy bieg ponownej
#: weryfikacji przegląda CAŁĄ kolejkę — wpis zostawiony w „Do weryfikacji”
#: zjadałby budżet biegu w testach innych plików.
_CREATED: list[int] = []


@pytest.fixture(autouse=True)
async def _remove_own_documents():
    yield
    if not _CREATED:
        return
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(OrderMailDocument).where(OrderMailDocument.id.in_(_CREATED))
        )
        await db.commit()
    _CREATED.clear()


_STUB_POLICY = SimpleNamespace(
    key="stub",
    display_name="Stub",
    rule_version="v1",
    extract_rows=None,
    table_authoritative=False,
    reapply_on_refresh=False,
    open_ended_period=False,
    closes_on_md_exhaustion=False,
)


def _use_real_gate(monkeypatch, *doc_ids: int) -> None:
    """Przeliczenie bez PDF-a, z prawdziwym planerem i bramką; bieg tylko po swoich."""
    from app.services.order_pdf_parser import ConsultantOrderRow

    async def fake_refresh(db, row):
        extraction = ingest.restore_extraction(row.extraction)
        policy = SimpleNamespace(**vars(_STUB_POLICY))
        policy.extract_rows = lambda _text: [
            ConsultantOrderRow(
                consultant_name=r.consultant_name,
                rate_client=r.rate_client,
                rate_unit=r.rate_unit,
                uncertain=False,
            )
            for r in extraction.consultant_rows
        ]
        doc = OrderDocumentText("stub", 1, False, False, None, 0.0)
        await ingest._plan_and_gate(
            db, row, extraction, doc, [policy], row.client_id, row.identification_method
        )
        row.error = None

    async def pick(db, *, now):
        return list(doc_ids)

    async def no_card(db, row, **_kwargs):
        return 0

    monkeypatch.setattr(ingest, "refresh_review_plan", fake_refresh)
    monkeypatch.setattr(ingest, "_replannable", lambda row: True)
    monkeypatch.setattr(ingest, "notify_review", no_card)
    monkeypatch.setattr(recheck, "_candidate_ids", pick)


async def _person_with_contract(db, *, unit: RateUnit, rate: str):
    client = Client(name=f"Same order {uuid.uuid4().hex[:8]}")
    first, last = "Roman", "Powtorny" + uuid.uuid4().hex[:6]
    candidate = Candidate(name=first, lastname=last)
    db.add_all([client, candidate])
    await db.flush()
    contract = Contract(
        client_id=client.id,
        candidate_id=candidate.id,
        status=ContractStatus.active,
        start_date=date(2033, 1, 2),
        rate_candidate=Decimal("100"),
        rate_client=Decimal(rate),
        rate_unit=unit,
    )
    db.add(contract)
    await db.flush()
    return client, contract, f"{first} {last}"


async def _held(
    db,
    *,
    client,
    name: str,
    title: str,
    rate: str,
    end: Optional[str],
    total: Optional[str] = None,
):
    doc = OrderMailDocument(
        internet_message_id=f"<{uuid.uuid4()}@same-order.test>",
        attachment_name="zamowienie.pdf",
        storage_path="zamowienie.pdf",
        client_id=client.id,
        identification_method="registry_id",
        client_policy="Stub",
        outcome="needs_review",
        gate_verdict="review",
        received_at=datetime.now(timezone.utc),
        extraction={
            "title": title,
            "start_date": "2033-09-01",
            "end_date": end,
            "rate_client": rate,
            "rate_unit": "day",
            "total_value": total,
            "currency": "PLN",
            "source": "claude",
            "uncertain": False,
            "confidence": {"title": 1.0},
            "consultant_rows": [
                {
                    "consultant_name": name,
                    "rate_client": rate,
                    "rate_unit": "day",
                    "uncertain": False,
                }
            ],
        },
    )
    db.add(doc)
    await db.commit()
    _CREATED.append(doc.id)
    return doc


async def _periodic_order(db, client, contract, title: str) -> ClientOrder:
    # Zamówienie założone ręcznie w godzinach: 140 zł/h = 1120 zł/MD.
    order = ClientOrder(
        client_id=client.id,
        contract_id=contract.id,
        title=title,
        status=ClientOrderStatus.active,
        start_date=date(2033, 9, 1),
        end_date=date(2033, 11, 30),
        rate_client=Decimal("140"),
        rate_candidate=Decimal("100"),
        rate_unit=RateUnit.hourly,
        order_type="periodic",
    )
    db.add(order)
    await db.commit()
    return order


@pytest.mark.asyncio
async def test_revision_identical_to_the_order_is_closed_with_a_note(monkeypatch):
    async with AsyncSessionLocal() as db:
        client, contract, name = await _person_with_contract(
            db, unit=RateUnit.hourly, rate="140"
        )
        title = f"{uuid.uuid4().int % 9000 + 1000}/2033"
        order = await _periodic_order(db, client, contract, title)
        doc = await _held(
            db, client=client, name=name, title=title, rate="1120.00", end="2033-11-30"
        )
        _use_real_gate(monkeypatch, doc.id)

        result = await recheck.run_recheck(db)

        await db.refresh(doc)
        assert doc.proposal["rows"][0]["action"] == "revision"
        assert doc.outcome == "dismissed"
        assert doc.gate_reasons[0].startswith(f"To samo co zamówienie #{order.id}")
        assert doc.document_meta["same_as_orders"] == [order.id]
        assert doc.document_meta["dismissed_from"] == "needs_review"
        entry = next(e for e in result.details if e["document_id"] == doc.id)
        assert entry["outcome"] == "closed"
        # Zamówienie zostaje nietknięte.
        await db.refresh(order)
        assert order.rate_client == Decimal("140") and order.end_date == date(
            2033, 11, 30
        )


@pytest.mark.asyncio
async def test_revision_with_a_misread_rate_stays_for_a_human(monkeypatch):
    async with AsyncSessionLocal() as db:
        client, contract, name = await _person_with_contract(
            db, unit=RateUnit.hourly, rate="140"
        )
        title = f"{uuid.uuid4().int % 9000 + 1000}/2033"
        order = await _periodic_order(db, client, contract, title)
        doc = await _held(
            db, client=client, name=name, title=title, rate="18700.00", end="2033-11-30"
        )
        _use_real_gate(monkeypatch, doc.id)

        await recheck.run_recheck(db)

        await db.refresh(doc)
        assert doc.outcome == "needs_review"
        assert f"„{name}”: odczyt różni się od #{order.id}: stawka" in doc.gate_reasons
        assert "differs_from_order" in doc.gate_reason_codes


@pytest.mark.asyncio
async def test_revision_with_another_period_stays_for_a_human(monkeypatch):
    async with AsyncSessionLocal() as db:
        client, contract, name = await _person_with_contract(
            db, unit=RateUnit.hourly, rate="140"
        )
        title = f"{uuid.uuid4().int % 9000 + 1000}/2033"
        order = await _periodic_order(db, client, contract, title)
        doc = await _held(
            db, client=client, name=name, title=title, rate="1120.00", end="2033-12-31"
        )
        _use_real_gate(monkeypatch, doc.id)

        await recheck.run_recheck(db)

        await db.refresh(doc)
        assert doc.outcome == "needs_review"
        assert f"„{name}”: odczyt różni się od #{order.id}: okres" in doc.gate_reasons


async def _md_line(db, client, contract, number: str) -> ClientOrder:
    group = ClientOrderGroup(
        client_id=client.id,
        order_number=number,
        start_date=date(2033, 9, 1),
        status="active",
        order_type="md",
        is_cost_based=False,
        is_md_budget_based=False,
    )
    db.add(group)
    await db.flush()
    line = ClientOrder(
        client_id=client.id,
        contract_id=contract.id,
        order_group_id=group.id,
        title=f"Zamówienie {number} — linia",
        status=ClientOrderStatus.active,
        start_date=date(2033, 9, 1),
        rate_client=Decimal("1600"),
        rate_candidate=Decimal("1200"),
        rate_unit=RateUnit.daily,
        md_total=Decimal("50"),
        md_remaining=Decimal("50"),
        md_input_mode="md",
        md_input_value=Decimal("50"),
        md_rate_revenue=Decimal("1600"),
        order_type="md",
    )
    db.add(line)
    await db.commit()
    return line


@pytest.mark.asyncio
async def test_person_already_on_the_md_line_with_this_number_is_closed(monkeypatch):
    async with AsyncSessionLocal() as db:
        client, contract, name = await _person_with_contract(
            db, unit=RateUnit.daily, rate="1600"
        )
        number = f"SAP 45099{uuid.uuid4().int % 90000 + 10000}"
        line = await _md_line(db, client, contract, number)
        doc = await _held(
            db,
            client=client,
            name=name,
            title=number,
            rate="1600.00",
            end=None,
            total="80000",
        )
        _use_real_gate(monkeypatch, doc.id)

        await recheck.run_recheck(db)

        await db.refresh(doc)
        assert doc.proposal["rows"][0]["action"] == "group"
        assert doc.outcome == "dismissed"
        assert doc.document_meta["same_as_orders"] == [line.id]


@pytest.mark.asyncio
async def test_md_line_with_another_pool_stays_for_a_human(monkeypatch):
    async with AsyncSessionLocal() as db:
        client, contract, name = await _person_with_contract(
            db, unit=RateUnit.daily, rate="1600"
        )
        number = f"SAP 45099{uuid.uuid4().int % 90000 + 10000}"
        line = await _md_line(db, client, contract, number)
        doc = await _held(
            db,
            client=client,
            name=name,
            title=number,
            rate="1600.00",
            end=None,
            total="96000",
        )
        _use_real_gate(monkeypatch, doc.id)

        await recheck.run_recheck(db)

        await db.refresh(doc)
        assert doc.outcome == "needs_review"
        assert f"„{name}”: odczyt różni się od #{line.id}: pula" in doc.gate_reasons
