"""Wypowiedzenie po „Zakończ i przygotuj wypowiedzenie” nie skraca projektu (audyt 12.11.2026, K1).

Okno zapisuje koniec projektu na kontrakcie i otwiera generator. Generator
podpowiadał rozwiązanie umowy = dziś + okres wypowiedzenia, a podpis ustawiał
ten dzień jako koniec kontraktu i przycinał zamówienia — kontrakt z końcem
projektu 31.01 kończył się 31.12. Teraz generator podpowiada późniejszą z dat,
a podpis nie skraca końca projektu wybranego w oknie.

Baza wspólna i nieczyszczona — asercje wyłącznie na własnych wierszach.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.services.b2b_documents.contract_versions import notice_end_date, refs_for
from tests.test_b2b_documents_api import BASE, _create, _signed_parent
from tests.test_b2b_documents_api import _fake_render  # noqa: F401 (autouse)


def _notice_end() -> date:
    refs = refs_for("2026")
    assert refs is not None
    return notice_end_date(business_today(), refs)


async def _ended_in_window(app_client, project_end: date) -> tuple[int, int]:
    """Stan po „Zakończ i przygotuj wypowiedzenie”: koniec projektu, bez rozwiązania."""
    from app.models.contract import Contract, ContractStatus, ContractTerminationReason

    rid, contract_id = await _signed_parent(app_client)
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        contract.status = ContractStatus.ending
        contract.end_date = project_end
        contract.terminated_at = project_end
        contract.termination_reason = ContractTerminationReason.project_ended
        await db.commit()
    return rid, contract_id


async def _prefill(app_client, headers, rid: int) -> dict:
    resp = await app_client.get(
        f"{BASE}/documents/prefill",
        headers=headers,
        params={
            "document_type": "termination_notice",
            "parent_generated_contract_id": rid,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_prefill_takes_the_project_end_when_it_is_later_than_the_notice(
    app_client, app_auth_headers
):
    project_end = _notice_end() + timedelta(days=31)
    rid, _ = await _ended_in_window(app_client, project_end)

    body = await _prefill(app_client, app_auth_headers, rid)

    assert body["values"]["termination_date"] == project_end.isoformat()
    note = body["notes"]["termination_date"]
    assert project_end.strftime("%d.%m.%Y") in note
    assert _notice_end().strftime("%d.%m.%Y") in note


async def test_prefill_keeps_the_notice_end_when_the_project_ends_earlier(
    app_client, app_auth_headers
):
    rid, _ = await _ended_in_window(app_client, business_today() + timedelta(days=3))

    body = await _prefill(app_client, app_auth_headers, rid)

    assert body["values"]["termination_date"] == _notice_end().isoformat()
    assert body["notes"] == {}


async def test_prefill_of_a_running_contract_is_the_notice_end(
    app_client, app_auth_headers
):
    """Bez zakończenia z okna koniec kontraktu to plan, nie decyzja — liczy się okres."""
    from app.models.contract import Contract

    rid, contract_id = await _signed_parent(app_client)
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        contract.end_date = _notice_end() + timedelta(days=90)
        await db.commit()

    body = await _prefill(app_client, app_auth_headers, rid)

    assert body["values"]["termination_date"] == _notice_end().isoformat()
    assert body["notes"] == {}


async def test_signed_notice_does_not_cut_the_project_end_chosen_in_the_window(
    app_client, app_auth_headers
):
    """Dokument wydany z wcześniejszą datą (np. przed poprawką) nie skraca projektu."""
    from app.models.contract import Contract, ContractStatus

    project_end = _notice_end() + timedelta(days=31)
    rid, contract_id = await _ended_in_window(app_client, project_end)
    doc_id = await _create(
        app_client,
        app_auth_headers,
        "termination_notice",
        rid,
        delivery_date=business_today().isoformat(),
        termination_date=_notice_end().isoformat(),
        termination_reason="project_ended",
    )
    effects = await app_client.get(
        f"{BASE}/documents/{doc_id}/effects", headers=app_auth_headers
    )
    assert effects.status_code == 200, effects.text
    assert "nie skróci" in " ".join(effects.json()["changes"])
    assert effects.json()["warnings"]

    signed = await app_client.post(
        f"{BASE}/documents/{doc_id}/confirm-signed", headers=app_auth_headers
    )

    assert signed.status_code == 200, signed.text
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        assert contract.end_date == project_end
        assert contract.terminated_at == project_end
        assert contract.status == ContractStatus.ending


async def test_agreement_with_an_earlier_last_service_day_still_ends_the_project(
    app_client, app_auth_headers
):
    """Porozumienie niesie własny ostatni dzień świadczenia usług — on decyduje."""
    from app.models.contract import Contract

    project_end = _notice_end() + timedelta(days=31)
    earlier = project_end - timedelta(days=10)
    rid, contract_id = await _ended_in_window(app_client, project_end)
    doc_id = await _create(
        app_client,
        app_auth_headers,
        "termination_agreement",
        rid,
        termination_date=earlier.isoformat(),
        last_service_date=earlier.isoformat(),
    )

    signed = await app_client.post(
        f"{BASE}/documents/{doc_id}/confirm-signed", headers=app_auth_headers
    )

    assert signed.status_code == 200, signed.text
    async with AsyncSessionLocal() as db:
        assert (await db.get(Contract, contract_id)).end_date == earlier


async def test_signed_notice_on_the_project_end_keeps_the_contract_end(
    app_client, app_auth_headers
):
    from app.models.contract import Contract

    project_end = _notice_end() + timedelta(days=31)
    rid, contract_id = await _ended_in_window(app_client, project_end)
    doc_id = await _create(
        app_client,
        app_auth_headers,
        "termination_notice",
        rid,
        delivery_date=business_today().isoformat(),
        termination_date=project_end.isoformat(),
        termination_reason="project_ended",
    )

    signed = await app_client.post(
        f"{BASE}/documents/{doc_id}/confirm-signed", headers=app_auth_headers
    )

    assert signed.status_code == 200, signed.text
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        assert contract.end_date == project_end
        assert contract.agreement_termination_mode == "notice"
        assert contract.agreement_last_day == project_end
