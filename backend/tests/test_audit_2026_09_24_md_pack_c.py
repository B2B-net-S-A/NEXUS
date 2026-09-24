"""Audyt 24.09.2026, pakiet C: sprawy offboardingu MD, wyczerpanie, import MD.

Każdy test odtwarza jedno znalezisko (H6–H9, M8, M12, M13, U14): na kodzie
sprzed poprawki pada, po niej przechodzi. Nazwiska i numery są zmyślone,
daty liczone od ``business_today()``.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.scheduling import business_today

pytestmark = pytest.mark.asyncio


def _prev_period() -> str:
    first = business_today().replace(day=1)
    return (first - timedelta(days=1)).strftime("%Y-%m")


async def _admin_id() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.user import User

    async with AsyncSessionLocal() as db:
        return await db.scalar(select(User.id).order_by(User.id).limit(1))


async def _seed_case_alert(*, case_id: int, client_id: int, group_id: int) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.dl_alert import ALERT_MD_CONSULTANT_ENDED, DlAlert

    user_id = await _admin_id()
    async with AsyncSessionLocal() as db:
        alert = DlAlert(
            alert_type=ALERT_MD_CONSULTANT_ENDED,
            user_id=user_id,
            client_id=client_id,
            order_group_id=group_id,
            offboarding_case_id=case_id,
            title="Decyzja MD po zakończeniu współpracy",
            message="Decyzja MD po zakończeniu współpracy",
            dedupe_key=f"test-pack-c-{uuid.uuid4().hex}",
            event_key=f"{ALERT_MD_CONSULTANT_ENDED}:case:{case_id}:{user_id}",
        )
        db.add(alert)
        await db.commit()
        return alert.id


async def _alert_status(alert_id: int) -> str:
    from app.core.database import AsyncSessionLocal
    from app.models.dl_alert import DlAlert

    async with AsyncSessionLocal() as db:
        return (await db.get(DlAlert, alert_id)).status


async def _case(case_id: int):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order_offboarding import ClientOrderOffboardingCase

    async with AsyncSessionLocal() as db:
        return await db.get(ClientOrderOffboardingCase, case_id)


async def _event_descriptions(app_client, headers, client_id, group_id) -> str:
    events = await app_client.get(
        f"/api/clients/{client_id}/order-groups/{group_id}/events",
        headers=headers,
    )
    assert events.status_code == 200, events.text
    return " | ".join(e["description"] for e in events.json()["events"])


# ── H8: decyzja człowieka nie zamyka sprawy „automatycznie” ────────────────


async def test_dl_transfer_decision_is_not_auto_closed_as_used_up(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from tests.test_order_line_takeover import _add_recipient, _enable_multi, _seed

    seed = await _seed()
    _enable_multi(monkeypatch, seed["client_id"])
    recipient = await _add_recipient(seed)

    resp = await app_client.post(
        f"/api/clients/{seed['client_id']}/order-groups/{seed['group_id']}"
        f"/offboarding-cases/{seed['case_id']}/resolve",
        json={
            "action": "transfer",
            "target_order_id": recipient,
            "md_transfer_method": "one_to_one",
            "expected_version": 1,
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text

    case = await _case(seed["case_id"])
    assert case.resolution == "transfer"
    # Migawka zostaje pulą, o której zdecydował człowiek — nie 0.
    assert Decimal(str(case.remaining_md_snapshot)) == Decimal("187")
    assert not (case.resolution_payload or {}).get("automatic")
    history = await _event_descriptions(
        app_client, app_auth_headers, seed["client_id"], seed["group_id"]
    )
    assert "wykorzystana w całości (0 MD)" not in history, history


async def test_takeover_closes_the_dl_alert_and_is_not_auto_closed(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from tests.test_order_line_takeover import _enable_multi, _seed, _takeover_url

    seed = await _seed()
    _enable_multi(monkeypatch, seed["client_id"])
    alert_id = await _seed_case_alert(
        case_id=seed["case_id"], client_id=seed["client_id"], group_id=seed["group_id"]
    )

    resp = await app_client.post(
        _takeover_url(seed),
        json={
            "contract_id": seed["kamila_contract_id"],
            "departing_order_id": seed["line_id"],
            "entry_date": (seed["departure"] + timedelta(days=1)).isoformat(),
            "rate_cost": 680,
            "rate_revenue": 800,
            "expected_case_version": 1,
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text

    # Przejęcie rozstrzyga sprawę — alert DL jest obsłużony, nie wisi dalej.
    assert await _alert_status(alert_id) == "handled"
    case = await _case(seed["case_id"])
    assert case.resolution == "transfer"
    assert Decimal(str(case.remaining_md_snapshot)) == Decimal("187")
    history = await _event_descriptions(
        app_client, app_auth_headers, seed["client_id"], seed["group_id"]
    )
    assert "wykorzystana w całości (0 MD)" not in history, history


async def test_import_that_uses_up_the_pool_closes_the_case_and_its_alert(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Automatyczne zamknięcie (import wyzerował pulę) zdejmuje też kartę DL."""
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder
    from app.services.client_order_lines import upsert_consumption
    from tests.test_order_line_takeover import _enable_multi, _seed

    seed = await _seed()
    _enable_multi(monkeypatch, seed["client_id"])
    alert_id = await _seed_case_alert(
        case_id=seed["case_id"], client_id=seed["client_id"], group_id=seed["group_id"]
    )
    async with AsyncSessionLocal() as db:
        line = await db.get(ClientOrder, seed["line_id"])
        await upsert_consumption(
            db,
            order=line,
            period_month=seed["departure"].strftime("%Y-%m"),
            md_reported=Decimal("187"),
        )
        await db.commit()

    case = await _case(seed["case_id"])
    assert case.status == "resolved"
    assert (case.resolution_payload or {}).get("automatic") is True
    assert await _alert_status(alert_id) == "resolved"


# ── H9: wyczerpanie zamyka zamówienie z dniem przeliczenia ─────────────────


async def test_exhausted_by_a_late_report_the_order_still_settles_this_month(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Raport za poprzedni miesiąc wyczerpał pulę — data zakończenia to dzień
    przeliczenia, więc import za bieżący miesiąc nadal znajduje linię."""
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder
    from app.services.client_order_lines import (
        md_lines_settling_in_month,
        upsert_consumption,
    )
    from tests.test_bik_md_exhaustion_lifecycle import _bik_group, _group_state

    _client_id, group = await _bik_group(app_client, app_auth_headers, monkeypatch)
    async with AsyncSessionLocal() as db:
        for line in group["lines"]:
            order = await db.get(ClientOrder, line["id"])
            await upsert_consumption(
                db,
                order=order,
                period_month=_prev_period(),
                md_reported=Decimal(str(line["md_total"])),
            )
        await db.commit()

    state, _ = await _group_state(group["id"])
    assert state.status == "completed"
    assert state.closure_date == business_today()

    async with AsyncSessionLocal() as db:
        settling = await md_lines_settling_in_month(
            db, business_today().strftime("%Y-%m")
        )
    line_ids = {line["id"] for line in group["lines"]}
    assert line_ids <= {match.order.id for match in settling}


# ── M8: sprawa zamknięta automatycznie nie blokuje „Cofnij zakończenie” ────


async def test_auto_closed_case_does_not_block_termination_reversal(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder
    from app.services.client_order_lines import upsert_consumption
    from tests.test_contract_termination_reversal import (
        _enable_multi,
        _ended_on,
        _pending_cases,
        _seed_active_md_consultant,
        _terminate,
    )

    seed = await _seed_active_md_consultant()
    _enable_multi(monkeypatch, seed["client_id"])
    await _terminate(app_client, app_auth_headers, seed["contract_id"])
    [case_id] = await _pending_cases(seed["contract_id"])

    # Zaległy raport za miesiąc zejścia zjada resztę puli (259 MD) — sprawa
    # zamyka się sama jako „usunięto 0 MD”.
    async with AsyncSessionLocal() as db:
        line = await db.get(ClientOrder, seed["line_id"])
        await upsert_consumption(
            db,
            order=line,
            period_month=_ended_on().strftime("%Y-%m"),
            md_reported=Decimal("259"),
        )
        await db.commit()
    case = await _case(case_id)
    assert case.status == "resolved"
    assert case.resolution_payload.get("automatic") is True

    preview = await app_client.get(
        f"/api/contracts/{seed['contract_id']}/termination-reversal",
        headers=app_auth_headers,
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert [b["code"] for b in body["blockers"]] == [], body["blockers"]
    assert body["decision_cases_removed"] == 1

    done = await app_client.post(
        f"/api/contracts/{seed['contract_id']}/termination-reversal",
        headers=app_auth_headers,
    )
    assert done.status_code == 200, done.text
    assert await _pending_cases(seed["contract_id"]) == []


# ── H6: dawna linia Polkomtela nie wiąże numeru z „Uwag” u innego klienta ──


async def _person_on_two_clients() -> dict:
    """Ta sama osoba: kontrakt u „Polkomtela” (dawno) i u innego klienta (dziś)."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus
    from tests.test_md_import_order_number_assignment import _old_start

    suffix = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        polkomtel = Client(name=f"PackC-Polk-{suffix}")
        other = Client(name=f"PackC-Bnp-{suffix}")
        cand = Candidate(
            name="Oskar",
            lastname=f"Dwuklientowy-{suffix}",
            email=f"packc-{suffix}@example.com",
        )
        db.add_all([polkomtel, other, cand])
        await db.commit()
        # Aktywny na czas założenia zamówienia; test kończy go w bazie.
        old_contract = Contract(
            candidate_id=cand.id,
            client_id=polkomtel.id,
            status=ContractStatus.active,
            start_date=_old_start() - timedelta(days=200),
            rate_candidate=Decimal("900"),
            rate_client=Decimal("1100"),
        )
        new_contract = Contract(
            candidate_id=cand.id,
            client_id=other.id,
            status=ContractStatus.active,
            start_date=_old_start(),
            rate_candidate=Decimal("900"),
            rate_client=Decimal("1100"),
        )
        db.add_all([old_contract, new_contract])
        await db.commit()
        return {
            "polkomtel": polkomtel.id,
            "other": other.id,
            "old_contract": old_contract.id,
            "new_contract": new_contract.id,
            "name": f"{cand.name} {cand.lastname}",
        }


async def test_old_polkomtel_line_does_not_bind_a_note_number_at_another_client(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.client_order_group import GROUP_STATUS_COMPLETED, ClientOrderGroup
    from app.models.contract import Contract, ContractStatus
    from app.services import finance_order_matching
    from app.services.order_policies.polkomtel import CLIENT_IDS_ENV
    from tests.test_md_import_order_number_assignment import (
        _consumptions,
        _create_group,
        _enable_multi,
        _finance_headers,
        _import,
        _old_start,
        _sheet,
    )

    seed = await _person_on_two_clients()
    _enable_multi(monkeypatch, seed["polkomtel"], seed["other"])
    monkeypatch.setattr(
        finance_order_matching, "POLKOMTEL_CLIENT_ID", seed["polkomtel"]
    )
    monkeypatch.setenv(CLIENT_IDS_ENV, str(seed["polkomtel"]))

    old = await _create_group(
        app_client,
        app_auth_headers,
        seed["polkomtel"],
        seed["old_contract"],
        number=f"SAP 45{uuid.uuid4().int % 10**8:08d}",
        start=_old_start() - timedelta(days=200),
        end=None,
        md_total=40,
    )
    async with AsyncSessionLocal() as db:
        line = await db.get(ClientOrder, old["lines"][0]["id"])
        line.status = ClientOrderStatus.completed
        line.end_date = _old_start() - timedelta(days=1)
        group = await db.get(ClientOrderGroup, old["id"])
        group.status = GROUP_STATUS_COMPLETED
        group.closure_date = _old_start() - timedelta(days=1)
        contract = await db.get(Contract, seed["old_contract"])
        contract.status = ContractStatus.ended
        contract.end_date = _old_start() - timedelta(days=1)
        await db.commit()
    current = await _create_group(
        app_client,
        app_auth_headers,
        seed["other"],
        seed["new_contract"],
        number=f"87_{uuid.uuid4().hex[:4]}",
        start=_old_start(),
        end=None,
        md_total=60,
    )
    current_line = current["lines"][0]["id"]

    finance = await _finance_headers(app_client)
    detail = await _import(
        app_client, finance, _sheet([(seed["name"], 12, "delegacja 445", 0)])
    )

    [row] = detail["rows"]
    assert row["status"] == "applied", row
    assert row["matched_order_id"] == current_line
    assert list((await _consumptions(current_line)).values()) == [Decimal("12")]


# ── H7: zatwierdzenie przekroczenia wspólnej puli nie nadpisuje nowszej paczki ─


async def test_approving_an_old_shared_pool_batch_does_not_overwrite_a_newer_one(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from tests.test_md_import_shared_budget import (
        _create_shared_md_group,
        _enable_cyfrowy_polsat,
        _group_from_list,
    )
    from tests.test_order_lifecycle_and_cost import (
        _finance_headers,
        _import_sheet,
        _seed_client_with_contracts,
        _sheet,
    )

    client_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_cyfrowy_polsat(monkeypatch, client_id)
    number = f"45008{uuid.uuid4().int % 10**5:05d}"
    group = await _create_shared_md_group(
        app_client,
        app_auth_headers,
        client_id,
        contracts[0],
        order_number=number,
        budget=10,
    )
    finance = await _finance_headers(app_client)

    old = await _import_sheet(
        app_client, finance, _sheet([(names[0], 15, f"SAP {number}", 0)])
    )
    [held] = [r for r in old["rows"] if r["status"] == "overflow"]
    newer = await _import_sheet(
        app_client, finance, _sheet([(names[0], 8, f"SAP {number}", 0)])
    )
    assert newer["rows"][0]["status"] == "applied", newer["rows"]

    approved = await app_client.post(
        f"/api/md-consumption/imports/{old['id']}/rows/{held['id']}/assign",
        json={"order_id": held["matched_order_id"], "confirm_overflow": True},
        headers=finance,
    )
    assert approved.status_code == 409, approved.text
    assert "nowszego importu" in approved.json()["detail"]
    body = await _group_from_list(app_client, app_auth_headers, client_id, group["id"])
    assert body["md_budget_used"] == pytest.approx(8.0)


# ── M12: replay Polkomtela nie księguje przekroczenia bez zatwierdzenia ────


async def test_polkomtel_replay_keeps_an_overflow_row_waiting_for_approval(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder
    from app.services import finance_order_matching
    from tests.test_order_lifecycle_and_cost import (
        _create_group,
        _enable_multi,
        _finance_headers,
        _import_sheet,
        _md_line,
        _seed_client_with_contracts,
        _sheet,
    )

    client_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    monkeypatch.setattr(finance_order_matching, "POLKOMTEL_CLIENT_ID", client_id)
    digits = f"45{uuid.uuid4().int % 10**8:08d}"
    group = await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        [_md_line(contracts[0], input_value=8)],
        order_number=f"SAP {digits}",
    )
    line_id = group["lines"][0]["id"]
    finance = await _finance_headers(app_client)

    imported = await _import_sheet(
        app_client, finance, _sheet([(names[0], 12, digits, 0)])
    )
    [row] = imported["rows"]
    assert row["status"] == "overflow", row

    endpoint = f"/api/md-consumption/imports/{imported['id']}/reprocess-polkomtel"
    applied = await app_client.post(endpoint, json={"apply": True}, headers=finance)
    assert applied.status_code == 200, applied.text

    detail = await app_client.get(
        f"/api/md-consumption/imports/{imported['id']}", headers=finance
    )
    assert detail.status_code == 200, detail.text
    [after] = detail.json()["rows"]
    assert after["status"] == "overflow", after
    async with AsyncSessionLocal() as db:
        line = await db.get(ClientOrder, line_id)
        assert Decimal(str(line.md_remaining)) == Decimal("8")


# ── M13: przekroczenie u następcy zamiany wstrzymuje wiersz ────────────────


async def test_late_swap_month_report_that_sinks_the_successor_is_held(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Raport poprzednika za miesiąc zamiany zmniejsza budżet następcy
    (FIN-MD-02); gdy następca zużył już więcej, wiersz czeka na zatwierdzenie."""
    from tests.test_md_import_duplicate_consultant_rows import (
        _finance_headers,
        _sheet,
    )
    from tests.test_multi_consultant_orders import (
        _create_group,
        _enable_for,
        _line_payload,
        _line_total,
        _report_md,
        _seed_client_with_contracts,
        _swap,
    )
    from tests.test_order_lifecycle_and_cost import _import_sheet

    if business_today().day == 1:
        pytest.skip("Poprzednik kończy się w poprzednim miesiącu — brak miesiąca zamiany.")
    client_id, contracts, names = await _seed_client_with_contracts(2)
    _enable_for(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_line_payload(contracts[0])]
    )
    predecessor = group["lines"][0]["id"]
    successor = await _swap(app_client, app_auth_headers, client_id, group, contracts[1])
    assert await _line_total(successor) == Decimal("50")
    await _report_md(successor, "45")

    finance = await _finance_headers(app_client)
    detail = await _import_sheet(app_client, finance, _sheet([(names[0], 10)]))

    [row] = detail["rows"]
    assert row["status"] == "overflow", row
    assert row["matched_order_id"] == predecessor
    # Nic nie zostało zaksięgowane — budżet następcy nietknięty.
    assert await _line_total(successor) == Decimal("50")
