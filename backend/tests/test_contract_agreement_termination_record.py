"""Rozwiązanie umowy B2B podpisane poza NEXUSEM — zapis po zakończeniu projektu.

Zgłoszenie zespołu 29.10.2026: kontrakt zakończony bez danych rozwiązania
(porozumienie podpisane poza NEXUSEM, umowa sprzed Generatora) wisiał na
liście „Umowa nierozwiązana” bez możliwości zapisu. ``PUT
/api/contracts/{id}/agreement-termination`` dopisuje same dane umowy.
Każdy test seeduje WŁASNE wiersze (baza wspólna, nieczyszczona).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.activity import Activity
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, ContractType

PATH = "/api/contracts"


async def _seed(
    *,
    contract_type: ContractType = ContractType.b2b,
    with_generator: bool = True,
) -> tuple[int, int | None]:
    """Aktywny kontrakt (+ aktywna umowa w Generatorze). Zwraca ``(cid, gid)``."""
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Poza",
            lastname=f"Nexusem-{uuid.uuid4().hex[:6]}",
            email=f"poza-{uuid.uuid4().hex[:8]}@example.com",
        )
        client = Client(name=f"KlientPoza-{uuid.uuid4().hex[:6]}")
        db.add_all([cand, client])
        await db.flush()
        contract = Contract(
            candidate_id=cand.id,
            client_id=client.id,
            status=ContractStatus.active,
            contract_type=contract_type,
            start_date=business_today() - timedelta(days=200),
            rate_candidate=Decimal("100.000"),
            rate_client=Decimal("150.000"),
        )
        db.add(contract)
        await db.flush()
        gid = None
        if with_generator:
            seq = 300000 + (uuid.uuid4().int % 300000)
            row = B2BGeneratedContract(
                year=2026,
                seq=seq,
                contract_number=f"{seq}/2026",
                partner_name="Jan Poza",
                client_name=client.name,
                language="pl",
                signature_status="signed_both",
                contract_status="active",
                candidate_id=cand.id,
                client_id=client.id,
                contract_id=contract.id,
                render_payload={"language": "pl", "client_name": client.name},
            )
            db.add(row)
            await db.flush()
            gid = row.id
        await db.commit()
        return contract.id, gid


def _agreement(signed_offset: int = -20, last_offset: int = -2) -> dict:
    today = business_today()
    return {
        "mode": "mutual_agreement",
        "party": "consultant",
        "signed_on": (today + timedelta(days=signed_offset)).isoformat(),
        "last_day": (today + timedelta(days=last_offset)).isoformat(),
    }


async def _end(app_client, headers, cid: int, days_ago: int = 5) -> None:
    resp = await app_client.post(
        f"{PATH}/{cid}/terminate",
        json={
            "termination_reason": "project_ended",
            "terminated_at": (business_today() - timedelta(days=days_ago)).isoformat(),
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


async def _generated(gid: int) -> B2BGeneratedContract:
    async with AsyncSessionLocal() as db:
        return await db.get(B2BGeneratedContract, gid)


async def test_records_agreement_on_ended_contract_and_closes_suspended_row(
    app_client, app_auth_headers
):
    cid, gid = await _seed()
    await _end(app_client, app_auth_headers, cid)
    assert (await _generated(gid)).contract_status == "suspended"

    payload = _agreement()
    resp = await app_client.put(
        f"{PATH}/{cid}/agreement-termination", json=payload, headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ended"
    assert body["agreement_termination_mode"] == "mutual_agreement"
    assert body["agreement_termination_party"] == "consultant"
    assert body["agreement_termination_signed_on"] == payload["signed_on"]
    assert body["agreement_last_day"] == payload["last_day"]
    # Koniec projektu bez zmian — zapis dotyczy tylko umowy.
    assert body["terminated_at"] == (business_today() - timedelta(days=5)).isoformat()

    row = await _generated(gid)
    assert row.contract_status == "closed"
    assert row.closure_date.isoformat() == payload["last_day"]
    assert row.termination_mode == "mutual_agreement"
    assert row.termination_signed_on.isoformat() == payload["signed_on"]

    async with AsyncSessionLocal() as db:
        actions = (
            (
                await db.execute(
                    select(Activity.action).where(
                        Activity.entity_type == "contract", Activity.entity_id == cid
                    )
                )
            )
            .scalars()
            .all()
        )
    assert "agreement_termination_recorded" in actions

    listed = await app_client.get(
        PATH,
        params={
            "agreement_not_terminated": "true",
            "q": body["candidate_name"],
            "page_size": 50,
        },
        headers=app_auth_headers,
    )
    assert listed.status_code == 200, listed.text
    assert cid not in [item["id"] for item in listed.json()["items"]]


async def test_contract_without_generator_agreement_is_recorded(
    app_client, app_auth_headers
):
    # Kontrakt jak zgłoszony: umowa sprzed Generatora, brak wiersza.
    cid, _ = await _seed(with_generator=False)
    await _end(app_client, app_auth_headers, cid)
    resp = await app_client.put(
        f"{PATH}/{cid}/agreement-termination",
        json=_agreement(),
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["agreement_termination_mode"] == "mutual_agreement"


async def test_undo_after_recording_restores_the_agreement(
    app_client, app_auth_headers
):
    cid, gid = await _seed()
    await _end(app_client, app_auth_headers, cid)
    recorded = await app_client.put(
        f"{PATH}/{cid}/agreement-termination",
        json=_agreement(),
        headers=app_auth_headers,
    )
    assert recorded.status_code == 200, recorded.text

    undo = await app_client.patch(
        f"{PATH}/{cid}/status", json={"status": "active"}, headers=app_auth_headers
    )
    assert undo.status_code == 200, undo.text
    assert undo.json()["agreement_termination_mode"] is None
    row = await _generated(gid)
    assert row.contract_status == "active"
    assert row.closure_date is None


async def test_ending_contract_is_recorded_without_touching_generator(
    app_client, app_auth_headers
):
    cid, gid = await _seed()
    resp = await app_client.post(
        f"{PATH}/{cid}/terminate",
        json={
            "termination_reason": "project_ended",
            "terminated_at": (business_today() + timedelta(days=10)).isoformat(),
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "ending"
    recorded = await app_client.put(
        f"{PATH}/{cid}/agreement-termination",
        json=_agreement(signed_offset=-1, last_offset=40),
        headers=app_auth_headers,
    )
    assert recorded.status_code == 200, recorded.text
    assert recorded.json()["agreement_termination_mode"] == "mutual_agreement"
    assert (await _generated(gid)).contract_status == "active"


async def test_active_contract_is_refused(app_client, app_auth_headers):
    cid, gid = await _seed()
    resp = await app_client.put(
        f"{PATH}/{cid}/agreement-termination",
        json=_agreement(),
        headers=app_auth_headers,
    )
    assert resp.status_code == 409, resp.text
    async with AsyncSessionLocal() as db:
        assert (await db.get(Contract, cid)).agreement_termination_mode is None
    assert (await _generated(gid)).contract_status == "active"


async def test_non_b2b_contract_is_refused(app_client, app_auth_headers):
    cid, _ = await _seed(contract_type=ContractType.uzlecenie, with_generator=False)
    await _end(app_client, app_auth_headers, cid)
    resp = await app_client.put(
        f"{PATH}/{cid}/agreement-termination",
        json=_agreement(),
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text


async def test_last_day_before_signing_is_refused(app_client, app_auth_headers):
    cid, _ = await _seed(with_generator=False)
    await _end(app_client, app_auth_headers, cid)
    resp = await app_client.put(
        f"{PATH}/{cid}/agreement-termination",
        json=_agreement(signed_offset=-2, last_offset=-20),
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text


async def test_contract_expired_by_end_date_is_recorded(app_client, app_auth_headers):
    # 28 z 69 nierozwiązanych na kopii z 22.10: „Zakończony” nocną zmianą po
    # dacie końca, bez okna — bez `terminated_at`. Lista pokazuje je z
    # „+ Rozwiązanie”, więc zapis nie może kończyć się 409.
    cid, gid = await _seed()
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, cid)
        contract.status = ContractStatus.ended
        contract.end_date = business_today() - timedelta(days=10)
        await db.commit()
    resp = await app_client.put(
        f"{PATH}/{cid}/agreement-termination",
        json=_agreement(),
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["agreement_termination_mode"] == "mutual_agreement"
    # Jak okno „Zakończ współpracę” z rozwiązaniem: umowa w Generatorze zamknięta.
    assert (await _generated(gid)).contract_status == "closed"


async def test_row_kept_for_other_project_is_closed_like_the_window(
    app_client, app_auth_headers
):
    cid, gid = await _seed()
    async with AsyncSessionLocal() as db:
        first = await db.get(Contract, cid)
        db.add(
            Contract(
                candidate_id=first.candidate_id,
                client_id=first.client_id,
                status=ContractStatus.active,
                contract_type=ContractType.b2b,
                start_date=business_today() - timedelta(days=30),
                rate_candidate=Decimal("100.000"),
                rate_client=Decimal("150.000"),
            )
        )
        await db.commit()
    await _end(app_client, app_auth_headers, cid)
    # Inny trwający projekt: zakończenie bez rozwiązania nie zawiesza umowy.
    assert (await _generated(gid)).contract_status == "active"

    payload = _agreement()
    resp = await app_client.put(
        f"{PATH}/{cid}/agreement-termination", json=payload, headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    row = await _generated(gid)
    assert row.contract_status == "closed"
    assert row.closure_date.isoformat() == payload["last_day"]


async def test_existing_dissolution_is_not_overwritten(app_client, app_auth_headers):
    cid, gid = await _seed()
    first = _agreement()
    resp = await app_client.post(
        f"{PATH}/{cid}/terminate",
        json={
            "termination_reason": "project_ended",
            "terminated_at": (business_today() - timedelta(days=5)).isoformat(),
            "agreement_termination": first,
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    again = await app_client.put(
        f"{PATH}/{cid}/agreement-termination",
        json=_agreement(signed_offset=-3, last_offset=30),
        headers=app_auth_headers,
    )
    assert again.status_code == 409, again.text
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, cid)
    assert contract.agreement_last_day.isoformat() == first["last_day"]
    assert (await _generated(gid)).closure_date.isoformat() == first["last_day"]
