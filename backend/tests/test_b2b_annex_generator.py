"""Generator aneksów (ticket 29.09.2026) — umowa spoza NEXUSA, rejestr
zmieniany przy wygenerowaniu (i cofany przy anulowaniu), wiele stawek.

Render szablonów jest podmieniony (``_fake_render`` z ``test_b2b_documents_api``)
— treść aneksów sprawdza ``test_b2b_document_templates.py``. Baza wspólna
i nieczyszczona: asercje wyłącznie na własnych wierszach.
"""

from __future__ import annotations

from datetime import date, timedelta
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
from tests.test_b2b_generated_contract_status import (
    _admin_user_id,
    _seed,
    _seed_linked_contract,
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


async def _external(app_client, headers, doc_type: str, **body):
    """Aneks do umowy spoza NEXUSA: bez umowy z rejestru, z kontraktem albo
    klientem w żądaniu (``contract_id`` / ``client_id`` w ``body``)."""
    values = body.pop("values", {})
    return await app_client.post(
        f"{BASE}/documents",
        headers=headers,
        json={
            "document_type": doc_type,
            "language": "pl",
            "parent_generated_contract_id": None,
            "values": _values(**values),
            **body,
        },
    )


async def _document(doc_id: int):
    from app.models.b2b_contract_document import B2BContractDocument

    async with AsyncSessionLocal() as db:
        return await db.get(B2BContractDocument, doc_id)


async def test_outside_nexus_annex_is_saved_with_its_contract(
    app_client, app_auth_headers
):
    """Do 13.10.2026 aneks do umowy spoza NEXUSA nie był zapisywany — nie
    było go w żadnej liście i podpis nie zmieniał kontraktu."""
    from app.models.contract import Contract

    contract_id, client_id = await _seed_linked_contract()
    resp = await _external(
        app_client,
        app_auth_headers,
        "annex_rate_change",
        contract_id=contract_id,
        values={"contract_number": "EXT-77/2025", "rate_items": [{"rate": "145"}]},
    )
    assert resp.status_code == 200, resp.text
    assert "X-Document-Saved" not in resp.headers
    doc = await _document(int(resp.headers["X-Document-Id"]))
    assert doc.parent_generated_contract_id is None
    assert doc.contract_id == contract_id
    # Klienta i osobę dokumentu bierze serwer z kontraktu, nie z żądania.
    assert doc.client_id == client_id
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
    assert doc.candidate_id == contract.candidate_id
    assert doc.render_payload["base"]["contract_number"] == "EXT-77/2025"

    listed = await app_client.get(
        f"{BASE}/documents",
        headers=app_auth_headers,
        params={"q": "EXT-77/2025"},
    )
    assert listed.status_code == 200, listed.text
    assert doc.id in {item["id"] for item in listed.json()}


async def test_outside_nexus_annex_without_contract_needs_a_client(
    app_client, app_auth_headers
):
    """„Bez kontraktu”: aneks zapisuje się przy kliencie, a podpis czeka na
    powiązanie — bez kontraktu nie zmieniłby niczego."""
    refused = await _external(
        app_client,
        app_auth_headers,
        "annex_start_date",
        values={"new_start_date": "2026-11-15"},
    )
    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"]["code"] == "document_fields_missing"
    assert refused.json()["detail"]["missing"] == ["Klient"]

    _, client_id = await _seed_linked_contract()
    saved = await _external(
        app_client,
        app_auth_headers,
        "annex_start_date",
        client_id=client_id,
        values={"new_start_date": "2026-11-15"},
    )
    assert saved.status_code == 200, saved.text
    doc_id = int(saved.headers["X-Document-Id"])
    doc = await _document(doc_id)
    assert doc.contract_id is None
    assert doc.client_id == client_id

    effects = await app_client.get(
        f"{BASE}/documents/{doc_id}/effects", headers=app_auth_headers
    )
    assert effects.status_code == 200, effects.text
    assert any(
        "nie jest powiązany z kontraktem" in b for b in effects.json()["blockers"]
    )
    signed = await app_client.post(
        f"{BASE}/documents/{doc_id}/confirm-signed", headers=app_auth_headers
    )
    assert signed.status_code == 409, signed.text
    assert (await _document(doc_id)).signature_status == "unsigned"


async def test_signed_outside_nexus_rate_annex_changes_the_contract(
    app_client, app_auth_headers
):
    from app.models.contract import Contract, RateUnit
    from app.models.contract_amendment import ContractAmendment, ContractAmendmentType

    contract_id, _ = await _seed_linked_contract()
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        contract.rate_candidate = Decimal("150")
        contract.rate_candidate_currency = "PLN"
        contract.rate_unit = RateUnit.hourly
        await db.commit()
    resp = await _external(
        app_client,
        app_auth_headers,
        "annex_rate_change",
        contract_id=contract_id,
        values={
            "effective_date": "2026-11-01",
            "paragraph": "6",
            "paragraph_section": "1",
            "rate_items": [{"rate": "165"}],
        },
    )
    assert resp.status_code == 200, resp.text
    doc_id = int(resp.headers["X-Document-Id"])
    # Wygenerowanie niczego w kontrakcie nie zmienia.
    async with AsyncSessionLocal() as db:
        assert (await db.get(Contract, contract_id)).rate_candidate == Decimal("150")

    signed = await app_client.post(
        f"{BASE}/documents/{doc_id}/confirm-signed", headers=app_auth_headers
    )
    assert signed.status_code == 200, signed.text
    async with AsyncSessionLocal() as db:
        amendment = await db.scalar(
            select(ContractAmendment).where(
                ContractAmendment.contract_id == contract_id,
                ContractAmendment.amendment_type == ContractAmendmentType.rate_change,
            )
        )
    assert amendment is not None
    assert amendment.effective_date == date(2026, 11, 1)
    doc = await _document(doc_id)
    assert doc.effect_summary["contract_id"] == contract_id
    assert doc.effect_summary["effective_date"] == "2026-11-01"


async def test_signed_outside_nexus_start_date_annex_moves_the_contract_start(
    app_client, app_auth_headers
):
    from app.models.contract import Contract

    contract_id, _ = await _seed_linked_contract()
    resp = await _external(
        app_client,
        app_auth_headers,
        "annex_start_date",
        contract_id=contract_id,
        values={"new_start_date": "2026-11-16"},
    )
    assert resp.status_code == 200, resp.text
    doc_id = int(resp.headers["X-Document-Id"])
    signed = await app_client.post(
        f"{BASE}/documents/{doc_id}/confirm-signed", headers=app_auth_headers
    )
    assert signed.status_code == 200, signed.text
    async with AsyncSessionLocal() as db:
        assert (await db.get(Contract, contract_id)).start_date == date(2026, 11, 16)


async def test_annex_refuses_a_void_or_wrong_type_contract(
    app_client, app_auth_headers
):
    from app.models.contract import Contract, ContractStatus, ContractType

    void_id, _ = await _seed_linked_contract()
    employment_id, _ = await _seed_linked_contract()
    async with AsyncSessionLocal() as db:
        (await db.get(Contract, void_id)).status = ContractStatus.void
        (await db.get(Contract, employment_id)).contract_type = ContractType.uop
        await db.commit()
    for contract_id in (void_id, employment_id):
        resp = await _external(
            app_client,
            app_auth_headers,
            "annex_start_date",
            contract_id=contract_id,
            values={"new_start_date": "2026-11-16"},
        )
        assert resp.status_code == 422, resp.text
    missing = await _external(
        app_client,
        app_auth_headers,
        "annex_start_date",
        contract_id=2_000_000_000,
        values={"new_start_date": "2026-11-16"},
    )
    assert missing.status_code == 404, missing.text


async def test_delivery_lead_cannot_attach_an_annex_outside_the_portfolio(
    app_client, app_auth_headers
):
    from app.models.team_structure import DeliveryLeadClientAssignment
    from tests.test_b2b_generator_rate_visibility import _seed_user

    own_contract, own_client = await _seed_linked_contract()
    other_contract, _ = await _seed_linked_contract()
    dl_headers, dl_id = await _seed_user(app_client, "delivery_lead")
    async with AsyncSessionLocal() as db:
        db.add(
            DeliveryLeadClientAssignment(
                delivery_lead_user_id=dl_id, client_id=own_client
            )
        )
        await db.commit()

    refused = await _external(
        app_client,
        dl_headers,
        "annex_start_date",
        contract_id=other_contract,
        values={"new_start_date": "2026-11-16"},
    )
    assert refused.status_code == 403, refused.text
    allowed = await _external(
        app_client,
        dl_headers,
        "annex_start_date",
        contract_id=own_contract,
        values={"new_start_date": "2026-11-16"},
    )
    assert allowed.status_code == 200, allowed.text


async def _unlinked_row(app_client, *, contract_id: int, client_id: int) -> int:
    """Umowa w rejestrze BEZ kontraktu (jak wiersz z Excela działu), ale
    z osobą i klientem kontraktu."""
    from app.models.b2b_generated_contract import B2BGeneratedContract
    from app.models.contract import Contract

    admin_id = await _admin_user_id(app_client)
    rid, _number = await _seed(admin_id, signature_status="signed_both")
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        row = await db.get(B2BGeneratedContract, rid)
        row.candidate_id = contract.candidate_id
        row.client_id = client_id
        row.template_version = "2026"
        await db.commit()
    return rid


async def test_annex_links_an_unlinked_register_row_to_the_only_live_contract(
    app_client, app_auth_headers
):
    """Aneks do umowy z Excela zmieniał tylko rejestr — kontrakt osoby
    istniał obok, bez powiązania. Reguła jak przy zakończeniu współpracy."""
    contract_id, client_id = await _seed_linked_contract()
    rid = await _unlinked_row(app_client, contract_id=contract_id, client_id=client_id)
    doc_id = await _create(
        app_client,
        app_auth_headers,
        "annex_start_date",
        rid,
        new_start_date="2026-11-15",
    )
    assert (await _row(rid)).contract_id == contract_id
    assert (await _document(doc_id)).contract_id == contract_id


async def test_unlinked_row_with_several_live_contracts_links_only_the_picked_one(
    app_client, app_auth_headers
):
    from app.models.contract import Contract, ContractStatus

    first_id, client_id = await _seed_linked_contract()
    stranger_id, _ = await _seed_linked_contract()
    async with AsyncSessionLocal() as db:
        first = await db.get(Contract, first_id)
        second = Contract(
            candidate_id=first.candidate_id,
            client_id=client_id,
            status=ContractStatus.active,
            start_date=date(2026, 6, 1),
        )
        db.add(second)
        await db.commit()
        await db.refresh(second)
        second_id = second.id
    rid = await _unlinked_row(app_client, contract_id=first_id, client_id=client_id)

    # Dwa trwające kontrakty: system nie zgaduje, aneks zostaje bez kontraktu.
    doc_id = await _create(
        app_client,
        app_auth_headers,
        "annex_start_date",
        rid,
        new_start_date="2026-11-15",
    )
    assert (await _row(rid)).contract_id is None
    assert (await _document(doc_id)).contract_id is None

    def body(contract_id: int) -> dict:
        return {
            "document_type": "annex_start_date",
            "language": "pl",
            "parent_generated_contract_id": rid,
            "contract_id": contract_id,
            "values": _values(new_start_date="2026-11-20"),
        }

    foreign = await app_client.post(
        f"{BASE}/documents", headers=app_auth_headers, json=body(stranger_id)
    )
    assert foreign.status_code == 422, foreign.text
    assert (await _row(rid)).contract_id is None

    picked = await app_client.post(
        f"{BASE}/documents", headers=app_auth_headers, json=body(second_id)
    )
    assert picked.status_code == 200, picked.text
    assert (await _row(rid)).contract_id == second_id
    assert (await _document(int(picked.headers["X-Document-Id"]))).contract_id == (
        second_id
    )


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


async def test_cancelling_both_annexes_restores_the_state_before_them(
    app_client, app_auth_headers
):
    """A, potem B; anulowanie A, potem B — wiersz wraca do stanu sprzed
    aneksów, nie do wartości anulowanego A."""
    rid, _ = await _signed_parent(app_client)
    before = (await _row(rid)).start_date
    first = await _create(
        app_client,
        app_auth_headers,
        "annex_start_date",
        rid,
        new_start_date="2026-11-15",
    )
    second = await _create(
        app_client,
        app_auth_headers,
        "annex_start_date",
        rid,
        new_start_date="2026-12-01",
    )
    for doc_id in (first, second):
        resp = await app_client.post(
            f"{BASE}/documents/{doc_id}/cancel",
            headers=app_auth_headers,
            json={"reason": "Nie doszło do skutku"},
        )
        assert resp.status_code == 200, resp.text
    assert (await _row(rid)).start_date == before


async def test_correcting_an_older_annex_does_not_override_a_newer_one(
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
    fixed = await app_client.post(
        f"{BASE}/documents/{first}/rerender",
        headers=app_auth_headers,
        json={
            "document_type": "annex_start_date",
            "parent_generated_contract_id": rid,
            "values": _values(new_start_date="2026-11-20"),
        },
    )
    assert fixed.status_code == 200, fixed.text
    assert (await _row(rid)).start_date == date(2026, 12, 1)
    cancel = await app_client.post(
        f"{BASE}/documents/{first}/cancel",
        headers=app_auth_headers,
        json={"reason": "Pomyłka"},
    )
    assert cancel.status_code == 200, cancel.text
    assert (await _row(rid)).start_date == date(2026, 12, 1)


async def test_legacy_rate_annex_form_keeps_its_own_rate(app_client, app_auth_headers):
    """„Popraw” aneksu zapisanego przed generatorem (``new_rate``) pokazuje
    jego stawkę, a nie bieżącą stawkę z rejestru."""
    from app.models.b2b_contract_document import B2BContractDocument

    rid, _ = await _signed_parent(app_client)
    doc_id = await _create(
        app_client,
        app_auth_headers,
        "annex_rate_change",
        rid,
        rate_items=[{"rate": "150"}],
    )
    async with AsyncSessionLocal() as db:
        doc = await db.get(B2BContractDocument, doc_id)
        payload = dict(doc.render_payload)
        values = dict(payload["values"])
        values.pop("rate_items")
        values.update(new_rate=180, currency="PLN")
        doc.render_payload = {**payload, "values": values}
        await db.commit()
    form = await app_client.get(
        f"{BASE}/documents/{doc_id}/form", headers=app_auth_headers
    )
    assert form.status_code == 200, form.text
    assert form.json()["values"]["rate_items"][0]["rate"] == 180


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


# ── dla kogo jest aneks: jedno wyszukiwanie osoby ────────────────────────────


async def _subjects(app_client, headers, **params) -> list[dict]:
    resp = await app_client.get(
        f"{BASE}/documents/subjects", headers=headers, params=params
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _lastname(contract_id: int) -> str:
    from app.models.candidate import Candidate
    from app.models.contract import Contract

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        return (await db.get(Candidate, contract.candidate_id)).lastname


async def test_subjects_offer_a_contract_without_a_register_agreement(
    app_client, app_auth_headers
):
    contract_id, client_id = await _seed_linked_contract()
    lastname = await _lastname(contract_id)

    found = await _subjects(
        app_client, app_auth_headers, document_type="annex_rate_change", q=lastname
    )
    [subject] = [s for s in found if s["contract_id"] == contract_id]
    assert subject["kind"] == "contract"
    assert subject["parent_generated_contract_id"] is None
    assert subject["client_id"] == client_id
    assert subject["person_name"].endswith(lastname)
    # Wybór podmiotu nie jest wglądem w stawki.
    assert not {k for k in subject if "rate" in k or "amount" in k}

    # Typ bez ścieżki „umowa spoza NEXUSA” dostaje wyłącznie umowy z rejestru.
    only_agreements = await _subjects(
        app_client, app_auth_headers, document_type="annex_subcontractor", q=lastname
    )
    assert all(s["kind"] == "agreement" for s in only_agreements)
    # Fraza krótsza niż dwa znaki nie przeszukuje całej bazy.
    assert (
        await _subjects(
            app_client, app_auth_headers, document_type="annex_rate_change", q="K"
        )
        == []
    )


async def test_subjects_show_a_linked_contract_only_under_its_agreement(
    app_client, app_auth_headers
):
    rid, contract_id = await _signed_parent(app_client)
    number = (await _row(rid)).contract_number
    lastname = await _lastname(contract_id)

    by_number = await _subjects(
        app_client, app_auth_headers, document_type="annex_start_date", q=number
    )
    [agreement] = [s for s in by_number if s["parent_generated_contract_id"] == rid]
    assert agreement["kind"] == "agreement"
    assert agreement["contract_id"] == contract_id
    assert agreement["contract_options"] == []

    # Kontrakt z własną umową w rejestrze nie jest „umową spoza NEXUSA”.
    by_person = await _subjects(
        app_client, app_auth_headers, document_type="annex_start_date", q=lastname
    )
    assert not [
        s
        for s in by_person
        if s["kind"] == "contract" and s["contract_id"] == contract_id
    ]

    # Wejście z modułu Kontrakty: podmiot tego jednego kontraktu.
    from_contract = await _subjects(
        app_client,
        app_auth_headers,
        document_type="annex_start_date",
        contract_id=contract_id,
    )
    assert [s["parent_generated_contract_id"] for s in from_contract] == [rid]


async def test_subjects_pair_an_unlinked_agreement_with_its_live_contract(
    app_client, app_auth_headers
):
    contract_id, client_id = await _seed_linked_contract()
    rid = await _unlinked_row(app_client, contract_id=contract_id, client_id=client_id)

    found = await _subjects(
        app_client,
        app_auth_headers,
        document_type="annex_rate_change",
        contract_id=contract_id,
    )
    [agreement] = found
    assert agreement["parent_generated_contract_id"] == rid
    assert agreement["contract_id"] is None
    assert [o["contract_id"] for o in agreement["contract_options"]] == [contract_id]


# ── rejestr aneksów: lista, przywrócenie, powiązanie, historia ───────────────


async def _listed(app_client, headers, doc_id: int, **params) -> dict | None:
    resp = await app_client.get(f"{BASE}/documents", headers=headers, params=params)
    assert resp.status_code == 200, resp.text
    return next((item for item in resp.json() if item["id"] == doc_id), None)


async def test_register_row_says_for_whom_what_and_since_when(
    app_client, app_auth_headers
):
    from app.core.scheduling import business_today
    from app.models.contract import Contract, RateUnit
    from tests.test_b2b_generator_rate_visibility import _seed_user

    contract_id, client_id = await _seed_linked_contract()
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        contract.rate_candidate = Decimal("140")
        contract.rate_candidate_currency = "PLN"
        contract.rate_unit = RateUnit.hourly
        await db.commit()
    lastname = await _lastname(contract_id)
    nip = "5213900011"
    in_a_month = (business_today() + timedelta(days=30)).isoformat()
    resp = await _external(
        app_client,
        app_auth_headers,
        "annex_rate_change",
        contract_id=contract_id,
        values={
            "effective_date": in_a_month,
            "partner_nip": nip,
            "rate_items": [{"rate": "145"}],
        },
    )
    assert resp.status_code == 200, resp.text
    doc_id = int(resp.headers["X-Document-Id"])

    # Szukanie po osobie z kontraktu i po NIP-ie, tylko w rodzinie aneksów.
    item = await _listed(
        app_client, app_auth_headers, doc_id, family="annex", q=lastname
    )
    assert item is not None
    assert await _listed(app_client, app_auth_headers, doc_id, q="521-390-00-11")
    assert (
        await _listed(app_client, app_auth_headers, doc_id, family="termination", q=nip)
        is None
    )
    assert item["state"] == "waiting"
    assert item["effective_date"] == in_a_month
    assert item["contract_id"] == contract_id
    assert item["client_id"] == client_id
    assert item["external"] is True
    assert item["partner_nip"] == nip
    assert item["person_name"].endswith(lastname)
    assert item["change"]["kind"] == "rate"
    assert [i["rate"] for i in item["change"]["items"]] == [145.0]
    assert item["can_confirm_signed"] is True
    assert item["can_link_contract"] is False

    unknown = await app_client.get(
        f"{BASE}/documents", headers=app_auth_headers, params={"family": "wszystko"}
    )
    assert unknown.status_code == 422, unknown.text

    # Rekruter, który nie jest autorem ani prowadzącym, widzi aneks bez kwot.
    recruiter_headers, _ = await _seed_user(app_client, "recruiter")
    seen = await _listed(app_client, recruiter_headers, doc_id, family="annex", q=nip)
    assert seen is not None
    assert seen["change"] == {"kind": "rate", "hidden": True}

    signed = await app_client.post(
        f"{BASE}/documents/{doc_id}/confirm-signed", headers=app_auth_headers
    )
    # Aneks podpisany z datą w przyszłości jeszcze nie obowiązuje.
    assert signed.status_code == 200, signed.text
    assert signed.json()["state"] == "signed_pending"


async def test_annex_without_contract_waits_until_it_is_linked(
    app_client, app_auth_headers
):
    from app.models.contract import Contract

    contract_id, client_id = await _seed_linked_contract()
    saved = await _external(
        app_client,
        app_auth_headers,
        "annex_start_date",
        client_id=client_id,
        values={"contract_number": "BK-1/2025", "new_start_date": "2026-11-16"},
    )
    assert saved.status_code == 200, saved.text
    doc_id = int(saved.headers["X-Document-Id"])

    item = await _listed(app_client, app_auth_headers, doc_id, status="no_contract")
    assert item is not None
    assert item["contract_id"] is None
    assert item["can_confirm_signed"] is False
    assert item["can_link_contract"] is True

    linked = await app_client.post(
        f"{BASE}/documents/{doc_id}/link-contract",
        headers=app_auth_headers,
        json={"contract_id": contract_id},
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["contract_id"] == contract_id
    assert linked.json()["can_confirm_signed"] is True
    assert (
        await _listed(app_client, app_auth_headers, doc_id, status="no_contract")
        is None
    )
    again = await app_client.post(
        f"{BASE}/documents/{doc_id}/link-contract",
        headers=app_auth_headers,
        json={"contract_id": contract_id},
    )
    assert again.status_code == 409, again.text

    signed = await app_client.post(
        f"{BASE}/documents/{doc_id}/confirm-signed", headers=app_auth_headers
    )
    assert signed.status_code == 200, signed.text
    async with AsyncSessionLocal() as db:
        assert (await db.get(Contract, contract_id)).start_date == date(2026, 11, 16)
    after = await app_client.post(
        f"{BASE}/documents/{doc_id}/link-contract",
        headers=app_auth_headers,
        json={"contract_id": contract_id},
    )
    assert after.status_code == 409, after.text


async def test_restore_brings_a_cancelled_annex_back_without_displacing_a_newer_one(
    app_client, app_auth_headers
):
    rid, _ = await _signed_parent(app_client)
    older = await _create(
        app_client,
        app_auth_headers,
        "annex_start_date",
        rid,
        new_start_date="2026-11-15",
    )
    newer = await _create(
        app_client,
        app_auth_headers,
        "annex_start_date",
        rid,
        new_start_date="2026-11-20",
    )

    async def post(doc_id: int, action: str, **json):
        return await app_client.post(
            f"{BASE}/documents/{doc_id}/{action}", headers=app_auth_headers, **json
        )

    not_cancelled = await post(older, "restore")
    assert not_cancelled.status_code == 409, not_cancelled.text

    cancelled = await post(older, "cancel", json={"reason": "Partner nie podpisał"})
    assert cancelled.status_code == 200, cancelled.text
    restored = await post(older, "restore")
    assert restored.status_code == 200, restored.text
    assert restored.json()["status"] == "issued"
    assert restored.json()["state"] == "waiting"
    assert restored.json()["cancelled_reason"] is None
    # Późniejszy aneks nadal wygrywa w wierszu umowy.
    assert (await _row(rid)).start_date == date(2026, 11, 20)

    # Jedyny aktywny aneks po przywróceniu wraca do wiersza.
    assert (
        await post(newer, "cancel", json={"reason": "Zmiana ustaleń"})
    ).status_code == 200
    assert (await _row(rid)).start_date == date(2026, 11, 15)

    history = await app_client.get(
        f"{BASE}/documents/{older}/history", headers=app_auth_headers
    )
    assert history.status_code == 200, history.text
    entries = history.json()
    assert [e["action"] for e in entries] == ["generated", "cancelled", "restored"]
    assert entries[1]["note"] == "Partner nie podpisał"
    assert entries[0]["note"] is None
    assert all(set(e) == {"action", "at", "by_name", "note"} for e in entries)
