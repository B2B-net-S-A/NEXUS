"""Historia stawek z faktur KSeF (0782): przebieg, wpis automatyczny, karta, cofnięcie.

Faktury sprzedaży i faktury konsultanta wstawiane wprost. Baza wspólna
i nieczyszczona: przebieg zawężony do własnego kontraktu, asercje wyłącznie
na własnych wierszach. Osoby, firmy i kwoty zmyślone.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_sales_invoice import ClientSalesInvoice
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.contract_candidate_rate import ContractCandidateRate
from app.models.contract_client_rate import ContractClientRate
from app.models.contract_rate_history_finding import ContractRateHistoryFinding
from app.models.hr_approval import ApprovalDocument
from app.services.contract_rate_history import service

HOURS = Decimal("160")
#: Wiosna: inna stawka niż dziś w kontrakcie (brak historii).
CLIENT = {4: "250", 5: "250", 6: "250", 7: "200", 8: "200", 9: "200"}
COST = {4: "190", 5: "190", 6: "190", 7: "150", 8: "150", 9: "150"}


def _hex(text: str, size: int) -> str:
    return hashlib.sha256(text.encode()).hexdigest().upper()[:size]


async def _seed(*, client_rates=CLIENT, cost_rates=COST) -> int:
    tag = uuid.uuid4().hex[:8]
    first, last = "Testowy", f"Fikcyjny{tag}"
    async with AsyncSessionLocal() as db:
        cand = Candidate(name=first, lastname=last, email=f"rh-{tag}@example.com")
        client = Client(name=f"Klient historii {tag}")
        db.add_all([cand, client])
        await db.flush()
        contract = Contract(
            candidate_id=cand.id,
            client_id=client.id,
            status=ContractStatus.active,
            start_date=date(2025, 1, 1),
            rate_unit=RateUnit.hourly,
            rate_client=Decimal("200"),
            rate_candidate=Decimal("150"),
            rate_client_currency="PLN",
            rate_candidate_currency="PLN",
        )
        db.add(contract)
        await db.flush()
        for month, price in client_rates.items():
            key = f"{tag}-{month}"
            db.add(
                ClientSalesInvoice(
                    ksef_number=f"1234567890-2026{month:02d}10-{_hex(key, 12)}-{_hex(key, 2)}",
                    xml_sha256=hashlib.sha256(key.encode()).hexdigest(),
                    client_id=client.id,
                    invoice_number=f"FS/{tag}/{month}",
                    issue_date=date(2026, month + 1, 3),
                    period_year=2026,
                    period_month=month,
                    period_source="invoice",
                    net_amount=HOURS * Decimal(price),
                    gross_amount=HOURS * Decimal(price),
                    items=[
                        {
                            "name": f"Usługi IT, Contractor: {first} {last}",
                            "unit": "godz.",
                            "quantity": str(HOURS),
                            "unit_price": price,
                            "net": str(HOURS * Decimal(price)),
                        }
                    ],
                )
            )
        for month, rate in cost_rates.items():
            key = f"{tag}-k{month}"
            db.add(
                ApprovalDocument(
                    source="ksef",
                    status="unmatched",
                    ksef_number=f"9876543210-2026{month:02d}28-{_hex(key, 12)}-{_hex(key, 2)}",
                    seller_nip="1111111111",
                    seller_name=f"{first} {last} Usługi Informatyczne",
                    invoice_number=f"K/{tag}/{month}",
                    issue_date=date(2026, month, 28),
                    net_amount=HOURS * Decimal(rate),
                    vat_amount=Decimal("0"),
                    gross_amount=HOURS * Decimal(rate),
                )
            )
        await db.commit()
        return contract.id


async def _run(contract_id: int, *, auto_apply: bool = True) -> None:
    async with AsyncSessionLocal() as db:
        await service.run(
            db, business_today(), auto_apply=auto_apply, contract_ids={contract_id}
        )


async def _schedules(contract_id: int) -> tuple[list, list]:
    async with AsyncSessionLocal() as db:
        client = (
            await db.scalars(
                select(ContractClientRate)
                .where(ContractClientRate.contract_id == contract_id)
                .order_by(ContractClientRate.effective_from, ContractClientRate.id)
            )
        ).all()
        cost = (
            await db.scalars(
                select(ContractCandidateRate)
                .where(ContractCandidateRate.contract_id == contract_id)
                .order_by(
                    ContractCandidateRate.effective_from, ContractCandidateRate.id
                )
            )
        ).all()
        return (
            [(r.effective_from.isoformat(), float(r.rate)) for r in client],
            [(r.effective_from.isoformat(), float(r.rate)) for r in cost],
        )


async def test_history_is_filled_automatically_and_undo_returns_it_to_the_card(
    app_client, app_auth_headers
):
    contract_id = await _seed()
    await _run(contract_id)

    client, cost = await _schedules(contract_id)
    assert client == [
        ("2025-01-01", 200.0),
        ("2026-04-01", 250.0),
        ("2026-07-01", 200.0),
    ]
    assert cost == [("2025-01-01", 150.0), ("2026-04-01", 190.0), ("2026-07-01", 150.0)]
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        # Dzisiejsza stawka bez zmian — automat wpisuje tylko historię.
        assert contract.rate_client == Decimal("200")
        assert contract.rate_candidate == Decimal("150")

    card = await app_client.get(
        f"/api/contracts/{contract_id}/rate-history-ksef", headers=app_auth_headers
    )
    assert card.status_code == 200, card.text
    item = card.json()["item"]
    assert item["status"] == "auto_applied" and item["undo_until"]
    assert item["category"] == "brak_historii"
    spring = next(
        s for s in item["steps"] if s["leg"] == "client" and s["from"] == "2026-04-01"
    )
    assert spring["rate"] == 250.0 and spring["nexus_rate"] == 200.0
    assert spring["months"] == ["2026-04", "2026-05", "2026-06"]

    # Drugi przebieg niczego nie dopisuje (harmonogram zgadza się z fakturami).
    await _run(contract_id)
    assert (await _schedules(contract_id))[0] == client

    undo = await app_client.post(
        f"/api/contracts/{contract_id}/rate-history-ksef/undo", headers=app_auth_headers
    )
    assert undo.status_code == 200, undo.text
    assert undo.json()["status"] == "undone"
    assert await _schedules(contract_id) == ([], [])

    # Cofnięte: automat już nie wpisuje, karta czeka na człowieka.
    await _run(contract_id)
    assert await _schedules(contract_id) == ([], [])
    listed = await app_client.get(
        "/api/contracts?bucket=rate_history&page_size=100", headers=app_auth_headers
    )
    assert listed.status_code == 200, listed.text
    row = next(i for i in listed.json()["items"] if i["id"] == contract_id)
    assert row["rate_history_change"]["from"] == "2026-04-01"

    applied = await app_client.post(
        f"/api/contracts/{contract_id}/rate-history-ksef/apply",
        headers=app_auth_headers,
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["status"] == "applied"
    assert (await _schedules(contract_id))[0] == client
    again = await app_client.post(
        f"/api/contracts/{contract_id}/rate-history-ksef/apply",
        headers=app_auth_headers,
    )
    assert again.status_code == 409


async def test_current_client_gap_waits_for_human_and_is_refused_without_annex(
    app_client, app_auth_headers
):
    contract_id = await _seed(
        client_rates={7: "220", 8: "220", 9: "220"}, cost_rates={7: "150", 8: "150"}
    )
    await _run(contract_id)
    assert await _schedules(contract_id) == ([], [])
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(ContractRateHistoryFinding).where(
                ContractRateHistoryFinding.contract_id == contract_id
            )
        )
        assert row.status == "open" and not row.automatic
        assert row.category == "rozjazd_biezacy"

    refused = await app_client.post(
        f"/api/contracts/{contract_id}/rate-history-ksef/apply",
        headers=app_auth_headers,
    )
    assert refused.status_code == 409
    assert "zamówienie" in refused.json()["detail"]

    dismissed = await app_client.post(
        f"/api/contracts/{contract_id}/rate-history-ksef/dismiss",
        headers=app_auth_headers,
    )
    assert dismissed.status_code == 200, dismissed.text
    await _run(contract_id)
    card = await app_client.get(
        f"/api/contracts/{contract_id}/rate-history-ksef", headers=app_auth_headers
    )
    # Ta sama propozycja po odrzuceniu już nie wraca.
    assert card.json()["item"] is None
