"""Runda 10 audytu (27.09.2026) — dokumenty pochodne umowy B2B (B2BDOC).

R10-N14-1  cofnięcie wypowiedzenia kasuje migawkę zakończenia wiersza,
R10-N14-2  porozumienie: koniec projektu = ostatni dzień świadczenia usług,
           umowa w rejestrze kończy się dniem rozwiązania,
R10-N14-3  wypowiedzenie Partnera do umowy bez kontraktu szuka trwającego
           kontraktu osoby u klienta umowy,
R10-N14-4  podgląd aneksu daty startu bez daty nie kończy się 500,
R10-N14-5  kwota od miliona: słownik liczb i walidacja 422,
R10-N14-6  opis skutku cofnięcia wypowiedzenia nie obiecuje zmiany kontraktu,
R10-N14-7  aneks stawki potwierdzają admin, Finanse i DL z portfela,
R10-N14-8  podpowiedzi formularza biorą dane firmy z kolumn po aneksie danych.

Baza wspólna i nieczyszczona — asercje wyłącznie na własnych wierszach.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.services.b2b_contract_generator.number_words import (
    liczba_slownie,
    number_to_words_en,
    rate_in_words,
)
from app.services.b2b_documents.context import build_document_context
from app.services.b2b_documents.effects import project_end_of
from app.services.b2b_documents.registry import TYPES, invalid_values
from app.services.b2b_documents.render import render_html, template_key

# ── czyste reguły ────────────────────────────────────────────────────────────


def test_number_words_handle_millions():
    assert liczba_slownie(1_000_000) == "milion"
    assert liczba_slownie(2_000_000) == "dwa miliony"
    assert liczba_slownie(5_250_000) == "pięć milionów dwieście pięćdziesiąt tysięcy"
    assert number_to_words_en(1_500_000) == "one million five hundred thousand"
    assert rate_in_words(1_000_000, "pl", "PLN") == "milion złotych"
    # Dotychczasowe kwoty bez zmian.
    assert liczba_slownie(1000) == "tysiąc"
    assert liczba_slownie(165) == "sto sześćdziesiąt pięć"


def test_money_of_a_million_is_rejected_before_render():
    doc_type = TYPES["annex_rate_change"]
    problems = invalid_values(doc_type, {"new_rate": "1000000"})
    assert problems and "mniejsza niż 1 000 000" in problems[0]
    assert invalid_values(doc_type, {"new_rate": "165.50"}) == []


def test_last_service_after_termination_is_rejected():
    doc_type = TYPES["termination_agreement"]
    problems = invalid_values(
        doc_type,
        {"termination_date": "2026-10-31", "last_service_date": "2026-11-15"},
    )
    assert any("Ostatni dzień świadczenia" in p for p in problems)
    assert (
        invalid_values(
            doc_type,
            {"termination_date": "2026-10-31", "last_service_date": "2026-10-15"},
        )
        == []
    )


def test_project_end_is_the_last_service_day():
    when = date(2026, 10, 31)
    assert project_end_of({"last_service_date": "2026-10-15"}, when) == date(
        2026, 10, 15
    )
    assert project_end_of({}, when) == when
    # Dokument sprzed walidacji: data usług po rozwiązaniu liczy się jako
    # rozwiązanie.
    assert project_end_of({"last_service_date": "2026-11-15"}, when) == when


def test_start_date_annex_preview_without_a_date_renders():
    doc_type = TYPES["annex_start_date"]
    context = build_document_context(
        doc_type,
        {"document_date": "2026-09-27", "gender": "m", "partner_name": "X"},
        language="pl",
        base=None,
        refs=None,
    )
    assert "new_start_clause" in context["doc"]
    html = render_html(template_key("annex_start_date", "pl"), context)
    assert "…" in html


def test_withdrawal_effect_label_does_not_promise_a_contract_change():
    label = TYPES["notice_withdrawal"].effect_label
    assert "Kontrakt wróci" not in label
    assert "Cofnij zakończenie" in label


# ── API ──────────────────────────────────────────────────────────────────────


async def _row(rid: int):
    from app.core.database import AsyncSessionLocal
    from app.models.b2b_generated_contract import B2BGeneratedContract

    async with AsyncSessionLocal() as db:
        return await db.get(B2BGeneratedContract, rid)


async def test_withdrawal_clears_the_termination_snapshot(app_client, app_auth_headers):
    """R10-N14-1: po cofnięciu wypowiedzenia powrót po przerwie nie zamyka
    umowy ponownie z migawki."""
    from app.core.database import AsyncSessionLocal
    from app.models.contract import Contract
    from app.services.contract_termination_sync import (
        on_contract_returned_after_break,
    )
    from tests.test_b2b_documents_api import BASE, _create
    from tests.test_b2b_documents_api import _fake_render  # noqa: F401
    from tests.test_b2b_documents_round6 import _project_ended_earlier

    rid, contract_id = await _project_ended_earlier(app_client)
    notice = await app_client.post(
        f"{BASE}/documents/partner-notice",
        headers=app_auth_headers,
        json={
            "parent_generated_contract_id": rid,
            "delivered_on": "2026-07-10",
            "termination_date": "2026-08-31",
        },
    )
    assert notice.status_code == 200, notice.text
    row = await _row(rid)
    assert row.contract_status == "closed"
    assert row.termination_restore is not None

    doc_id = await _create(
        app_client,
        app_auth_headers,
        "notice_withdrawal",
        rid,
        notice_delivery_date="2026-07-10",
    )
    signed = await app_client.post(
        f"{BASE}/documents/{doc_id}/confirm-signed", headers=app_auth_headers
    )
    assert signed.status_code == 200, signed.text
    row = await _row(rid)
    assert row.contract_status == "active"
    assert row.termination_restore is None

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        await on_contract_returned_after_break(db, contract, actor_id=None)
        await db.commit()
    row = await _row(rid)
    assert row.contract_status == "active"
    assert row.termination_mode is None


async def test_agreement_ends_the_project_on_the_last_service_day(
    app_client, app_auth_headers
):
    """R10-N14-2: daty minione — kontrakt kończy się dniem usług, umowa
    w rejestrze dniem rozwiązania."""
    from app.core.database import AsyncSessionLocal
    from app.core.scheduling import business_today
    from app.models.contract import Contract
    from tests.test_b2b_documents_api import BASE, _create, _signed_parent
    from tests.test_b2b_documents_api import _fake_render  # noqa: F401

    rid, contract_id = await _signed_parent(app_client)
    last_service = business_today() - timedelta(days=45)
    ends = business_today() - timedelta(days=30)
    doc_id = await _create(
        app_client,
        app_auth_headers,
        "termination_agreement",
        rid,
        termination_date=ends.isoformat(),
        last_service_date=last_service.isoformat(),
    )
    effects = await app_client.get(
        f"{BASE}/documents/{doc_id}/effects", headers=app_auth_headers
    )
    assert effects.status_code == 200, effects.text
    changes = " ".join(effects.json()["changes"])
    assert last_service.strftime("%d.%m.%Y") in changes
    assert ends.strftime("%d.%m.%Y") in changes

    signed = await app_client.post(
        f"{BASE}/documents/{doc_id}/confirm-signed", headers=app_auth_headers
    )
    assert signed.status_code == 200, signed.text
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        assert contract.end_date == last_service
        assert contract.terminated_at == last_service
    row = await _row(rid)
    assert row.contract_status == "closed"
    assert row.closure_date == ends
    assert row.project_end_date == last_service
    assert row.termination_mode == "mutual_agreement"


async def test_agreement_with_future_dates_closes_the_row_on_the_agreement_day(
    app_client, app_auth_headers
):
    from app.core.database import AsyncSessionLocal
    from app.core.scheduling import business_today
    from app.models.contract import Contract
    from tests.test_audit_r7_term import _end_project_and_sync
    from tests.test_b2b_documents_api import BASE, _create, _signed_parent
    from tests.test_b2b_documents_api import _fake_render  # noqa: F401

    rid, contract_id = await _signed_parent(app_client)
    last_service = business_today() + timedelta(days=20)
    ends = business_today() + timedelta(days=40)
    doc_id = await _create(
        app_client,
        app_auth_headers,
        "termination_agreement",
        rid,
        termination_date=ends.isoformat(),
        last_service_date=last_service.isoformat(),
    )
    signed = await app_client.post(
        f"{BASE}/documents/{doc_id}/confirm-signed", headers=app_auth_headers
    )
    assert signed.status_code == 200, signed.text
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        assert contract.end_date == last_service
    row = await _row(rid)
    assert row.contract_status == "active"
    assert row.termination_mode == "mutual_agreement"

    await _end_project_and_sync(contract_id)
    row = await _row(rid)
    assert row.contract_status == "closed"
    assert row.closure_date == ends


async def test_agreement_with_service_after_termination_is_422(
    app_client, app_auth_headers
):
    from tests.test_b2b_documents_api import BASE, _signed_parent, _values
    from tests.test_b2b_documents_api import _fake_render  # noqa: F401

    rid, _ = await _signed_parent(app_client)
    resp = await app_client.post(
        f"{BASE}/documents",
        headers=app_auth_headers,
        json={
            "document_type": "termination_agreement",
            "parent_generated_contract_id": rid,
            "values": _values(
                termination_date="2026-10-31", last_service_date="2026-11-30"
            ),
        },
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "document_values_invalid"


async def test_rate_of_a_million_is_422_not_500(app_client, app_auth_headers):
    from tests.test_b2b_documents_api import BASE, _signed_parent, _values
    from tests.test_b2b_documents_api import _fake_render  # noqa: F401

    rid, _ = await _signed_parent(app_client)
    resp = await app_client.post(
        f"{BASE}/documents",
        headers=app_auth_headers,
        json={
            "document_type": "annex_rate_change",
            "parent_generated_contract_id": rid,
            "values": _values(
                effective_date="2026-11-01", new_rate="1000000", currency="PLN"
            ),
        },
    )
    assert resp.status_code == 422, resp.text
    assert "1 000 000" in resp.json()["detail"]["message"]


async def _unlinked_row(app_client, *, contracts: int) -> tuple[int, list[int]]:
    """Umowa bez kontraktu + ``contracts`` trwających kontraktów tej osoby
    u klienta umowy."""
    from app.core.database import AsyncSessionLocal
    from app.models.b2b_generated_contract import B2BGeneratedContract
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus
    from tests.test_b2b_generated_contract_status import _admin_user_id, _seed

    admin_id = await _admin_user_id(app_client)
    rid, _ = await _seed(admin_id, signature_status="signed_both")
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Wypowiadający",
            lastname=f"R10-{uuid.uuid4().hex[:6]}",
            email=f"r10-notice-{uuid.uuid4().hex[:8]}@example.com",
        )
        client = Client(name=f"R10 Notice {uuid.uuid4().hex[:6]}")
        db.add_all([cand, client])
        await db.flush()
        ids: list[int] = []
        for _ in range(contracts):
            contract = Contract(
                candidate_id=cand.id,
                client_id=client.id,
                status=ContractStatus.active,
                start_date=date(2026, 1, 1),
            )
            db.add(contract)
            await db.flush()
            ids.append(contract.id)
        row = await db.get(B2BGeneratedContract, rid)
        row.candidate_id = cand.id
        row.client_id = client.id
        row.contract_id = None
        row.contract_status = "active"
        row.template_version = None
        await db.commit()
    return rid, ids


async def test_partner_notice_without_link_ends_the_persons_contract(
    app_client, app_auth_headers
):
    from app.core.database import AsyncSessionLocal
    from app.core.scheduling import business_today
    from app.models.contract import Contract
    from tests.test_b2b_documents_api import BASE

    rid, (contract_id,) = await _unlinked_row(app_client, contracts=1)
    ends = business_today() + timedelta(days=35)
    resp = await app_client.post(
        f"{BASE}/documents/partner-notice",
        headers=app_auth_headers,
        json={
            "parent_generated_contract_id": rid,
            "delivered_on": business_today().isoformat(),
            "termination_date": ends.isoformat(),
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["contract_id"] == contract_id
    assert body["contract_matched_by_person"] is True
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        assert contract.terminated_at == ends
    row = await _row(rid)
    assert row.contract_id == contract_id
    assert row.termination_party == "consultant"


async def test_partner_notice_without_link_and_two_contracts_is_refused(
    app_client, app_auth_headers
):
    from app.core.database import AsyncSessionLocal
    from app.core.scheduling import business_today
    from app.models.contract import Contract
    from tests.test_b2b_documents_api import BASE

    rid, ids = await _unlinked_row(app_client, contracts=2)
    resp = await app_client.post(
        f"{BASE}/documents/partner-notice",
        headers=app_auth_headers,
        json={
            "parent_generated_contract_id": rid,
            "delivered_on": business_today().isoformat(),
            "termination_date": (business_today() + timedelta(days=35)).isoformat(),
        },
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "partner_notice_contract_ambiguous"
    async with AsyncSessionLocal() as db:
        for cid in ids:
            assert (await db.get(Contract, cid)).terminated_at is None
    row = await _row(rid)
    assert row.termination_mode is None


async def test_partner_notice_without_any_contract_warns(app_client, app_auth_headers):
    from app.core.scheduling import business_today
    from tests.test_b2b_documents_api import BASE

    rid, _ = await _unlinked_row(app_client, contracts=0)
    resp = await app_client.post(
        f"{BASE}/documents/partner-notice",
        headers=app_auth_headers,
        json={
            "parent_generated_contract_id": rid,
            "delivered_on": business_today().isoformat(),
            "termination_date": (business_today() + timedelta(days=35)).isoformat(),
        },
    )
    assert resp.status_code == 200, resp.text
    assert "tylko rejestr" in resp.json()["contract_warning"]


async def _rate_annex(app_client, app_auth_headers) -> tuple[int, int, int]:
    from app.core.database import AsyncSessionLocal
    from app.models.contract import Contract, RateUnit
    from tests.test_b2b_documents_api import _create, _signed_parent

    rid, contract_id = await _signed_parent(app_client)
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        contract.rate_candidate = Decimal("150")
        contract.rate_candidate_currency = "PLN"
        contract.rate_unit = RateUnit.hourly
        client_id = contract.client_id
        await db.commit()
    doc_id = await _create(
        app_client,
        app_auth_headers,
        "annex_rate_change",
        rid,
        effective_date="2026-11-01",
        new_rate="165",
        currency="PLN",
    )
    return doc_id, contract_id, client_id


async def _rate_amendment_exists(contract_id: int) -> bool:
    from app.core.database import AsyncSessionLocal
    from app.models.contract_amendment import ContractAmendment, ContractAmendmentType

    async with AsyncSessionLocal() as db:
        found = await db.scalar(
            select(ContractAmendment.id).where(
                ContractAmendment.contract_id == contract_id,
                ContractAmendment.amendment_type == ContractAmendmentType.rate_change,
            )
        )
    return found is not None


async def test_finance_confirms_a_rate_annex(app_client, app_auth_headers):
    """R10-N14-7 (decyzja 27.09.2026): Finanse potwierdzają aneks stawki,
    choć nie mają uprawnienia „Oznaczanie podpisu umowy B2B”."""
    from tests.test_b2b_documents_api import BASE, _create, _signed_parent
    from tests.test_b2b_documents_api import _fake_render  # noqa: F401
    from tests.test_b2b_generator_rate_visibility import _seed_user

    doc_id, contract_id, _ = await _rate_annex(app_client, app_auth_headers)
    finance_headers, _ = await _seed_user(app_client, "finance")
    effects = await app_client.get(
        f"{BASE}/documents/{doc_id}/effects", headers=finance_headers
    )
    assert effects.status_code == 200, effects.text
    assert effects.json()["blockers"] == []
    signed = await app_client.post(
        f"{BASE}/documents/{doc_id}/confirm-signed", headers=finance_headers
    )
    assert signed.status_code == 200, signed.text
    assert await _rate_amendment_exists(contract_id)

    # Inny dokument (porozumienie) nadal wymaga uprawnienia podpisu.
    rid, _ = await _signed_parent(app_client)
    other = await _create(
        app_client,
        app_auth_headers,
        "termination_agreement",
        rid,
        termination_date="2026-12-31",
        last_service_date="2026-12-31",
    )
    refused = await app_client.post(
        f"{BASE}/documents/{other}/confirm-signed", headers=finance_headers
    )
    assert refused.status_code == 403, refused.text


async def test_delivery_lead_confirms_a_rate_annex_in_own_portfolio(
    app_client, app_auth_headers
):
    from app.core.database import AsyncSessionLocal
    from app.models.team_structure import DeliveryLeadClientAssignment
    from tests.test_b2b_documents_api import BASE
    from tests.test_b2b_documents_api import _fake_render  # noqa: F401
    from tests.test_b2b_generator_rate_visibility import _seed_user

    doc_id, contract_id, client_id = await _rate_annex(app_client, app_auth_headers)
    dl_headers, dl_id = await _seed_user(app_client, "delivery_lead")
    async with AsyncSessionLocal() as db:
        db.add(
            DeliveryLeadClientAssignment(
                delivery_lead_user_id=dl_id, client_id=client_id
            )
        )
        await db.commit()
    effects = await app_client.get(
        f"{BASE}/documents/{doc_id}/effects", headers=dl_headers
    )
    assert effects.status_code == 200, effects.text
    assert effects.json()["blockers"] == []
    signed = await app_client.post(
        f"{BASE}/documents/{doc_id}/confirm-signed", headers=dl_headers
    )
    assert signed.status_code == 200, signed.text
    assert await _rate_amendment_exists(contract_id)


async def test_prefill_takes_company_data_from_the_register_after_the_annex(
    app_client, app_auth_headers
):
    from app.core.database import AsyncSessionLocal
    from app.models.b2b_generated_contract import B2BGeneratedContract
    from tests.test_b2b_documents_api import BASE, _signed_parent

    rid, _ = await _signed_parent(app_client)
    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, rid)
        row.render_payload = {
            **(row.render_payload or {}),
            "partner_legal_name": "Stara Firma JDG",
            "partner_nip": "1111111111",
        }
        row.partner_legal_name = "Nowa Spółka sp. z o.o."
        row.partner_nip = "2222222222"
        await db.commit()
    resp = await app_client.get(
        f"{BASE}/documents/prefill",
        headers=app_auth_headers,
        params={
            "document_type": "annex_rate_change",
            "parent_generated_contract_id": rid,
        },
    )
    assert resp.status_code == 200, resp.text
    values = resp.json()["values"]
    assert values["partner_legal_name"] == "Nowa Spółka sp. z o.o."
    assert values["partner_nip"] == "2222222222"
