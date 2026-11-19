"""Stawka z dokumentu kontraktu (0739): karta, filtr listy, wpis, odrzucenie, cofnięcie.

Odczyt modelu jest wstawiany wprost (bez wywołania AI). Baza wspólna
i nieczyszczona: asercje wyłącznie na własnych wierszach. Kwoty zmyślone.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.contract import Contract, RateUnit
from app.models.contract_candidate_rate import ContractCandidateRate
from app.models.contract_document import ContractDocument, ContractDocumentType
from app.models.contract_document_rate_read import ContractDocumentRateRead
from app.services.contract_rate_documents import reader, service
from tests.test_b2b_generated_contract_status import _seed_linked_contract


async def _contract(rate: str = "100") -> int:
    contract_id, _ = await _seed_linked_contract()
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        contract.rate_candidate = Decimal(rate)
        contract.rate_candidate_currency = "PLN"
        contract.rate_unit = RateUnit.hourly
        contract.start_date = business_today() - timedelta(days=60)
        await db.commit()
    return contract_id


async def _read(
    contract_id: int, rate: float, days_ahead: int = 10, *, kind: str = "annex"
) -> int:
    frm = (business_today() + timedelta(days=days_ahead)).isoformat()
    async with AsyncSessionLocal() as db:
        doc = ContractDocument(
            contract_id=contract_id,
            filename="Aneks stawka test.pdf",
            file_path=f"contracts/{contract_id}/test-rate-doc.pdf",
            content_type="application/pdf",
            doc_type=ContractDocumentType.annex,
        )
        db.add(doc)
        await db.flush()
        row = ContractDocumentRateRead(
            contract_document_id=doc.id,
            contract_id=contract_id,
            reader_version=reader.READER_VERSION,
            status="read",
            result={
                "kind": kind,
                "changes_rate": True,
                "document_date": business_today().isoformat(),
                "effective_from": frm,
                "rate_steps": [
                    {
                        "rate": rate,
                        "currency": "PLN",
                        "unit": "hour",
                        "from": frm,
                        "to": None,
                        "condition": None,
                    }
                ],
                "quote": f"wynagrodzenie w wysokości {rate} zł netto za roboczogodzinę",
            },
        )
        db.add(row)
        await db.flush()
        await service.refresh_contract(db, contract_id)
        await db.commit()
        return row.id


async def _schedule(contract_id: int) -> list[tuple[str, float]]:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(ContractCandidateRate)
                .where(ContractCandidateRate.contract_id == contract_id)
                .order_by(
                    ContractCandidateRate.effective_from, ContractCandidateRate.id
                )
            )
        ).scalars()
        return [(r.effective_from.isoformat(), float(r.rate)) for r in rows]


async def test_finding_shows_on_contract_and_in_list_bucket(
    app_client, app_auth_headers
):
    contract_id = await _contract()
    read_id = await _read(contract_id, 110)

    resp = await app_client.get(
        f"/api/contracts/{contract_id}/rate-documents", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    [item] = resp.json()["items"]
    assert item["id"] == read_id and item["category"] == "auto"
    assert item["steps"][0]["rate"] == 110.0 and item["steps"][0]["nexus_rate"] == 100.0
    assert "110" in item["quote"]

    listed = await app_client.get(
        "/api/contracts?bucket=rate_document&page_size=500", headers=app_auth_headers
    )
    assert listed.status_code == 200, listed.text
    row = next(i for i in listed.json()["items"] if i["id"] == contract_id)
    assert row["rate_document_change"]["rate"] == 110.0


async def test_apply_adds_step_and_closes_finding(app_client, app_auth_headers):
    contract_id = await _contract()
    read_id = await _read(contract_id, 112)

    resp = await app_client.post(
        f"/api/contracts/{contract_id}/rate-documents/{read_id}/apply",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["decision"] == "applied"
    assert (business_today() + timedelta(days=10)).isoformat() in dict(
        await _schedule(contract_id)
    )

    after = await app_client.get(
        f"/api/contracts/{contract_id}/rate-documents", headers=app_auth_headers
    )
    assert after.json()["items"] == []
    again = await app_client.post(
        f"/api/contracts/{contract_id}/rate-documents/{read_id}/apply",
        headers=app_auth_headers,
    )
    assert again.status_code == 409


async def test_dismiss_removes_contract_from_bucket(app_client, app_auth_headers):
    contract_id = await _contract()
    read_id = await _read(contract_id, 109)
    resp = await app_client.post(
        f"/api/contracts/{contract_id}/rate-documents/{read_id}/dismiss",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    listed = await app_client.get(
        "/api/contracts?bucket=rate_document&page_size=500", headers=app_auth_headers
    )
    assert contract_id not in {i["id"] for i in listed.json()["items"]}


async def test_read_of_other_contract_is_refused(app_client, app_auth_headers):
    contract_id = await _contract()
    other_id = await _contract()
    read_id = await _read(other_id, 111)
    resp = await app_client.post(
        f"/api/contracts/{contract_id}/rate-documents/{read_id}/apply",
        headers=app_auth_headers,
    )
    assert resp.status_code == 409


async def test_auto_apply_then_undo_restores_rate(app_client, app_auth_headers):
    contract_id = await _contract()
    read_id = await _read(contract_id, 108, days_ahead=-5)
    async with AsyncSessionLocal() as db:
        await service.apply_read(db, read_id, user=None)
        await db.commit()
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        assert float(contract.rate_candidate) == 108.0

    card = await app_client.get(
        f"/api/contracts/{contract_id}/rate-documents", headers=app_auth_headers
    )
    [item] = card.json()["items"]
    assert item["decision"] == "auto_applied" and item["undo_until"]

    resp = await app_client.post(
        f"/api/contracts/{contract_id}/rate-documents/{read_id}/undo",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        assert float(contract.rate_candidate) == 100.0
    # Cofnięty wpis wraca na kartę do decyzji człowieka.
    card = await app_client.get(
        f"/api/contracts/{contract_id}/rate-documents", headers=app_auth_headers
    )
    [item] = card.json()["items"]
    assert item["decision"] == "undone" and item["steps"][0]["rate"] == 108.0


async def test_undo_on_contract_without_schedule_restores_old_rate(
    app_client, app_auth_headers
):
    """Pusty harmonogram: wpis zakłada krok bazowy, „Cofnij” usuwa wszystkie kroki
    wpisu i przywraca starą stawkę (kolumna trzymała już nową)."""
    contract_id = await _contract("120")
    read_id = await _read(contract_id, 130, days_ahead=-20)
    assert await _schedule(contract_id) == []
    async with AsyncSessionLocal() as db:
        await service.apply_read(db, read_id, user=None)
        await db.commit()
    assert len(await _schedule(contract_id)) == 2  # bazowy 120 + 130
    resp = await app_client.post(
        f"/api/contracts/{contract_id}/rate-documents/{read_id}/undo",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert await _schedule(contract_id) == []
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        assert float(contract.rate_candidate) == 120.0


async def test_condition_step_is_never_applied(app_client, app_auth_headers):
    """Stawka „dla klienta X” z aneksu nie wchodzi do harmonogramu jednym klikiem."""
    contract_id = await _contract()
    read_id = await _read(contract_id, 111)
    async with AsyncSessionLocal() as db:
        row = await db.get(ContractDocumentRateRead, read_id)
        steps = [dict(s, condition="klient B") for s in row.result["rate_steps"]]
        row.result = {**row.result, "rate_steps": steps}
        await db.flush()
        await service.refresh_contract(db, contract_id)
        await db.commit()
    resp = await app_client.post(
        f"/api/contracts/{contract_id}/rate-documents/{read_id}/apply",
        headers=app_auth_headers,
    )
    assert resp.status_code == 409
    assert await _schedule(contract_id) == []


async def test_automat_never_applies_review_finding():
    contract_id = await _contract()
    read_id = await _read(contract_id, 160)  # +60% → do sprawdzenia
    async with AsyncSessionLocal() as db:
        with pytest.raises(service.RateDocumentError):
            await service.apply_read(db, read_id, user=None)
        await db.rollback()
