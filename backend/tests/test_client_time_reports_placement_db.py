"""Faktura kontraktora → osoba, gdy NIP nie rozstrzyga (odpowiedź rozliczeń 13.11).

(a) spółka wystawia za kilka osób, (b) dwie osoby ze spółki o różnych stawkach:
rozstrzyga kwota = godziny zatwierdzone w raporcie klienta × stawka osoby;
(c) jedna faktura za pracę osoby u dwóch klientów pasuje do sumy rozliczeń,
a ekran raportu klienta odejmuje część drugiego klienta. Dane fikcyjne.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import local_now
from app.models.candidate import Candidate
from app.models.client_settlement import ClientContractorInvoice, ClientSettlement
from app.models.contract import ContractStatus, RateUnit
from app.services.client_settlements import contractor_invoices as ci
from app.services.client_settlements import time_reports
from tests.test_client_audit_2026_09_24 import _cleanup, _client, _contract
from tests.test_client_settlements_contractor_invoices_db import _item, _nip
from tests.test_client_time_reports_db import MONTH, _rows, _upload, _view, _xlsx

pytestmark = pytest.mark.asyncio

ACTOR = SimpleNamespace(id=None)
ISSUE = date(2026, 10, 2)


async def _person(client_id: int, first: str, last: str, *, nip: str, rate: int) -> int:
    async with AsyncSessionLocal() as db:
        candidate = Candidate(name=first, lastname=last, nip=nip)
        db.add(candidate)
        await db.commit()
        candidate_id = candidate.id
    return await _contract(
        client_id,
        candidate_id,
        start_date=date(2026, 1, 1),
        rate_unit=RateUnit.hourly,
        rate_candidate=rate,
        rate_client=rate + 20,
        status=ContractStatus.active,
    )


async def _number(client_id: int, contract_id: int, value: str) -> None:
    async with AsyncSessionLocal() as db:
        await time_reports.add_manual_id(
            db,
            client_id,
            contract_id=contract_id,
            kind="client_person_no",
            value=value,
            actor=ACTOR,
            now=local_now(),
        )
        await db.commit()


async def _consider(nip: str, name: str, net: str) -> ClientContractorInvoice:
    item = _item(nip, name, net, ISSUE)
    async with AsyncSessionLocal() as db:
        index = await ci.load_index(db, ISSUE)
        await ci.consider(db, index, item, item["ksefNumber"])
        await db.commit()
        return await db.scalar(
            select(ClientContractorInvoice).where(
                ClientContractorInvoice.ksef_number == item["ksefNumber"]
            )
        )


async def _drop(client_ids: list[int], nips: list[str]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(ClientContractorInvoice).where(
                ClientContractorInvoice.seller_nip.in_(nips)
            )
        )
        await db.commit()
    for client_id in client_ids:
        await _cleanup(client_id)


async def test_spolka_za_kilka_osob_rozstrzyga_kwota_z_raportu_i_stawka():
    client_id = await _client()
    company = _nip()
    first = await _person(client_id, "Jan", "Testowy", nip=company, rate=100)
    second = await _person(client_id, "Anna", "Przykładowa", nip=company, rate=120)
    third = await _person(client_id, "Ewa", "Próbna", nip=company, rate=110)
    try:
        for contract_id, number in (
            (first, "M000001"),
            (second, "M000002"),
            (third, "M000003"),
        ):
            await _number(client_id, contract_id, number)
        report = _xlsx(
            _rows("M000001", "Jan Testowy"),  # 176 h × 100 = 17 600
            _rows("M000002", "Anna Przykładowa"),  # 176 h × 120 = 21 120
            _rows("M000003", "Ewa Próbna"),  # 176 h × 110 = 19 360
        )
        await _upload(client_id, report, date(2026, 10, 1))

        # (a) faktura spółki za jedną z osób: kwota wskazuje Annę.
        invoice = await _consider(company, "Spółka Testowa sp. z o.o.", "21120.00")
        assert invoice.contract_id == second and invoice.period_month == MONTH
        # (b) druga osoba z tej samej spółki, inna stawka: kwota wskazuje Ewę.
        invoice = await _consider(company, "Spółka Testowa sp. z o.o.", "19360.00")
        assert invoice.contract_id == third
        # Kwota nikogo — faktura bez osoby do ręcznego przypisania.
        invoice = await _consider(company, "Spółka Testowa sp. z o.o.", "1000.00")
        assert invoice.contract_id is None

        view = await _view(client_id)
        by_key = {r["key"]: r for r in view["rows"]}
        assert by_key["M000002"]["status"] == "ok"
        assert by_key["M000003"]["status"] == "ok"
        assert by_key["M000001"]["status"] == "no_invoice"
    finally:
        await _drop([client_id], [company])


async def test_jedna_faktura_za_dwoch_klientow_pasuje_do_sumy_rozliczen():
    client_id = await _client()
    other_client = await _client()
    nip = _nip()
    nordea = await _person(client_id, "Jan", "Testowy", nip=nip, rate=100)
    async with AsyncSessionLocal() as db:
        candidate_id = (
            await db.execute(select(Candidate.id).where(Candidate.nip == nip))
        ).scalar_one()
    other = await _contract(
        other_client,
        candidate_id,
        start_date=date(2026, 1, 1),
        rate_unit=RateUnit.daily,
        rate_candidate=1000,
        status=ContractStatus.active,
    )
    try:
        await _number(client_id, nordea, "M000001")
        await _upload(
            client_id, _xlsx(_rows("M000001", "Jan Testowy")), date(2026, 10, 1)
        )
        async with AsyncSessionLocal() as db:
            db.add(
                ClientSettlement(
                    contract_id=other,
                    client_id=other_client,
                    period_month=MONTH,
                    status="accepted",
                    md_regular=Decimal("5"),
                    md_charged=Decimal("5"),
                    amount_cost=Decimal("5000.00"),
                    amount_revenue=Decimal("6000.00"),
                )
            )
            await db.commit()

        # (c) 176 h × 100 + 5 MD × 1000 = 22 600 jedną fakturą.
        invoice = await _consider(nip, "Jan Testowy", "22600.00")
        assert invoice.contract_id == nordea and invoice.period_month == MONTH

        view = await _view(client_id)
        (row,) = view["rows"]
        assert row["status"] == "ok"
        assert row["invoice_hours"] == "176.00"
        assert "innego klienta" in row["notes"][0]
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(ClientSettlement).where(ClientSettlement.contract_id == other)
            )
            await db.commit()
        await _drop([client_id, other_client], [nip])
