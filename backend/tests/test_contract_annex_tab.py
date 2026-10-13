"""Zakładka „Aneksy” kontraktu — aneks z Generatora aneksów widać od
wygenerowania, a po podpisie wiadomo, skąd jest i jaki ma plik.

Render szablonów jest podmieniony (``_fake_render``). Baza wspólna
i nieczyszczona: asercje wyłącznie na własnych wierszach.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from tests.test_b2b_annex_signed_scan import PDF, _upload
from tests.test_b2b_documents_api import (  # noqa: F401
    BASE,
    _create,
    _fake_render,
    _signed_parent,
    _values,
)
from tests.test_b2b_generated_contract_status import _seed_linked_contract


async def _amendment_count(contract_id: int) -> int:
    from app.models.contract_amendment import ContractAmendment

    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(func.count())
            .select_from(ContractAmendment)
            .where(ContractAmendment.contract_id == contract_id)
        )


async def _hourly(contract_id: int, rate: str = "140") -> None:
    from app.models.contract import Contract, RateUnit

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        contract.rate_candidate = Decimal(rate)
        contract.rate_candidate_currency = "PLN"
        contract.rate_unit = RateUnit.hourly
        await db.commit()


async def _annex_documents(app_client, headers, contract_id: int) -> list[dict]:
    resp = await app_client.get(
        f"/api/contracts/{contract_id}/annex-documents", headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _amendments(app_client, headers, contract_id: int) -> list[dict]:
    resp = await app_client.get(
        f"/api/contracts/{contract_id}/amendments", headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_waiting_annex_shows_on_the_contract_without_becoming_an_amendment(
    app_client, app_auth_headers
):
    """Aneks do umowy spoza NEXUSA: kontrakt pokazuje go od wygenerowania,
    ale historia zmian kontraktu rośnie dopiero po podpisie."""
    contract_id, _ = await _seed_linked_contract()
    await _hourly(contract_id)
    resp = await app_client.post(
        f"{BASE}/documents",
        headers=app_auth_headers,
        json={
            "document_type": "annex_rate_change",
            "language": "pl",
            "contract_id": contract_id,
            "values": _values(
                effective_date="2026-11-01",
                paragraph="6",
                paragraph_section="1",
                rate_items=[{"rate": "150"}],
            ),
        },
    )
    assert resp.status_code == 200, resp.text
    doc_id = int(resp.headers["X-Document-Id"])

    [waiting] = await _annex_documents(app_client, app_auth_headers, contract_id)
    assert waiting["document_id"] == doc_id
    assert waiting["state"] == "waiting"
    assert waiting["effective_date"] == "2026-11-01"
    assert [i["rate"] for i in waiting["change"]["items"]] == [150.0]
    # „Przed” to bieżąca stawka kontraktu — widzi ją osoba z wglądem w stawki.
    assert [i["rate"] for i in waiting["change"]["before"]] == [140.0]
    assert await _amendment_count(contract_id) == 0
    assert await _amendments(app_client, app_auth_headers, contract_id) == []

    signed = await app_client.post(
        f"{BASE}/documents/{doc_id}/confirm-signed", headers=app_auth_headers
    )
    assert signed.status_code == 200, signed.text
    # Po podpisie aneks reprezentuje wpis historii — nie dubluje się.
    assert await _annex_documents(app_client, app_auth_headers, contract_id) == []
    [applied] = await _amendments(app_client, app_auth_headers, contract_id)
    assert applied["source"] == "generator"
    assert applied["b2b_document_id"] == doc_id
    assert applied["state"] in ("in_force", "signed_pending")
    assert applied["document"]["is_signed_scan"] is False

    scan = await _upload(
        app_client,
        app_auth_headers,
        f"/api/contracts/{contract_id}/amendments/{applied['id']}/document",
        "Aneks podpisany.pdf",
        PDF,
    )
    assert scan.status_code == 200, scan.text
    assert scan.json()["document"] == {
        "id": scan.json()["document_id"],
        "filename": "Aneks podpisany.pdf",
        "is_signed_scan": True,
    }


async def test_cancelled_annex_stays_visible_and_manual_amendment_says_manual(
    app_client, app_auth_headers
):
    rid, contract_id = await _signed_parent(app_client)
    doc_id = await _create(
        app_client,
        app_auth_headers,
        "annex_start_date",
        rid,
        new_start_date="2026-11-15",
    )
    cancelled = await app_client.post(
        f"{BASE}/documents/{doc_id}/cancel",
        headers=app_auth_headers,
        json={"reason": "Partner nie podpisał"},
    )
    assert cancelled.status_code == 200, cancelled.text

    [row] = await _annex_documents(app_client, app_auth_headers, contract_id)
    assert row["document_id"] == doc_id
    assert row["state"] == "cancelled"
    assert row["cancelled_reason"] == "Partner nie podpisał"
    assert row["change"] == {
        "kind": "start_date",
        "before": "2026-10-01",
        "after": "2026-11-15",
    }

    manual = await app_client.post(
        f"/api/contracts/{contract_id}/amendments",
        headers=app_auth_headers,
        json={
            "amendment_type": "scope_change",
            "effective_date": "2026-11-01",
            "new_project_name": "Hurtownia danych",
        },
    )
    assert manual.status_code == 201, manual.text
    [listed] = await _amendments(app_client, app_auth_headers, contract_id)
    assert listed["source"] == "manual"
    assert listed["b2b_document_id"] is None
    assert listed["document"] is None
    assert listed["created_by_name"]
