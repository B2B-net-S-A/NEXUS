"""Generator aneksów (ticket 29.09.2026) — umowa spoza NEXUSA, rejestr
zmieniany przy wygenerowaniu (i cofany przy anulowaniu), wiele stawek.

Render szablonów jest podmieniony (``_fake_render`` z ``test_b2b_documents_api``)
— treść aneksów sprawdza ``test_b2b_document_templates.py``. Baza wspólna
i nieczyszczona: asercje wyłącznie na własnych wierszach.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.services.b2b_documents.registry import TYPES, rate_items_problems
from tests.test_b2b_documents_api import (  # noqa: F401
    BASE,
    _create,
    _fake_render,
    _signed_parent,
    _values,
)

# ── czyste reguły ────────────────────────────────────────────────────────────


def test_generator_types_accept_contracts_outside_nexus():
    keys = {k for k, t in TYPES.items() if t.allows_external}
    assert keys == {"annex_party_data", "annex_start_date", "annex_rate_change"}
    for key in keys:
        assert TYPES[key].languages == ("pl",)
        assert TYPES[key].uses_refs is False


def test_several_rates_need_a_date_or_a_client():
    assert rate_items_problems([{"rate": 135}]) == []
    assert (
        rate_items_problems([{"rate": 135}, {"rate": 140, "from": "2027-01-01"}]) == []
    )
    assert rate_items_problems([{"rate": 135}, {"rate": 150, "client_id": 3}]) == []
    problems = rate_items_problems([{"rate": 135}, {"rate": 140}])
    assert problems and "daty „od” albo klienta" in problems[0]


def test_rate_item_period_must_not_be_reversed():
    problems = rate_items_problems(
        [{"rate": 135, "from": "2026-12-01", "to": "2026-11-01"}]
    )
    assert any("wcześniejsza niż „od”" in p for p in problems)
    assert any("podaj stawkę" in p for p in rate_items_problems([{"rate": ""}]))


# ── umowa spoza NEXUSA ───────────────────────────────────────────────────────


async def test_outside_nexus_annex_downloads_without_saving(
    app_client, app_auth_headers
):
    from app.models.b2b_contract_document import B2BContractDocument

    number = "EXT-77/2025"
    resp = await app_client.post(
        f"{BASE}/documents",
        headers=app_auth_headers,
        json={
            "document_type": "annex_rate_change",
            "language": "pl",
            "parent_generated_contract_id": None,
            "values": _values(
                contract_number=number,
                paragraph="6",
                paragraph_section="1",
                rate_items=[{"rate": "145"}],
            ),
        },
    )
    assert resp.status_code == 200, resp.text
    assert "X-Document-Id" not in resp.headers
    assert resp.headers["X-Document-Saved"] == "0"
    async with AsyncSessionLocal() as db:
        saved = await db.scalar(
            select(B2BContractDocument.id).where(
                B2BContractDocument.render_payload["base"]["contract_number"].astext
                == number
            )
        )
    assert saved is None


async def test_outside_nexus_needs_contract_data(app_client, app_auth_headers):
    values = _values(rate_items=[{"rate": "145"}])
    values.pop("contract_number")
    resp = await app_client.post(
        f"{BASE}/documents",
        headers=app_auth_headers,
        json={"document_type": "annex_rate_change", "values": values},
    )
    assert resp.status_code == 422, resp.text
    assert "Numer umowy" in resp.json()["detail"]["missing"]


async def test_other_documents_still_need_a_register_contract(
    app_client, app_auth_headers
):
    resp = await app_client.post(
        f"{BASE}/documents",
        headers=app_auth_headers,
        json={
            "document_type": "termination_agreement",
            "values": _values(
                termination_date="2026-10-31", last_service_date="2026-10-31"
            ),
        },
    )
    assert resp.status_code == 422, resp.text


# ── rejestr zmienia się przy wygenerowaniu ───────────────────────────────────


async def _row(rid: int):
    from app.models.b2b_generated_contract import B2BGeneratedContract

    async with AsyncSessionLocal() as db:
        return await db.get(B2BGeneratedContract, rid)


async def test_start_date_annex_updates_register_and_cancel_restores(
    app_client, app_auth_headers
):
    rid, _ = await _signed_parent(app_client)
    before = (await _row(rid)).start_date
    doc_id = await _create(
        app_client,
        app_auth_headers,
        "annex_start_date",
        rid,
        new_start_date="2026-11-15",
    )
    assert (await _row(rid)).start_date == date(2026, 11, 15)

    cancel = await app_client.post(
        f"{BASE}/documents/{doc_id}/cancel",
        headers=app_auth_headers,
        json={"reason": "Partner nie podpisał"},
    )
    assert cancel.status_code == 200, cancel.text
    assert (await _row(rid)).start_date == before


async def test_later_annex_wins_over_cancelling_an_earlier_one(
    app_client, app_auth_headers
):
    rid, _ = await _signed_parent(app_client)
    first = await _create(
        app_client,
        app_auth_headers,
        "annex_start_date",
        rid,
        new_start_date="2026-11-15",
    )
    await _create(
        app_client,
        app_auth_headers,
        "annex_start_date",
        rid,
        new_start_date="2026-12-01",
    )
    deleted = await app_client.delete(
        f"{BASE}/documents/{first}", headers=app_auth_headers
    )
    assert deleted.status_code == 204, deleted.text
    assert (await _row(rid)).start_date == date(2026, 12, 1)


async def test_party_data_annex_updates_company_and_nip(app_client, app_auth_headers):
    rid, _ = await _signed_parent(app_client)
    doc_id = await _create(
        app_client,
        app_auth_headers,
        "annex_party_data",
        rid,
        partner_home_address="ul. Domowa 1",
        id_document="ABC123456",
        new_legal_name="Anna Testowa Consulting",
        new_business_address="ul. Firmowa 2, Warszawa",
        new_nip="527-010-33-91",
        new_regon="012345678",
    )
    row = await _row(rid)
    assert row.partner_legal_name == "Anna Testowa Consulting"
    assert row.partner_nip == "5270103391"
    assert row.partner_entity_type == "sole_trader"
    deleted = await app_client.delete(
        f"{BASE}/documents/{doc_id}", headers=app_auth_headers
    )
    assert deleted.status_code == 204, deleted.text
    assert (await _row(rid)).partner_legal_name != "Anna Testowa Consulting"


async def test_rate_annex_shows_rates_on_the_register_row(app_client, app_auth_headers):
    from app.models.contract import Contract

    rid, contract_id = await _signed_parent(app_client)
    async with AsyncSessionLocal() as db:
        client_id = (await db.get(Contract, contract_id)).client_id
    await _create(
        app_client,
        app_auth_headers,
        "annex_rate_change",
        rid,
        paragraph="6",
        paragraph_section="1",
        rate_items=[
            {"rate": "150", "from": "2026-11-01", "to": "2026-12-31"},
            {"rate": "160,50", "from": "2027-01-01", "client_id": client_id},
        ],
    )
    row = await _row(rid)
    items = row.annex_rates["items"]
    assert [i["rate"] for i in items] == [150.0, 160.5]
    assert items[1]["client_id"] == client_id
    assert items[1]["client_name"]

    listed = await app_client.get(
        f"{BASE}/generated", headers=app_auth_headers, params={"q": row.contract_number}
    )
    assert listed.status_code == 200, listed.text
    [item] = [r for r in listed.json() if r["id"] == rid]
    assert [i["rate"] for i in item["annex_rates"]] == [150.0, 160.5]


async def test_rate_client_must_exist_in_nexus(app_client, app_auth_headers):
    rid, _ = await _signed_parent(app_client)
    resp = await app_client.post(
        f"{BASE}/documents",
        headers=app_auth_headers,
        json={
            "document_type": "annex_rate_change",
            "parent_generated_contract_id": rid,
            "values": _values(rate_items=[{"rate": "150", "client_id": 987654321}]),
        },
    )
    assert resp.status_code == 422, resp.text


async def test_client_name_comes_from_nexus_not_from_the_request(
    app_client, app_auth_headers
):
    from app.models.b2b_contract_document import B2BContractDocument
    from app.models.contract import Contract

    rid, contract_id = await _signed_parent(app_client)
    async with AsyncSessionLocal() as db:
        client_id = (await db.get(Contract, contract_id)).client_id
    doc_id = await _create(
        app_client,
        app_auth_headers,
        "annex_rate_change",
        rid,
        rate_items=[
            {"rate": "150", "client_id": client_id, "client_name": "Wymyślony"}
        ],
    )
    async with AsyncSessionLocal() as db:
        doc = await db.get(B2BContractDocument, doc_id)
    [item] = doc.render_payload["values"]["rate_items"]
    assert item["client_name"] != "Wymyślony"


# ── podpis: kontrakt dopiero po „Oznacz jako podpisany” ──────────────────────


async def test_progressive_rates_become_schedule_steps_on_signature(
    app_client, app_auth_headers
):
    from app.models.client import Client
    from app.models.contract import Contract, RateUnit
    from app.models.contract_amendment import ContractAmendment, ContractAmendmentType

    rid, contract_id = await _signed_parent(app_client)
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        contract.rate_candidate = Decimal("140")
        contract.rate_candidate_currency = "PLN"
        contract.rate_unit = RateUnit.hourly
        other = Client(name="Inny Klient Aneksu")
        db.add(other)
        await db.commit()
        await db.refresh(other)
        other_id = other.id
    doc_id = await _create(
        app_client,
        app_auth_headers,
        "annex_rate_change",
        rid,
        rate_items=[
            {"rate": "150", "from": "2026-11-01"},
            {"rate": "160", "from": "2027-01-01"},
            {"rate": "200", "client_id": other_id},
        ],
    )
    # Generowanie nie rusza kontraktu.
    async with AsyncSessionLocal() as db:
        assert not (
            await db.scalars(
                select(ContractAmendment.id).where(
                    ContractAmendment.contract_id == contract_id,
                    ContractAmendment.amendment_type
                    == ContractAmendmentType.rate_change,
                )
            )
        ).all()

    effects = await app_client.get(
        f"{BASE}/documents/{doc_id}/effects", headers=app_auth_headers
    )
    assert effects.status_code == 200, effects.text
    body = effects.json()
    assert len([c for c in body["changes"] if "nowy krok" in c]) == 2
    assert any("Inny Klient Aneksu" in w for w in body["warnings"])

    signed = await app_client.post(
        f"{BASE}/documents/{doc_id}/confirm-signed", headers=app_auth_headers
    )
    assert signed.status_code == 200, signed.text
    async with AsyncSessionLocal() as db:
        amendments = (
            await db.scalars(
                select(ContractAmendment)
                .where(
                    ContractAmendment.contract_id == contract_id,
                    ContractAmendment.amendment_type
                    == ContractAmendmentType.rate_change,
                )
                .order_by(ContractAmendment.effective_date)
            )
        ).all()
    assert [a.effective_date for a in amendments] == [
        date(2026, 11, 1),
        date(2027, 1, 1),
    ]
    assert [Decimal(str(a.new_values["rate_candidate"])) for a in amendments] == [
        Decimal("150"),
        Decimal("160"),
    ]


# ── prefill ──────────────────────────────────────────────────────────────────


async def test_prefill_from_register_row(app_client, app_auth_headers):
    from app.models.b2b_generated_contract import B2BGeneratedContract

    rid, _ = await _signed_parent(app_client)
    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, rid)
        row.start_date = date(2026, 10, 1)
        row.signing_date = date(2026, 9, 1)
        row.render_payload = {**(row.render_payload or {}), "rate_candidate": 150}
        await db.commit()
        number = row.contract_number
    resp = await app_client.get(
        f"{BASE}/documents/prefill",
        headers=app_auth_headers,
        params={
            "document_type": "annex_start_date",
            "parent_generated_contract_id": rid,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["values"]["contract_number"] == number
    assert body["values"]["contract_signing_date"] == "2026-09-01"
    assert body["values"]["current_start_date"] == "2026-10-01"
    assert body["values"]["partner_variant"] == "sole_trader"
    # Umowa ze wzoru 2026 w NEXUSIE: § 13 ust. 2 (JDG), § 14 ust. 2 (spółka).
    assert body["paragraph_defaults"] == {
        "sole_trader": ["13", "2"],
        "company": ["14", "2"],
    }
    assert body["values"]["paragraph"] == "13"

    rate = await app_client.get(
        f"{BASE}/documents/prefill",
        headers=app_auth_headers,
        params={
            "document_type": "annex_rate_change",
            "parent_generated_contract_id": rid,
        },
    )
    assert rate.status_code == 200, rate.text
    [item] = rate.json()["values"]["rate_items"]
    assert float(item["rate"]) == 150.0
    assert item["client_id"] is not None


async def test_prefill_outside_nexus_uses_ticket_paragraphs(
    app_client, app_auth_headers
):
    resp = await app_client.get(
        f"{BASE}/documents/prefill",
        headers=app_auth_headers,
        params={"document_type": "annex_start_date"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["paragraph_defaults"] == {
        "sole_trader": ["12", "2"],
        "company": ["13", "2"],
    }
    assert body["values"]["paragraph"] == "12"
    assert body["values"]["partner_variant"] == "sole_trader"
