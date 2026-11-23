"""Porozumienie i wypowiedzenie do umowy spoza NEXUSA (23.11.2026).

Zgłoszenie z Finansów: porozumienia nie dało się przygotować, bo wybór umowy
bazowej pokazywał wyłącznie rejestr generatora (umowy od 09.06.2026), a 392
z 510 trwających kontraktów nie ma w nim wiersza. Rozwiązanie przyjmuje teraz
kontrakt B2B bez umowy w rejestrze — numer i datę umowy wpisuje człowiek,
podpis kończy wskazany kontrakt. Bez kontraktu dokumentu nie ma („Bez
kontraktu” zostaje wyłącznie przy aneksach).

Render szablonów podmieniony (``_fake_render``); baza wspólna i nieczyszczona.
"""

from __future__ import annotations

from datetime import date

from app.core.database import AsyncSessionLocal
from app.services.b2b_documents.contract_versions import default_refs
from app.services.b2b_documents.registry import TYPES
from tests.test_b2b_documents_api import BASE, _fake_render, _values  # noqa: F401
from tests.test_b2b_generated_contract_status import _seed_linked_contract

_ENDS_CONTRACT = {"termination_agreement", "termination_notice"}


# ── czyste reguły ────────────────────────────────────────────────────────────


def test_only_b2b_terminations_take_a_contract_outside_the_register():
    keys = {k for k, t in TYPES.items() if t.accepts_contract}
    assert keys == _ENDS_CONTRACT
    for key in keys:
        assert TYPES[key].allows_external is False
        base = [f for f in TYPES[key].fields if f.group == "base"]
        assert [f.key for f in base] == ["contract_number", "contract_signing_date"]
        # Wymagane dopiero bez umowy z rejestru — pilnuje serwer, nie registry.
        assert all(not f.required for f in base)


# ── API ──────────────────────────────────────────────────────────────────────


def _termination(doc_type: str, **extra) -> dict:
    values = {
        "termination_date": "2026-10-31",
        "last_service_date": "2026-10-31",
        "delivery_date": "2026-09-23",
        "termination_reason": "other",
        "contract_number": "17/2024",
        "contract_signing_date": "2024-03-01",
        **extra,
    }
    return {
        "document_type": doc_type,
        "language": "pl",
        "parent_generated_contract_id": None,
        "values": _values(**values),
        # Wersja wzoru umowy spoza NEXUSA jest nieznana — paragrafy z formularza.
        "refs": default_refs().as_context(),
    }


async def test_agreement_to_a_contract_outside_the_register_ends_that_contract(
    app_client, app_auth_headers
):
    from app.models.b2b_contract_document import B2BContractDocument
    from app.models.contract import Contract, ContractTerminationReason

    contract_id, client_id = await _seed_linked_contract()
    resp = await app_client.post(
        f"{BASE}/documents",
        headers=app_auth_headers,
        json={**_termination("termination_agreement"), "contract_id": contract_id},
    )
    assert resp.status_code == 200, resp.text
    doc_id = int(resp.headers["X-Document-Id"])
    async with AsyncSessionLocal() as db:
        doc = await db.get(B2BContractDocument, doc_id)
        assert doc.parent_generated_contract_id is None
        assert doc.contract_id == contract_id
        assert doc.client_id == client_id
        assert doc.render_payload["base"]["contract_number"] == "17/2024"
        assert doc.render_payload["base"]["signing_date"] == "2024-03-01"
        assert (await db.get(Contract, contract_id)).terminated_at is None

    signed = await app_client.post(
        f"{BASE}/documents/{doc_id}/confirm-signed", headers=app_auth_headers
    )
    assert signed.status_code == 200, signed.text
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        assert contract.terminated_at == date(2026, 10, 31)
        assert contract.termination_reason == ContractTerminationReason.mutual_agreement


async def test_termination_outside_the_register_needs_a_contract(
    app_client, app_auth_headers
):
    """„Bez kontraktu” jest tylko przy aneksach — rozwiązanie bez kontraktu
    i bez umowy z rejestru nie miałoby czego zakończyć."""
    _, client_id = await _seed_linked_contract()
    for doc_type in _ENDS_CONTRACT:
        resp = await app_client.post(
            f"{BASE}/documents",
            headers=app_auth_headers,
            json={**_termination(doc_type), "client_id": client_id},
        )
        assert resp.status_code == 422, (doc_type, resp.text)


async def test_termination_outside_the_register_needs_the_contract_number(
    app_client, app_auth_headers
):
    contract_id, _ = await _seed_linked_contract()
    resp = await app_client.post(
        f"{BASE}/documents",
        headers=app_auth_headers,
        json={
            **_termination("termination_notice", contract_number=""),
            "contract_id": contract_id,
        },
    )
    assert resp.status_code == 422, resp.text
    assert "Numer umowy" in resp.json()["detail"]["missing"]


async def test_subjects_offer_the_contract_for_a_termination(
    app_client, app_auth_headers
):
    from app.models.candidate import Candidate
    from app.models.contract import Contract

    contract_id, _ = await _seed_linked_contract()
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        candidate = await db.get(Candidate, contract.candidate_id)
        lastname = candidate.lastname
    resp = await app_client.get(
        f"{BASE}/documents/subjects",
        headers=app_auth_headers,
        params={"document_type": "termination_agreement", "q": lastname},
    )
    assert resp.status_code == 200, resp.text
    assert {"kind": "contract", "contract_id": contract_id} in [
        {"kind": s["kind"], "contract_id": s["contract_id"]} for s in resp.json()
    ]
    # Cofnięcie wypowiedzenia nadal tylko do umowy z rejestru.
    withdrawal = await app_client.get(
        f"{BASE}/documents/subjects",
        headers=app_auth_headers,
        params={"document_type": "notice_withdrawal", "q": lastname},
    )
    assert withdrawal.status_code == 200, withdrawal.text
    assert all(s["kind"] == "agreement" for s in withdrawal.json())


async def test_contract_behind_an_unlinked_register_row_goes_through_that_row(
    app_client, app_auth_headers
):
    """Osoba ma u tego klienta umowę w rejestrze bez powiązania (wiersz
    z Excela): rozwiązanie wybiera tę umowę, nie sam kontrakt — inaczej wiersz
    rejestru zostałby „Aktywny” po rozwiązaniu umowy."""
    from tests.test_b2b_annex_generator import _lastname, _unlinked_row

    contract_id, client_id = await _seed_linked_contract()
    rid = await _unlinked_row(app_client, contract_id=contract_id, client_id=client_id)
    resp = await app_client.post(
        f"{BASE}/documents",
        headers=app_auth_headers,
        json={**_termination("termination_agreement"), "contract_id": contract_id},
    )
    assert resp.status_code == 422, resp.text
    found = await app_client.get(
        f"{BASE}/documents/subjects",
        headers=app_auth_headers,
        params={
            "document_type": "termination_agreement",
            "q": await _lastname(contract_id),
        },
    )
    assert found.status_code == 200, found.text
    kinds = {
        (s["kind"], s["parent_generated_contract_id"], s["contract_id"])
        for s in found.json()
    }
    assert ("agreement", rid, None) in kinds
    assert all(
        s["contract_id"] != contract_id for s in found.json() if s["kind"] == "contract"
    )
