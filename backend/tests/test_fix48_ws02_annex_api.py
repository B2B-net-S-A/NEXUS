"""Aneksy i kontrakty po audycie 48 h (13.10.2026) — ścieżki na bazie.

* pkt 7: „Powiąż z kontraktem” nie przenosi aneksu na inną osobę ani do
  innego klienta,
* kontrakt z żywą umową w rejestrze nie przyjmuje aneksu „spoza NEXUSA”,
* dowiązanie umowy z Excela przy aneksie idzie rdzeniem „Powiąż z kontraktem”,
* skan usunięty z Dokumentów kontraktu nie udaje istniejącego,
* portfel Delivery Leada i bramka kwot w zakładce „Aneksy” kontraktu, przy
  skanie (obie trasy) i przy przywróceniu.

Render szablonów jest podmieniony (``_fake_render``). Baza wspólna
i nieczyszczona: asercje wyłącznie na własnych wierszach. Reguły tych samych
tras bez bazy: ``test_fix48_ws02_annex_link_rules.py``.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from tests._permission_grants import grant_permissions
from tests.test_b2b_annex_generator import (
    _document,
    _external,
    _row,
    _unlinked_row,
)
from tests.test_b2b_annex_signed_scan import (
    PDF,
    _rate_amendment,
    _signed_rate_annex,
    _upload,
)
from tests.test_b2b_documents_api import (  # noqa: F401
    BASE,
    _create,
    _fake_render,
    _signed_parent,
)
from tests.test_b2b_generated_contract_status import _seed_linked_contract
from tests.test_b2b_generator_rate_visibility import _seed_user
from tests.test_contract_annex_tab import _annex_documents, _hourly

CLIENT = "Klient Testowy WS02"


async def _contract_for(client_id: int, candidate_id: int | None = None) -> int:
    """Trwający kontrakt B2B u klienta: tej osoby albo nowej."""
    from app.models.candidate import Candidate
    from app.models.contract import Contract, ContractStatus

    async with AsyncSessionLocal() as db:
        if candidate_id is None:
            person = Candidate(
                name="Bartosz",
                lastname=f"Przykładowy-{uuid.uuid4().hex[:6]}",
                email=f"ws02-{uuid.uuid4().hex[:8]}@example.com",
            )
            db.add(person)
            await db.flush()
            candidate_id = person.id
        contract = Contract(
            candidate_id=candidate_id,
            client_id=client_id,
            status=ContractStatus.active,
            start_date=date(2026, 6, 1),
        )
        db.add(contract)
        await db.commit()
        await db.refresh(contract)
        return contract.id


async def _client_of(contract_id: int) -> int:
    from app.models.contract import Contract

    async with AsyncSessionLocal() as db:
        return (await db.get(Contract, contract_id)).client_id


async def _assign(dl_id: int, client_id: int) -> None:
    from app.models.team_structure import DeliveryLeadClientAssignment

    async with AsyncSessionLocal() as db:
        db.add(
            DeliveryLeadClientAssignment(
                delivery_lead_user_id=dl_id, client_id=client_id
            )
        )
        await db.commit()


async def _delivery_lead(app_client, client_id: int) -> tuple[dict, int]:
    """Delivery Lead z portfelem złożonym z jednego klienta."""
    headers, dl_id = await _seed_user(app_client, "delivery_lead")
    await _assign(dl_id, client_id)
    return headers, dl_id


def _scan_id(doc) -> int | None:
    return (doc.effect_summary or {}).get("signed_scan_document_id")


async def _link(app_client, headers, doc_id: int, contract_id: int):
    return await app_client.post(
        f"{BASE}/documents/{doc_id}/link-contract",
        headers=headers,
        json={"contract_id": contract_id},
    )


# ── pkt 7: aneks nie trafia do cudzego kontraktu ─────────────────────────────


async def test_annex_of_a_void_contract_does_not_move_to_another_person(
    app_client, app_auth_headers
):
    """Aneks osoby A z unieważnionym kontraktem wiązał się z kontraktem
    osoby B, a podpis zapisywał wtedy dane A w kontrakcie B."""
    from app.models.contract import Contract, ContractStatus

    contract_a, client_id = await _seed_linked_contract(CLIENT)
    saved = await _external(
        app_client,
        app_auth_headers,
        "annex_start_date",
        contract_id=contract_a,
        values={
            "contract_number": f"WS02-{contract_a}/2025",
            "new_start_date": "2026-11-16",
        },
    )
    assert saved.status_code == 200, saved.text
    doc_id = int(saved.headers["X-Document-Id"])
    person_a = (await _document(doc_id)).candidate_id
    async with AsyncSessionLocal() as db:
        (await db.get(Contract, contract_a)).status = ContractStatus.void
        await db.commit()

    stranger = await _contract_for(client_id)
    refused = await _link(app_client, app_auth_headers, doc_id, stranger)
    assert refused.status_code == 409, refused.text
    assert "innej osoby" in refused.json()["detail"]
    doc = await _document(doc_id)
    assert (doc.contract_id, doc.candidate_id) == (contract_a, person_a)

    own = await _contract_for(client_id, candidate_id=person_a)
    linked = await _link(app_client, app_auth_headers, doc_id, own)
    assert linked.status_code == 200, linked.text
    assert linked.json()["contract_id"] == own
    assert (await _document(doc_id)).candidate_id == person_a


async def test_annex_without_contract_links_only_at_its_own_client(
    app_client, app_auth_headers
):
    contract_x, client_x = await _seed_linked_contract(CLIENT)
    contract_y, _client_y = await _seed_linked_contract(CLIENT)
    saved = await _external(
        app_client,
        app_auth_headers,
        "annex_start_date",
        client_id=client_x,
        values={
            "contract_number": f"WS02-BK-{contract_x}/2025",
            "new_start_date": "2026-11-16",
        },
    )
    assert saved.status_code == 200, saved.text
    doc_id = int(saved.headers["X-Document-Id"])

    elsewhere = await _link(app_client, app_auth_headers, doc_id, contract_y)
    assert elsewhere.status_code == 409, elsewhere.text
    assert "innego klienta" in elsewhere.json()["detail"]
    doc = await _document(doc_id)
    assert (doc.contract_id, doc.client_id) == (None, client_x)

    here = await _link(app_client, app_auth_headers, doc_id, contract_x)
    assert here.status_code == 200, here.text
    assert here.json()["contract_id"] == contract_x


# ── kontrakt z umową w rejestrze ─────────────────────────────────────────────


async def test_contract_with_its_own_agreement_takes_annexes_through_it(
    app_client, app_auth_headers
):
    """Wyszukiwarka nie pokazuje takiego kontraktu, ale trasy przyjmowały go
    samym ``contract_id`` — aneks omijał wiersz rejestru."""
    from app.models.b2b_contract_document import B2BContractDocument

    _rid, contract_id = await _signed_parent(app_client)
    client_id = await _client_of(contract_id)
    values = {
        "contract_number": f"WS02-OWN-{contract_id}/2025",
        "new_start_date": "2026-11-16",
    }

    direct = await _external(
        app_client,
        app_auth_headers,
        "annex_start_date",
        contract_id=contract_id,
        values=values,
    )
    assert direct.status_code == 422, direct.text
    assert "umowę w rejestrze" in direct.json()["detail"]
    async with AsyncSessionLocal() as db:
        saved = await db.scalar(
            select(func.count())
            .select_from(B2BContractDocument)
            .where(
                B2BContractDocument.contract_id == contract_id,
                B2BContractDocument.parent_generated_contract_id.is_(None),
            )
        )
    assert saved == 0

    waiting = await _external(
        app_client,
        app_auth_headers,
        "annex_start_date",
        client_id=client_id,
        values=values,
    )
    assert waiting.status_code == 200, waiting.text
    doc_id = int(waiting.headers["X-Document-Id"])
    refused = await _link(app_client, app_auth_headers, doc_id, contract_id)
    assert refused.status_code == 422, refused.text
    assert (await _document(doc_id)).contract_id is None


# ── dowiązanie umowy z Excela przez aneks ────────────────────────────────────


async def _assert_linked_like_the_register(rid: int, contract_id: int) -> None:
    """Numer umowy na kontrakcie, wpis na osi czasu umowy i na kontrakcie."""
    from app.models.activity import Activity
    from app.models.b2b_contract_detail import B2BContractDetail
    from app.models.b2b_generated_contract import B2BGeneratedContractStatusEvent

    row = await _row(rid)
    assert row.contract_id == contract_id
    async with AsyncSessionLocal() as db:
        detail = await db.scalar(
            select(B2BContractDetail).where(
                B2BContractDetail.contract_id == contract_id
            )
        )
        events = (
            await db.scalars(
                select(B2BGeneratedContractStatusEvent).where(
                    B2BGeneratedContractStatusEvent.generated_contract_id == rid
                )
            )
        ).all()
        activity = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "contract",
                Activity.entity_id == contract_id,
                Activity.action == "generated_contract_linked",
            )
        )
    assert detail is not None and detail.contract_number == row.contract_number
    assert [
        e.details.get("contract_id")
        for e in events
        if (e.details or {}).get("source") == "linked_to_contract"
    ] == [contract_id]
    assert activity is not None
    assert activity.details["generated_contract_id"] == rid


async def test_annex_links_an_excel_row_the_same_way_as_the_register(
    app_client, app_auth_headers
):
    contract_id, client_id = await _seed_linked_contract(CLIENT)
    rid = await _unlinked_row(app_client, contract_id=contract_id, client_id=client_id)
    await _create(
        app_client,
        app_auth_headers,
        "annex_start_date",
        rid,
        new_start_date="2026-11-15",
    )
    await _assert_linked_like_the_register(rid, contract_id)


async def test_linking_an_annex_later_links_the_row_the_same_way(
    app_client, app_auth_headers
):
    """Dwa trwające kontrakty: aneks powstaje bez powiązania, a wiersz
    dowiązuje dopiero „Powiąż z kontraktem” w rejestrze aneksów."""
    first_id, client_id = await _seed_linked_contract(CLIENT)
    rid = await _unlinked_row(app_client, contract_id=first_id, client_id=client_id)
    second_id = await _contract_for(
        client_id, candidate_id=(await _row(rid)).candidate_id
    )
    doc_id = await _create(
        app_client,
        app_auth_headers,
        "annex_start_date",
        rid,
        new_start_date="2026-11-15",
    )
    assert (await _row(rid)).contract_id is None

    linked = await _link(app_client, app_auth_headers, doc_id, second_id)
    assert linked.status_code == 200, linked.text
    await _assert_linked_like_the_register(rid, second_id)


# ── skan usunięty z Dokumentów kontraktu ─────────────────────────────────────


async def test_deleted_scan_is_not_offered_as_an_existing_one(
    app_client, app_auth_headers
):
    """Zapis skutku trzymał id usuniętego skanu — okno mówiło „Podmień skan”
    i „Nowy plik zastąpi skan…” przy skanie, którego nie ma."""
    doc_id, contract_id = await _signed_rate_annex(app_client, app_auth_headers)
    signed = await app_client.post(
        f"{BASE}/documents/{doc_id}/confirm-signed", headers=app_auth_headers
    )
    assert signed.status_code == 200, signed.text
    url = f"{BASE}/documents/{doc_id}/signed-scan"
    first = await _upload(app_client, app_auth_headers, url)
    assert first.status_code == 200, first.text
    scan_id = first.json()["signed_scan_document_id"]
    assert scan_id is not None

    removed = await app_client.delete(
        f"/api/contracts/{contract_id}/documents/{scan_id}", headers=app_auth_headers
    )
    assert removed.status_code == 204, removed.text
    # Podpisany dokument: „Oznacz jako podpisany” oddaje go bez zmian.
    again = await app_client.post(
        f"{BASE}/documents/{doc_id}/confirm-signed", headers=app_auth_headers
    )
    assert again.status_code == 200, again.text
    assert again.json()["signed_scan_document_id"] is None

    second = await _upload(app_client, app_auth_headers, url, "skan-2.pdf", PDF)
    assert second.status_code == 200, second.text
    new_id = second.json()["signed_scan_document_id"]
    assert new_id is not None and new_id != scan_id
    assert (await _rate_amendment(contract_id)).document_id == new_id


# ── portfel Delivery Leada i kwoty ───────────────────────────────────────────


async def test_contract_annex_tab_keeps_the_portfolio_and_hides_amounts(
    app_client, app_auth_headers
):
    contract_id, client_id = await _seed_linked_contract(CLIENT)
    await _hourly(contract_id, "140")
    saved = await _external(
        app_client,
        app_auth_headers,
        "annex_rate_change",
        contract_id=contract_id,
        values={
            "contract_number": f"WS02-RATE-{contract_id}/2025",
            "effective_date": "2026-11-01",
            "rate_items": [{"rate": "150"}],
        },
    )
    assert saved.status_code == 200, saved.text
    url = f"/api/contracts/{contract_id}/annex-documents"

    _other_contract, other_client = await _seed_linked_contract(CLIENT)
    outside_headers, _ = await _delivery_lead(app_client, other_client)
    outside = await app_client.get(url, headers=outside_headers)
    assert outside.status_code == 403, outside.text

    inside_headers, _ = await _delivery_lead(app_client, client_id)
    [own] = await _annex_documents(app_client, inside_headers, contract_id)
    assert [i["rate"] for i in own["change"]["items"]] == [150.0]
    assert [i["rate"] for i in own["change"]["before"]] == [140.0]

    # TCM widzi kontrakt, ale nie ma „Stawki i kwoty: podgląd”.
    tcm_headers, _ = await _seed_user(app_client, "talent_community_manager")
    [seen] = await _annex_documents(app_client, tcm_headers, contract_id)
    assert seen["change"] == {"kind": "rate", "hidden": True}


async def test_scan_and_restore_stay_inside_the_delivery_lead_portfolio(
    app_client, app_auth_headers
):
    from app.models.b2b_contract_document import B2BContractDocument

    rid, contract_id = await _signed_parent(app_client)
    client_id = await _client_of(contract_id)
    _other_contract, other_client = await _seed_linked_contract(CLIENT)
    outside_headers, outside_id = await _delivery_lead(app_client, other_client)
    inside_headers, inside_id = await _delivery_lead(app_client, client_id)

    signed_id = await _create(
        app_client,
        app_auth_headers,
        "annex_start_date",
        rid,
        new_start_date="2026-11-16",
    )
    signed = await app_client.post(
        f"{BASE}/documents/{signed_id}/confirm-signed", headers=app_auth_headers
    )
    assert signed.status_code == 200, signed.text
    url = f"{BASE}/documents/{signed_id}/signed-scan"
    refused = await _upload(app_client, outside_headers, url)
    assert refused.status_code == 403, refused.text
    assert _scan_id(await _document(signed_id)) is None
    allowed = await _upload(app_client, inside_headers, url)
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["signed_scan_document_id"] is not None

    cancelled_id = await _create(
        app_client,
        app_auth_headers,
        "annex_start_date",
        rid,
        new_start_date="2026-11-20",
    )
    cancelled = await app_client.post(
        f"{BASE}/documents/{cancelled_id}/cancel",
        headers=app_auth_headers,
        json={"reason": "Zmiana ustaleń"},
    )
    assert cancelled.status_code == 200, cancelled.text

    async def restore_as(headers, author_id: int):
        async with AsyncSessionLocal() as db:
            (await db.get(B2BContractDocument, cancelled_id)).created_by = author_id
            await db.commit()
        return await app_client.post(
            f"{BASE}/documents/{cancelled_id}/restore", headers=headers
        )

    # Autor spoza portfela klienta nie przywraca — zapis u klienta.
    outside_restore = await restore_as(outside_headers, outside_id)
    assert outside_restore.status_code == 403, outside_restore.text
    assert (await _document(cancelled_id)).status == "cancelled"
    inside_restore = await restore_as(inside_headers, inside_id)
    assert inside_restore.status_code == 200, inside_restore.text
    assert inside_restore.json()["status"] == "issued"


async def test_scan_from_the_contract_keeps_the_portfolio_and_the_amounts_gate(
    app_client, app_auth_headers
):
    """Skan aneksu stawki niesie kwotę — dołącza go tylko osoba z wglądem
    w kwoty tego klienta (Delivery Lead: z portfela)."""
    doc_id, contract_id = await _signed_rate_annex(app_client, app_auth_headers)
    signed = await app_client.post(
        f"{BASE}/documents/{doc_id}/confirm-signed", headers=app_auth_headers
    )
    assert signed.status_code == 200, signed.text
    amendment = await _rate_amendment(contract_id)
    before = amendment.document_id
    url = f"/api/contracts/{contract_id}/amendments/{amendment.id}/document"

    _other_contract, other_client = await _seed_linked_contract(CLIENT)
    outside_headers, _ = await _delivery_lead(app_client, other_client)
    outside = await _upload(app_client, outside_headers, url)
    assert outside.status_code == 403, outside.text

    tcm_headers, tcm_id = await _seed_user(app_client, "talent_community_manager")
    await grant_permissions(tcm_id, "contracts_orders_edit")
    no_amounts = await _upload(app_client, tcm_headers, url)
    assert no_amounts.status_code == 403, no_amounts.text
    assert (await _rate_amendment(contract_id)).document_id == before

    inside_headers, _ = await _delivery_lead(app_client, await _client_of(contract_id))
    inside = await _upload(app_client, inside_headers, url)
    assert inside.status_code == 200, inside.text
    assert (
        inside.json()["new_values"] == (await _rate_amendment(contract_id)).new_values
    )
