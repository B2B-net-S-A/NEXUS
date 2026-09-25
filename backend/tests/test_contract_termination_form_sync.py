"""Zakończenie współpracy — obowiązkowe okno, rozwiązanie umowy, Generator B2B.

Ticket 09.2026 (kontrakt #674): „Zakończony" z listy statusu zmieniał status
bez powodu i daty, okno nie znało rozwiązania umowy B2B, a Generator umów nie
wiedział o zakończeniu. Każdy test seeduje WŁASNE wiersze (baza wspólna,
nieczyszczona) i asertuje wyłącznie na nich.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.activity import Activity
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.b2b_generated_contract_status_event import (
    B2BGeneratedContractStatusEvent,
)
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import (
    Contract,
    ContractStatus,
    ContractTerminationReason,
    ContractType,
)

PATH = "/api/contracts"


async def _seed(
    *,
    status: ContractStatus = ContractStatus.active,
    candidate_id: int | None = None,
    generator_status: str | None = "active",
    link_generator: bool = True,
) -> tuple[int, int | None, int]:
    """Kontrakt B2B (+ opcjonalnie umowa w Generatorze). Zwraca
    ``(contract_id, generated_id, candidate_id)``."""
    async with AsyncSessionLocal() as db:
        if candidate_id is None:
            cand = Candidate(
                name="Koniec",
                lastname=f"Wsp-{uuid.uuid4().hex[:6]}",
                email=f"koniec-{uuid.uuid4().hex[:8]}@example.com",
            )
            db.add(cand)
            await db.flush()
            candidate_id = cand.id
        client = Client(name=f"KlientKoniec-{uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.flush()
        contract = Contract(
            candidate_id=candidate_id,
            client_id=client.id,
            status=status,
            contract_type=ContractType.b2b,
            start_date=business_today() - timedelta(days=200),
            rate_candidate=Decimal("100.000"),
            rate_client=Decimal("150.000"),
        )
        db.add(contract)
        await db.flush()
        generated_id = None
        if generator_status is not None:
            seq = 600000 + (uuid.uuid4().int % 300000)
            row = B2BGeneratedContract(
                year=2026,
                seq=seq,
                contract_number=f"{seq}/2026",
                partner_name="Jan Koniec",
                client_name=client.name,
                language="pl",
                signature_status="signed_both",
                contract_status=generator_status,
                candidate_id=candidate_id,
                client_id=client.id,
                contract_id=contract.id if link_generator else None,
                # CHECK spójności: suspended/closed wymagają powodu i daty.
                closure_reason=(
                    "project_completed"
                    if generator_status in ("suspended", "closed")
                    else None
                ),
                closure_date=(
                    business_today() - timedelta(days=60)
                    if generator_status in ("suspended", "closed")
                    else None
                ),
                render_payload={"language": "pl", "client_name": client.name},
            )
            db.add(row)
            await db.flush()
            generated_id = row.id
        await db.commit()
        return contract.id, generated_id, candidate_id


async def _contract(cid: int) -> Contract:
    async with AsyncSessionLocal() as db:
        return await db.get(Contract, cid)


async def _generated(gid: int) -> B2BGeneratedContract:
    async with AsyncSessionLocal() as db:
        return await db.get(B2BGeneratedContract, gid)


def _dissolution(signed_on: date, last_day: date, mode: str = "notice") -> dict:
    return {
        "mode": mode,
        "party": "consultant",
        "signed_on": signed_on.isoformat(),
        "last_day": last_day.isoformat(),
    }


# ── Okno jest jedyną drogą do „Zakończony" ───────────────────────────────────


async def test_status_dropdown_cannot_end_a_contract_without_the_form(
    app_client, app_auth_headers
):
    """Kontrakt #674: lista statusu kończyła kontrakt bez powodu i daty."""
    cid, _gid, _ = await _seed(generator_status=None)
    resp = await app_client.patch(
        f"{PATH}/{cid}/status", json={"status": "ended"}, headers=app_auth_headers
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["reason"] == "termination_required"
    assert (await _contract(cid)).status == ContractStatus.active

    full = await app_client.patch(
        f"{PATH}/{cid}", json={"status": "ended"}, headers=app_auth_headers
    )
    assert full.status_code == 409, full.text
    assert (await _contract(cid)).status == ContractStatus.active


# ── Status z daty zakończenia projektu ───────────────────────────────────────


async def test_future_project_end_is_ending_until_that_day_and_keeps_agreement(
    app_client, app_auth_headers
):
    """Projekt kończy się 23.09, wypowiedzenie do 30.09 → do 23.09 „Kończący
    się”; Generator nie rusza się, dopóki kontrakt nie jest „Zakończony”."""
    cid, gid, _ = await _seed()
    project_end = business_today() + timedelta(days=5)
    last_day = business_today() + timedelta(days=12)
    resp = await app_client.post(
        f"{PATH}/{cid}/terminate",
        json={
            "termination_reason": "consultant_resigned",
            "terminated_at": project_end.isoformat(),
            "agreement_termination": _dissolution(business_today(), last_day),
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ending"
    assert body["end_date"] == project_end.isoformat()
    assert body["agreement_termination_mode"] == "notice"
    assert body["agreement_termination_party"] == "consultant"
    assert body["agreement_last_day"] == last_day.isoformat()
    row = await _generated(gid)
    assert row.contract_status == "active"
    assert row.termination_restore is None


async def test_today_project_end_is_still_ending(app_client, app_auth_headers):
    """„Do dnia zakończenia projektu włącznie” — dziś konsultant jeszcze pracuje."""
    cid, _gid, _ = await _seed(generator_status=None)
    resp = await app_client.post(
        f"{PATH}/{cid}/terminate",
        json={
            "termination_reason": "project_ended",
            "terminated_at": business_today().isoformat(),
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "ending"


async def test_nightly_job_ends_the_day_after_and_syncs_generator():
    """Od dnia po dacie końca projektu „Zakończony” — niezależnie od ostatniego
    dnia umowy; Generator przenosi umowę do „Zakończonych” z obiema datami,
    a automatyczna zmiana jest w historii kontraktu."""
    from app.tasks import contract_alerts

    cid, gid, _ = await _seed()
    project_end = business_today() - timedelta(days=1)
    last_day = business_today() + timedelta(days=6)
    async with AsyncSessionLocal() as db:
        c = await db.get(Contract, cid)
        c.status = ContractStatus.ending
        c.end_date = project_end
        c.terminated_at = project_end
        c.termination_reason = "consultant_resigned"
        c.agreement_termination_mode = "notice"
        c.agreement_termination_party = "consultant"
        c.agreement_termination_signed_on = business_today() - timedelta(days=20)
        c.agreement_last_day = last_day
        await db.commit()
    async with AsyncSessionLocal() as db:
        await contract_alerts._promote_statuses(db)
        await db.commit()

    assert (await _contract(cid)).status == ContractStatus.ended
    row = await _generated(gid)
    assert row.contract_status == "closed"
    assert row.closure_date == last_day
    assert row.project_end_date == project_end
    assert row.termination_mode == "notice"
    assert row.closure_reason == "other"
    assert row.closure_reason_other == "Rezygnacja konsultanta"
    async with AsyncSessionLocal() as db:
        auto = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "contract",
                Activity.entity_id == cid,
                Activity.action == "status_auto_changed",
            )
        )
        event = await db.scalar(
            select(B2BGeneratedContractStatusEvent).where(
                B2BGeneratedContractStatusEvent.generated_contract_id == gid
            )
        )
    assert auto is not None and auto.details["to_status"] == "ended"
    assert event is not None
    assert event.from_status == "active" and event.to_status == "closed"
    assert event.details["mode"] == "notice"
    assert event.details["agreement_last_day"] == last_day.isoformat()

    # Drugi przebieg niczego nie dubluje.
    async with AsyncSessionLocal() as db:
        await contract_alerts._promote_statuses(db)
        await db.commit()
    async with AsyncSessionLocal() as db:
        events = (
            await db.scalars(
                select(B2BGeneratedContractStatusEvent).where(
                    B2BGeneratedContractStatusEvent.generated_contract_id == gid
                )
            )
        ).all()
    assert len(events) == 1


# ── Generator przy zakończeniu z datą z przeszłości ──────────────────────────


async def test_past_end_with_dissolution_closes_agreement_immediately(
    app_client, app_auth_headers
):
    cid, gid, _ = await _seed()
    project_end = business_today() - timedelta(days=3)
    resp = await app_client.post(
        f"{PATH}/{cid}/terminate",
        json={
            "termination_reason": "client_budget_cut",
            "terminated_at": project_end.isoformat(),
            "agreement_termination": _dissolution(
                project_end, project_end, mode="mutual_agreement"
            ),
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "ended"
    row = await _generated(gid)
    assert row.contract_status == "closed"
    assert row.closure_reason == "no_client_budget"
    assert row.termination_mode == "mutual_agreement"
    assert row.project_end_date == project_end

    listed = await app_client.get(
        "/api/b2b-generator/generated",
        params={
            "q": row.contract_number,
            "contract_status": "closed",
            "termination_mode": "mutual_agreement",
        },
        headers=app_auth_headers,
    )
    assert listed.status_code == 200, listed.text
    [item] = listed.json()
    assert item["project_end_date"] == project_end.isoformat()
    assert item["closure_date"] == project_end.isoformat()
    assert item["termination_mode"] == "mutual_agreement"
    other_mode = await app_client.get(
        "/api/b2b-generator/generated",
        params={"q": row.contract_number, "termination_mode": "notice"},
        headers=app_auth_headers,
    )
    assert other_mode.json() == []


async def test_project_end_without_dissolution_moves_agreement_to_no_project(
    app_client, app_auth_headers
):
    cid, gid, _ = await _seed()
    project_end = business_today() - timedelta(days=2)
    resp = await app_client.post(
        f"{PATH}/{cid}/terminate",
        json={
            "termination_reason": "project_ended",
            "terminated_at": project_end.isoformat(),
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    row = await _generated(gid)
    assert row.contract_status == "suspended"
    assert row.closure_reason == "project_completed"
    assert row.closure_date == project_end
    assert row.termination_mode is None


async def test_other_active_project_keeps_agreement_current(
    app_client, app_auth_headers
):
    """Konsultant z innym trwającym projektem: umowa zostaje w bieżących."""
    cid, gid, candidate_id = await _seed()
    await _seed(candidate_id=candidate_id, generator_status=None)
    resp = await app_client.post(
        f"{PATH}/{cid}/terminate",
        json={
            "termination_reason": "project_ended",
            "terminated_at": (business_today() - timedelta(days=1)).isoformat(),
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert (await _generated(gid)).contract_status == "active"


async def test_unlinked_agreement_of_the_same_person_is_found(
    app_client, app_auth_headers
):
    """Umowy sprzed automatyzacji podpisu nie mają `contract_id` — umowa B2B
    jest umową z osobą, więc szukamy jej po kandydacie."""
    cid, gid, _ = await _seed(link_generator=False)
    resp = await app_client.post(
        f"{PATH}/{cid}/terminate",
        json={
            "termination_reason": "project_ended",
            "terminated_at": (business_today() - timedelta(days=1)).isoformat(),
            "agreement_termination": _dissolution(
                business_today() - timedelta(days=10),
                business_today() - timedelta(days=1),
            ),
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert (await _generated(gid)).contract_status == "closed"


async def test_last_day_before_signing_is_rejected(app_client, app_auth_headers):
    cid, _gid, _ = await _seed(generator_status=None)
    resp = await app_client.post(
        f"{PATH}/{cid}/terminate",
        json={
            "termination_reason": "project_ended",
            "terminated_at": business_today().isoformat(),
            "agreement_termination": _dissolution(
                business_today(), business_today() - timedelta(days=1)
            ),
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text
    assert (await _contract(cid)).status == ContractStatus.active


# ── „Cofnij zakończenie" i powrót po przerwie ────────────────────────────────


async def test_undo_restores_agreement_and_clears_dissolution(
    app_client, app_auth_headers
):
    cid, gid, _ = await _seed(generator_status="suspended")
    project_end = business_today() - timedelta(days=1)
    ended = await app_client.post(
        f"{PATH}/{cid}/terminate",
        json={
            "termination_reason": "project_ended",
            "terminated_at": project_end.isoformat(),
            "agreement_termination": _dissolution(project_end, project_end),
        },
        headers=app_auth_headers,
    )
    assert ended.status_code == 200, ended.text
    assert (await _generated(gid)).contract_status == "closed"

    undo = await app_client.patch(
        f"{PATH}/{cid}/status", json={"status": "active"}, headers=app_auth_headers
    )
    assert undo.status_code == 200, undo.text
    body = undo.json()
    assert body["status"] == "active"
    assert body["end_date"] is None
    assert body["agreement_termination_mode"] is None
    assert body["agreement_last_day"] is None
    row = await _generated(gid)
    assert row.contract_status == "suspended"
    assert row.closure_reason == "project_completed"
    assert row.closure_date == business_today() - timedelta(days=60)
    assert row.termination_mode is None
    assert row.termination_restore is None


async def test_patching_a_later_end_date_reopens_through_the_lifecycle(
    app_client, app_auth_headers
):
    """Audyt 25.09.2026: nowa data końca na ZAKOŃCZONEJ umowie zapisywała
    status wprost — Generator zostawał w „Umowach bez projektu”, nie było
    wpisu `contract_reopened`, migawka zakończenia wisiała otwarta, a umowa
    wypowiedziana z datą przyszłą dostawała „Aktywny” zamiast „Kończący się”."""
    from app.models.contract_termination_snapshot import (
        SNAPSHOT_STATUS_SUPERSEDED,
        ContractTerminationSnapshot,
    )

    cid, gid, _ = await _seed()
    ended = await app_client.post(
        f"{PATH}/{cid}/terminate",
        json={
            "termination_reason": "project_ended",
            "terminated_at": (business_today() - timedelta(days=2)).isoformat(),
        },
        headers=app_auth_headers,
    )
    assert ended.status_code == 200, ended.text
    assert ended.json()["status"] == "ended"
    assert (await _generated(gid)).contract_status == "suspended"

    later = business_today() + timedelta(days=20)
    resp = await app_client.patch(
        f"{PATH}/{cid}", json={"end_date": later.isoformat()}, headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "ending"
    assert resp.json()["end_date"] == later.isoformat()
    assert (await _generated(gid)).contract_status == "active"
    async with AsyncSessionLocal() as db:
        actions = set(
            (
                await db.scalars(
                    select(Activity.action).where(
                        Activity.entity_type == "contract", Activity.entity_id == cid
                    )
                )
            ).all()
        )
        snapshots = set(
            (
                await db.scalars(
                    select(ContractTerminationSnapshot.status).where(
                        ContractTerminationSnapshot.contract_id == cid
                    )
                )
            ).all()
        )
    assert "contract_reopened" in actions
    assert snapshots == {SNAPSHOT_STATUS_SUPERSEDED}


async def test_later_end_date_on_dissolved_contract_keeps_the_dissolution(
    app_client, app_auth_headers
):
    """Przegląd PR #1833: umowa z podpisanym rozwiązaniem i nową, późniejszą
    datą końca to korekta daty, nie reaktywacja. Rozwiązanie i wiersz
    Generatora („Zakończone”) zostają, a umowa do tej daty jest „Kończący się”
    — dawniej `undo_contract_termination` kasował rozwiązanie, więc po nowej
    dacie Generator lądował w „Umowach bez projektu”."""
    cid, gid, _ = await _seed()
    project_end = business_today() - timedelta(days=3)
    ended = await app_client.post(
        f"{PATH}/{cid}/terminate",
        json={
            "termination_reason": "client_budget_cut",
            "terminated_at": project_end.isoformat(),
            "agreement_termination": _dissolution(
                project_end, project_end, mode="mutual_agreement"
            ),
        },
        headers=app_auth_headers,
    )
    assert ended.status_code == 200, ended.text
    assert (await _generated(gid)).contract_status == "closed"

    later = business_today() + timedelta(days=20)
    resp = await app_client.patch(
        f"{PATH}/{cid}", json={"end_date": later.isoformat()}, headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ending"
    assert body["end_date"] == later.isoformat()
    assert body["agreement_termination_mode"] == "mutual_agreement"
    assert (await _generated(gid)).contract_status == "closed"


async def test_unrelated_patch_on_dissolved_contract_does_not_undo_the_termination(
    app_client, app_auth_headers
):
    """Audyt 25.09.2026, runda 2: PATCH innego pola (notatka przekazania) na
    zakończonej umowie bez daty końca szedł gałęzią reaktywacji — a ta przez
    `undo_contract_termination` kasowała podpisane rozwiązanie i przestawiała
    wiersz Generatora. Bez zmiany daty zostaje wyłącznie leczenie statusu."""
    cid, gid, _ = await _seed()
    project_end = business_today() - timedelta(days=3)
    ended = await app_client.post(
        f"{PATH}/{cid}/terminate",
        json={
            "termination_reason": "client_budget_cut",
            "terminated_at": project_end.isoformat(),
            "agreement_termination": _dissolution(
                project_end, project_end, mode="mutual_agreement"
            ),
        },
        headers=app_auth_headers,
    )
    assert ended.status_code == 200, ended.text
    assert (await _generated(gid)).contract_status == "closed"
    # Stan zastany: zakończona umowa z rozwiązaniem, ale bez daty końca.
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, cid)
        contract.end_date = None
        await db.commit()

    resp = await app_client.patch(
        f"{PATH}/{cid}",
        json={"handover_notes": "przekazanie po projekcie"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["agreement_termination_mode"] == "mutual_agreement"
    assert body["terminated_at"] == project_end.isoformat()
    row = await _generated(gid)
    assert row.contract_status == "closed"
    assert row.termination_mode == "mutual_agreement"
    async with AsyncSessionLocal() as db:
        actions = set(
            (
                await db.scalars(
                    select(Activity.action).where(
                        Activity.entity_type == "contract", Activity.entity_id == cid
                    )
                )
            ).all()
        )
    assert "contract_reopened" not in actions


async def test_return_after_break_creates_follow_up_agreement():
    from app.services.contract_lifecycle import sync_contract_to_live_order

    cid, gid, _ = await _seed()
    project_end = business_today() - timedelta(days=40)
    async with AsyncSessionLocal() as db:
        c = await db.get(Contract, cid)
        c.end_date = project_end
        c.terminated_at = project_end
        c.termination_reason = ContractTerminationReason.project_ended
        c.status = ContractStatus.ended
        c.agreement_termination_mode = "notice"
        c.agreement_termination_party = "company"
        c.agreement_termination_signed_on = project_end - timedelta(days=30)
        c.agreement_last_day = project_end
        from app.services.contract_termination_sync import (
            sync_generator_after_contract_ended,
        )

        assert await sync_generator_after_contract_ended(db, c, actor_id=None) == 1
        await db.commit()
    async with AsyncSessionLocal() as db:
        c = await db.get(Contract, cid)
        changed = await sync_contract_to_live_order(
            db,
            c,
            order_start=business_today() - timedelta(days=1),
            order_end=None,
            actor_id=None,
            today=business_today(),
        )
        await db.commit()
    assert changed is True
    contract = await _contract(cid)
    assert contract.status == ContractStatus.active
    assert contract.agreement_termination_mode is None
    previous = await _generated(gid)
    assert previous.contract_status == "closed"
    assert previous.termination_mode == "notice"
    async with AsyncSessionLocal() as db:
        follow_up = await db.scalar(
            select(B2BGeneratedContract).where(
                B2BGeneratedContract.previous_generated_contract_id == gid
            )
        )
    assert follow_up is not None
    assert follow_up.contract_status == "in_progress"
    assert follow_up.signature_status == "unsigned"
    assert follow_up.contract_id == cid
    assert follow_up.contract_number != previous.contract_number
    assert follow_up.render_payload["contract_number"] == follow_up.contract_number


async def test_termination_reversal_restores_the_generator_agreement(
    app_client, app_auth_headers
):
    """„Cofnij zakończenie" (``/termination-reversal``) domyka też Generator:
    umowa wraca do stanu sprzed zakończenia, dane rozwiązania znikają."""
    cid, gid, _ = await _seed()
    project_end = business_today() - timedelta(days=1)
    ended = await app_client.post(
        f"{PATH}/{cid}/terminate",
        json={
            "termination_reason": "project_ended",
            "terminated_at": project_end.isoformat(),
            "agreement_termination": _dissolution(project_end, project_end),
        },
        headers=app_auth_headers,
    )
    assert ended.status_code == 200, ended.text
    assert (await _generated(gid)).contract_status == "closed"

    resp = await app_client.post(
        f"{PATH}/{cid}/termination-reversal", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    contract = await _contract(cid)
    assert contract.status == ContractStatus.active
    assert contract.agreement_termination_mode is None
    assert contract.agreement_last_day is None
    row = await _generated(gid)
    assert row.contract_status == "active"
    assert row.closure_reason is None
    assert row.termination_mode is None
    assert row.termination_restore is None


async def test_return_after_break_endpoint_links_a_new_agreement(
    app_client, app_auth_headers
):
    """„Powrót po przerwie" (nowy kontrakt) przy rozwiązanej umowie zakłada
    nową umowę w Generatorze, powiązaną z poprzednią i z NOWYM kontraktem."""
    cid, gid, _ = await _seed()
    project_end = business_today() - timedelta(days=30)
    ended = await app_client.post(
        f"{PATH}/{cid}/terminate",
        json={
            "termination_reason": "project_ended",
            "terminated_at": project_end.isoformat(),
            "agreement_termination": _dissolution(project_end, project_end),
        },
        headers=app_auth_headers,
    )
    assert ended.status_code == 200, ended.text

    start = business_today() + timedelta(days=5)
    resp = await app_client.post(
        f"{PATH}/{cid}/return-after-break",
        json={"start_date": start.isoformat()},
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    new_id = resp.json()["contract_id"]

    previous = await _generated(gid)
    assert previous.contract_status == "closed"
    assert previous.contract_id == cid
    async with AsyncSessionLocal() as db:
        follow_up = await db.scalar(
            select(B2BGeneratedContract).where(
                B2BGeneratedContract.previous_generated_contract_id == gid
            )
        )
    assert follow_up is not None
    assert follow_up.contract_id == new_id
    assert follow_up.contract_status == "in_progress"
    # Poprzedni kontrakt zostaje zakończony razem z danymi rozwiązania umowy.
    old = await _contract(cid)
    assert old.status == ContractStatus.ended
    assert old.agreement_termination_mode == "notice"


# ── Zbiorcze „Oznacz zakończone" = to samo okno ──────────────────────────────


async def test_bulk_end_applies_the_same_form_to_every_contract(
    app_client, app_auth_headers
):
    first, gid_a, _ = await _seed()
    second, gid_b, _ = await _seed()
    project_end = business_today() - timedelta(days=1)
    resp = await app_client.post(
        f"{PATH}/bulk-mark-ended",
        params=[("ids", first), ("ids", second)],
        json={
            "termination_reason": "client_budget_cut",
            "terminated_at": project_end.isoformat(),
            "termination_lessons": "Klient — cięcie budżetu Q4",
            "agreement_termination": _dissolution(project_end, project_end),
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    for cid, gid in ((first, gid_a), (second, gid_b)):
        contract = await _contract(cid)
        assert contract.status == ContractStatus.ended
        assert contract.termination_lessons == "Klient — cięcie budżetu Q4"
        assert contract.agreement_last_day == project_end
        assert (await _generated(gid)).contract_status == "closed"


async def test_notice_period_months_is_editable(app_client, app_auth_headers):
    cid, _gid, _ = await _seed(generator_status=None)
    resp = await app_client.patch(
        f"{PATH}/{cid}", json={"notice_period_months": 1}, headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["notice_period_months"] == 1
    bad = await app_client.patch(
        f"{PATH}/{cid}", json={"notice_period_months": 0}, headers=app_auth_headers
    )
    assert bad.status_code == 422
