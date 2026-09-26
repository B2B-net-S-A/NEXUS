"""Dokumenty pochodne umowy B2B — poprawki rundy 6 audytu (26.09.2026).

* DOC-1: rozwiązanie umowy, której projekt (kontrakt) zakończył się wcześniej,
  nie nadpisuje zakończenia kontraktu — zamyka tylko umowę w rejestrze;
* DOC-2: skutki podpisu idą do BIEŻĄCEGO kontraktu umowy bazowej, a przy
  kontrakcie unieważnionym — czytelna odmowa;
* DOC-3: wypowiedzenie Partnera umowy bez wersji wzoru wymaga daty;
* LOCK-1: kolejność blokad kontrakt → wiersz rejestru (test źródła).

Baza wspólna i nieczyszczona — asercje wyłącznie na własnych wierszach.
"""

from __future__ import annotations

import inspect
from datetime import date

from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from tests.test_b2b_documents_api import BASE, _create, _signed_parent
from tests.test_b2b_documents_api import _fake_render  # noqa: F401 (autouse)
from tests.test_b2b_generated_contract_status import _seed_linked_contract

PROJECT_END = date(2026, 6, 30)


async def _project_ended_earlier(app_client) -> tuple[int, int]:
    """Umowa w „Umowach bez projektu”: jej kontrakt zakończył się 30.06."""
    from app.models.b2b_generated_contract import B2BGeneratedContract
    from app.models.contract import Contract, ContractStatus, ContractTerminationReason

    rid, contract_id = await _signed_parent(app_client)
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        contract.status = ContractStatus.ended
        contract.end_date = PROJECT_END
        contract.terminated_at = PROJECT_END
        contract.termination_reason = ContractTerminationReason.project_ended
        contract.termination_lessons = "Koniec projektu u klienta"
        row = await db.get(B2BGeneratedContract, rid)
        row.contract_status = "suspended"
        row.closure_reason = "project_completed"
        row.closure_date = PROJECT_END
        row.project_end_date = PROJECT_END
        row.termination_restore = {
            "contract_id": contract_id,
            "contract_status": "active",
            "closure_reason": None,
            "closure_reason_other": None,
            "closure_date": None,
            "termination_mode": None,
            "termination_party": None,
            "termination_signed_on": None,
            "project_end_date": None,
        }
        await db.commit()
    return rid, contract_id


async def _terminated_activities(contract_id: int) -> int:
    from app.models.activity import Activity

    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(func.count(Activity.id)).where(
                Activity.entity_type == "contract",
                Activity.entity_id == contract_id,
                Activity.action == "terminated",
            )
        )


async def _assert_contract_untouched(contract_id: int) -> None:
    from app.models.contract import Contract, ContractStatus, ContractTerminationReason

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        assert contract.status == ContractStatus.ended
        assert contract.terminated_at == PROJECT_END
        assert contract.end_date == PROJECT_END
        assert contract.termination_reason == ContractTerminationReason.project_ended
        assert contract.termination_lessons == "Koniec projektu u klienta"
        assert contract.agreement_termination_mode is None


# ── DOC-1 ────────────────────────────────────────────────────────────────────


async def test_agreement_for_project_that_already_ended_only_closes_the_register(
    app_client, app_auth_headers
):
    from app.models.b2b_generated_contract import B2BGeneratedContract

    rid, contract_id = await _project_ended_earlier(app_client)
    before = await _terminated_activities(contract_id)
    doc_id = await _create(
        app_client,
        app_auth_headers,
        "termination_agreement",
        rid,
        termination_date="2026-08-31",
        last_service_date="2026-08-31",
    )
    effects = await app_client.get(
        f"{BASE}/documents/{doc_id}/effects", headers=app_auth_headers
    )
    assert effects.status_code == 200, effects.text
    changes = " ".join(effects.json()["changes"])
    assert "już „Zakończony”" in changes
    assert "kontrakt, zamówienia klienta" not in changes

    signed = await app_client.post(
        f"{BASE}/documents/{doc_id}/confirm-signed", headers=app_auth_headers
    )
    assert signed.status_code == 200, signed.text

    await _assert_contract_untouched(contract_id)
    assert await _terminated_activities(contract_id) == before
    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, rid)
        assert row.contract_status == "closed"
        assert row.closure_date == date(2026, 8, 31)
        assert row.termination_mode == "mutual_agreement"
        assert row.project_end_date == PROJECT_END


async def test_partner_notice_for_project_that_already_ended_keeps_the_contract(
    app_client, app_auth_headers
):
    from app.models.b2b_generated_contract import B2BGeneratedContract

    rid, contract_id = await _project_ended_earlier(app_client)
    before = await _terminated_activities(contract_id)
    resp = await app_client.post(
        f"{BASE}/documents/partner-notice",
        headers=app_auth_headers,
        json={
            "parent_generated_contract_id": rid,
            "delivered_on": "2026-07-10",
            "termination_date": "2026-08-31",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["contract_already_ended"] is True

    await _assert_contract_untouched(contract_id)
    assert await _terminated_activities(contract_id) == before
    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, rid)
        assert row.contract_status == "closed"
        assert row.closure_date == date(2026, 8, 31)
        assert row.termination_party == "consultant"


# ── DOC-2 ────────────────────────────────────────────────────────────────────


async def test_effects_follow_the_current_contract_of_the_agreement(
    app_client, app_auth_headers
):
    """Dokument wygenerowany przy kontrakcie A, potem A unieważniony i umowa
    powiązana z B — aneks trafia do B, nie do unieważnionego A."""
    from app.models.b2b_contract_document import B2BContractDocument
    from app.models.b2b_generated_contract import B2BGeneratedContract
    from app.models.contract import Contract, ContractStatus

    rid, old_contract_id = await _signed_parent(app_client)
    doc_id = await _create(
        app_client,
        app_auth_headers,
        "annex_start_date",
        rid,
        new_start_date="2026-11-01",
        new_start_date_mode="exact",
    )
    new_contract_id, _ = await _seed_linked_contract()
    async with AsyncSessionLocal() as db:
        old = await db.get(Contract, old_contract_id)
        old.status = ContractStatus.void
        old_start = old.start_date
        row = await db.get(B2BGeneratedContract, rid)
        row.contract_id = new_contract_id
        await db.commit()

    signed = await app_client.post(
        f"{BASE}/documents/{doc_id}/confirm-signed", headers=app_auth_headers
    )
    assert signed.status_code == 200, signed.text
    async with AsyncSessionLocal() as db:
        assert (await db.get(Contract, new_contract_id)).start_date == date(2026, 11, 1)
        assert (await db.get(Contract, old_contract_id)).start_date == old_start
        doc = await db.get(B2BContractDocument, doc_id)
        assert doc.contract_id == new_contract_id
        assert doc.effect_summary["contract_id"] == new_contract_id


async def test_agreement_linked_to_a_void_contract_refuses_effects(
    app_client, app_auth_headers
):
    from app.models.contract import Contract, ContractStatus

    rid, contract_id = await _signed_parent(app_client)
    doc_id = await _create(
        app_client,
        app_auth_headers,
        "termination_agreement",
        rid,
        termination_date="2026-10-31",
        last_service_date="2026-10-31",
    )
    async with AsyncSessionLocal() as db:
        (await db.get(Contract, contract_id)).status = ContractStatus.void
        await db.commit()

    effects = await app_client.get(
        f"{BASE}/documents/{doc_id}/effects", headers=app_auth_headers
    )
    assert any("unieważnionym" in b for b in effects.json()["blockers"])
    signed = await app_client.post(
        f"{BASE}/documents/{doc_id}/confirm-signed", headers=app_auth_headers
    )
    assert signed.status_code == 409, signed.text
    assert "unieważnionym" in signed.json()["detail"]
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        assert contract.status == ContractStatus.void
        assert contract.terminated_at is None


# ── DOC-3 ────────────────────────────────────────────────────────────────────


async def test_partner_notice_without_template_version_requires_a_date(
    app_client, app_auth_headers
):
    """Wiersz z Excela działu nie zna wersji wzoru — okresu wypowiedzenia nie
    zgadujemy z umowy 2026."""
    from app.models.b2b_generated_contract import B2BGeneratedContract

    rid, _contract_id = await _signed_parent(app_client)
    async with AsyncSessionLocal() as db:
        (await db.get(B2BGeneratedContract, rid)).template_version = None
        await db.commit()

    prefill = await app_client.get(
        f"{BASE}/documents/prefill",
        headers=app_auth_headers,
        params={
            "document_type": "termination_notice",
            "parent_generated_contract_id": rid,
        },
    )
    assert prefill.status_code == 200, prefill.text
    assert "termination_date" not in prefill.json()["values"]

    guessed = await app_client.post(
        f"{BASE}/documents/partner-notice",
        headers=app_auth_headers,
        json={"parent_generated_contract_id": rid, "delivered_on": "2026-09-15"},
    )
    assert guessed.status_code == 422, guessed.text
    assert "podaj datę rozwiązania" in guessed.json()["detail"]

    explicit = await app_client.post(
        f"{BASE}/documents/partner-notice",
        headers=app_auth_headers,
        json={
            "parent_generated_contract_id": rid,
            "delivered_on": "2026-09-15",
            "termination_date": "2026-09-30",
        },
    )
    assert explicit.status_code == 200, explicit.text
    assert explicit.json()["termination_date"] == "2026-09-30"


# ── LOCK-1 ───────────────────────────────────────────────────────────────────


def _index(source: str, needle: str) -> int:
    position = source.find(needle)
    assert position >= 0, needle
    return position


def test_document_paths_lock_the_contract_before_the_register_row():
    """``/terminate`` i nocny cron: kontrakt → wiersze rejestru. Ścieżki
    dokumentów blokowały odwrotnie (runda 6 audytu, LOCK-1)."""
    from app.api import b2b_contract_generator, b2b_documents

    confirm = inspect.getsource(b2b_documents.confirm_document_signed)
    assert _index(confirm, "_lock_contract_first(") < _index(confirm, "_load_document(")
    notice = inspect.getsource(b2b_documents.register_partner_notice)
    assert _index(notice, "_lock_contract_first(") < _index(notice, "_load_parent(")
    link = inspect.getsource(b2b_contract_generator.link_generated_contract_to_contract)
    assert _index(link, "select(Contract)") < _index(
        link, "select(B2BGeneratedContract)"
    )
