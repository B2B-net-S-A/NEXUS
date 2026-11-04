"""Zakładka „Aneksy” kontraktu — aneks z Generatora aneksów widać od
wygenerowania, a po podpisie wiadomo, skąd jest i jaki ma plik.

Render szablonów jest podmieniony (``_fake_render``). Baza wspólna
i nieczyszczona: asercje wyłącznie na własnych wierszach.
"""

from __future__ import annotations

from datetime import date
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


# ── „Umowy bieżące”: etykieta aneksu na wierszu umowy ────────────────────────


async def _register_row(app_client, headers, rid: int) -> dict:
    from app.models.b2b_generated_contract import B2BGeneratedContract

    async with AsyncSessionLocal() as db:
        number = (await db.get(B2BGeneratedContract, rid)).contract_number
    listed = await app_client.get(
        f"{BASE}/generated", headers=headers, params={"q": number}
    )
    assert listed.status_code == 200, listed.text
    [item] = [row for row in listed.json() if row["id"] == rid]
    return item


async def test_register_row_names_its_latest_annex_and_the_start_date_before_it(
    app_client, app_auth_headers
):
    """Aneks zmieniał datę startu w wierszu po cichu — wiersz nie mówił, że
    to data z niepodpisanego aneksu ani jaka była wcześniej."""
    from app.models.b2b_generated_contract import B2BGeneratedContract

    rid, contract_id = await _signed_parent(app_client)
    await _hourly(contract_id, "150")
    async with AsyncSessionLocal() as db:
        (await db.get(B2BGeneratedContract, rid)).start_date = date(2026, 11, 2)
        await db.commit()

    plain = await _register_row(app_client, app_auth_headers, rid)
    assert plain["latest_annex"] is None
    assert plain["annex_count"] == 0
    assert plain["start_date_before"] is None

    start_annex = await _create(
        app_client,
        app_auth_headers,
        "annex_start_date",
        rid,
        new_start_date="2026-11-16",
    )
    row = await _register_row(app_client, app_auth_headers, rid)
    assert row["start_date"] == "2026-11-16"
    assert row["start_date_before"] == "2026-11-02"
    assert row["start_date_annex_state"] == "waiting"
    assert row["annex_count"] == 1
    assert row["latest_annex"] == {
        "document_id": start_annex,
        "document_type": "annex_start_date",
        "state": "waiting",
        "effective_date": "2026-11-16",
    }

    rate_annex = await _create(
        app_client,
        app_auth_headers,
        "annex_rate_change",
        rid,
        effective_date="2026-12-01",
        rate_items=[{"rate": "165"}],
    )
    row = await _register_row(app_client, app_auth_headers, rid)
    assert row["annex_count"] == 2
    assert row["latest_annex"]["document_id"] == rate_annex
    # Data startu nadal pochodzi z aneksu daty, choć nowszy jest aneks stawki.
    assert row["start_date_before"] == "2026-11-02"

    cancelled = await app_client.post(
        f"{BASE}/documents/{rate_annex}/cancel",
        headers=app_auth_headers,
        json={"reason": "Zmiana ustaleń"},
    )
    assert cancelled.status_code == 200, cancelled.text
    row = await _register_row(app_client, app_auth_headers, rid)
    # Anulowany aneks nie jest etykietą i nie liczy się do „+N aneksów”.
    assert row["annex_count"] == 1
    assert row["latest_annex"]["document_id"] == start_annex
