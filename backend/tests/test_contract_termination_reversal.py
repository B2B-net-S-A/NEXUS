"""„Cofnij zakończenie" i „Powrót po przerwie" (ticket 09.2026, 0365).

Zgłoszenie: kontrakt zakończono przez pomyłkę z datą końca w przeszłości,
a „aktywacja ponownie" wróciła tylko z kontraktem — zamówienie MD zostawiło
konsultanta w „Zakończonych" ze sprawą „Wymagana decyzja o pozostałej puli
MD". Testy idą prawdziwą ścieżką: ``POST /terminate`` → podgląd → cofnięcie,
i sprawdzają to, co widzi karta zamówienia: status i datę końca linii, brak
sprawy decyzji, nienaruszone zużycie i pulę MD.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.models.user import UserRole
from tests._jarvis_helpers import make_user

_TODAY = date.today()
_THIS_MONTH_START = _TODAY.replace(day=1)
_ENDED_ON = _THIS_MONTH_START - timedelta(days=1)  # ostatni dzień poprzedniego miesiąca


def _enable_multi(monkeypatch, *client_ids: int) -> None:
    from app.services import multi_consultant_orders as mco

    monkeypatch.setattr(
        mco, "multi_consultant_client_ids", lambda: frozenset(client_ids)
    )


async def _seed_active_md_consultant(*, used_md: Decimal = Decimal("93")) -> dict:
    """Aktywny kontrakt B2B + linia MD (352 MD, stawki 480/600) + zużycie."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.client_order_group import GROUP_STATUS_ACTIVE, ClientOrderGroup
    from app.models.contract import Contract, ContractStatus, ContractType, RateUnit
    from app.models.md_consumption import (
        CONSUMPTION_SOURCE_IMPORT,
        ClientOrderMdConsumption,
    )

    suffix = uuid.uuid4().hex[:6]
    start = _THIS_MONTH_START - timedelta(days=160)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"ReversalClient-{suffix}")
        db.add(client)
        await db.flush()
        candidate = Candidate(
            name="Mateusz",
            lastname=f"Pomylka-{suffix}",
            email=f"reversal-{suffix}@example.com",
        )
        db.add(candidate)
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            status=ContractStatus.active,
            contract_type=ContractType.b2b,
            start_date=start,
            end_date=None,
            rate_candidate=Decimal("60"),
            rate_client=Decimal("75"),
            rate_unit=RateUnit.hourly,
        )
        db.add(contract)
        await db.flush()
        group = ClientOrderGroup(
            client_id=client.id,
            order_number=f"CeZ/{suffix}/2025",
            start_date=start,
            end_date=None,
            status=GROUP_STATUS_ACTIVE,
            order_type=None,
        )
        db.add(group)
        await db.flush()
        line = ClientOrder(
            client_id=client.id,
            contract_id=contract.id,
            order_group_id=group.id,
            title=f"Zamówienie {group.order_number} — Mateusz",
            order_type=None,
            status=ClientOrderStatus.active,
            start_date=start,
            end_date=None,
            md_rate_cost=Decimal("480.00"),
            md_rate_revenue=Decimal("600.00"),
            rate_unit=RateUnit.daily,
            billing_hours_per_month=168,
            currency="PLN",
            rate_client_currency="PLN",
            rate_candidate_currency="PLN",
            md_input_mode="md",
            md_input_value=Decimal("352"),
            md_total=Decimal("352"),
            md_remaining=Decimal("352") - used_md,
            md_manual_adjustment=Decimal("0"),
            filled_at=None,
        )
        db.add(line)
        await db.flush()
        db.add(
            ClientOrderMdConsumption(
                order_id=line.id,
                period_month=(start + timedelta(days=40)).strftime("%Y-%m"),
                md_reported=used_md,
                source=CONSUMPTION_SOURCE_IMPORT,
            )
        )
        await db.commit()
        return {
            "client_id": client.id,
            "candidate_id": candidate.id,
            "candidate_name": f"{candidate.name} {candidate.lastname}",
            "contract_id": contract.id,
            "group_id": group.id,
            "line_id": line.id,
            "order_number": group.order_number,
        }


async def _terminate(app_client: AsyncClient, headers: dict, contract_id: int) -> None:
    resp = await app_client.post(
        f"/api/contracts/{contract_id}/terminate",
        json={
            "termination_reason": "better_offer",
            "terminated_at": _ENDED_ON.isoformat(),
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


async def _line(line_id: int) -> dict:
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder

    async with AsyncSessionLocal() as db:
        line = await db.get(ClientOrder, line_id)
        return {
            "status": line.status.value,
            "end_date": line.end_date,
            "md_total": Decimal(str(line.md_total)),
            "md_remaining": Decimal(str(line.md_remaining)),
            "md_rate_cost": Decimal(str(line.md_rate_cost)),
            "md_rate_revenue": Decimal(str(line.md_rate_revenue)),
        }


async def _pending_cases(contract_id: int) -> list[int]:
    from app.core.database import AsyncSessionLocal
    from app.models.client_order_offboarding import ClientOrderOffboardingCase

    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(ClientOrderOffboardingCase.id).where(
                        ClientOrderOffboardingCase.contract_id == contract_id
                    )
                )
            ).all()
        )


# ── Zapis stanu przy zakończeniu ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_termination_records_the_state_it_overwrites(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    seed = await _seed_active_md_consultant()
    _enable_multi(monkeypatch, seed["client_id"])
    await _terminate(app_client, app_auth_headers, seed["contract_id"])

    from app.core.database import AsyncSessionLocal
    from app.models.contract_termination_snapshot import ContractTerminationSnapshot

    async with AsyncSessionLocal() as db:
        snapshot = await db.scalar(
            select(ContractTerminationSnapshot).where(
                ContractTerminationSnapshot.contract_id == seed["contract_id"]
            )
        )
    assert snapshot is not None and snapshot.status == "open"
    assert snapshot.contract_before["status"] == "active"
    assert snapshot.contract_before["end_date"] is None
    assert snapshot.contract_before["terminated_at"] is None
    [entry] = snapshot.orders
    assert entry["order_id"] == seed["line_id"]
    assert entry["status_before"] == "active"
    assert entry["end_date_before"] is None
    assert entry["group_status_before"] == "active"
    assert entry["status_after"] == "completed"
    assert entry["end_date_after"] == _ENDED_ON.isoformat()


# ── Cofnij zakończenie ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reversal_restores_contract_and_order_line_as_if_nothing_happened(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    seed = await _seed_active_md_consultant()
    _enable_multi(monkeypatch, seed["client_id"])
    await _terminate(app_client, app_auth_headers, seed["contract_id"])
    assert (await _line(seed["line_id"]))["status"] == "completed"
    assert await _pending_cases(seed["contract_id"])

    preview = await app_client.get(
        f"/api/contracts/{seed['contract_id']}/termination-reversal",
        headers=app_auth_headers,
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["source"] == "snapshot"
    assert body["blockers"] == []
    assert body["decision_cases_removed"] == 1
    [order] = body["orders"]
    assert order["order_label"] == seed["order_number"]
    assert order["status_target"] == "active"
    assert order["end_date_target"] is None
    assert order["removes_decision_case"] is True

    resp = await app_client.post(
        f"/api/contracts/{seed['contract_id']}/termination-reversal",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["executed"] is True

    line = await _line(seed["line_id"])
    assert line["status"] == "active"
    assert line["end_date"] is None
    # Zużycie, pula i stawki bez zmian: 93 / 352 MD, zostaje 259.
    assert line["md_total"] == Decimal("352")
    assert line["md_remaining"] == Decimal("259")
    assert line["md_rate_cost"] == Decimal("480.00")
    assert line["md_rate_revenue"] == Decimal("600.00")
    assert await _pending_cases(seed["contract_id"]) == []

    detail = await app_client.get(
        f"/api/contracts/{seed['contract_id']}", headers=app_auth_headers
    )
    data = detail.json()
    assert data["status"] == "active"
    assert data["end_date"] is None
    assert data["terminated_at"] is None
    assert data["termination_reason"] is None
    assert data["termination_reversed_at"] is not None
    assert data["termination_reversed_by_name"] == "Pytest Admin"
    assert data["can_reverse_termination"] is False

    # Karta zamówienia: konsultant w aktywnej obsadzie, bez daty zejścia i bez
    # sprawy decyzji MD.
    groups = await app_client.get(
        f"/api/clients/{seed['client_id']}/order-groups", headers=app_auth_headers
    )
    assert groups.status_code == 200, groups.text
    [group] = [g for g in groups.json()["groups"] if g["id"] == seed["group_id"]]
    [read] = [ln for ln in group["lines"] if ln["id"] == seed["line_id"]]
    assert read["is_active"] is True
    assert read["cooperation_ended_on"] is None
    assert read["offboarding_case"] is None

    # Historia zamówienia i kontraktu mówi, która akcja, kiedy i kto.
    events = await app_client.get(
        f"/api/clients/{seed['client_id']}/order-groups/{seed['group_id']}/events",
        headers=app_auth_headers,
    )
    assert any(
        "Cofnięto zakończenie (pomyłka)" in e["description"]
        for e in events.json()["events"]
    ), events.text
    activity = await app_client.get(
        f"/api/contracts/{seed['contract_id']}/activities", headers=app_auth_headers
    )
    actions = [row["action"] for row in activity.json()]
    assert "termination_reversed" in actions
    assert "terminated" in actions  # wpis o zakończeniu zostaje w historii


@pytest.mark.asyncio
async def test_reversal_is_blocked_by_a_decision_on_the_md_pool(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    seed = await _seed_active_md_consultant()
    _enable_multi(monkeypatch, seed["client_id"])
    await _terminate(app_client, app_auth_headers, seed["contract_id"])
    [case_id] = await _pending_cases(seed["contract_id"])
    decided = await app_client.post(
        f"/api/clients/{seed['client_id']}/order-groups/{seed['group_id']}"
        f"/offboarding-cases/{case_id}/resolve",
        json={"action": "remove", "expected_version": 1},
        headers=app_auth_headers,
    )
    assert decided.status_code == 200, decided.text

    preview = await app_client.get(
        f"/api/contracts/{seed['contract_id']}/termination-reversal",
        headers=app_auth_headers,
    )
    [blocker] = preview.json()["blockers"]
    assert blocker["code"] == "md_pool_decided"
    assert blocker["order_label"] == seed["order_number"]
    assert seed["order_number"] in blocker["message"]
    assert "zamknięcie pozostałej puli MD" in blocker["message"]

    resp = await app_client.post(
        f"/api/contracts/{seed['contract_id']}/termination-reversal",
        headers=app_auth_headers,
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "termination_reversal_blocked"
    assert (await _line(seed["line_id"]))["status"] == "completed"


@pytest.mark.asyncio
async def test_reversal_without_snapshot_uses_order_change_history(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Przypadek ze zgłoszenia: zakończenie sprzed 0365, kontrakt przywrócony
    samą zmianą statusu, linia została w „Zakończonych"."""
    seed = await _seed_active_md_consultant()
    _enable_multi(monkeypatch, seed["client_id"])
    await _terminate(app_client, app_auth_headers, seed["contract_id"])
    reopened = await app_client.patch(
        f"/api/contracts/{seed['contract_id']}/status",
        json={"status": "active"},
        headers=app_auth_headers,
    )
    assert reopened.status_code == 200, reopened.text
    assert (await _line(seed["line_id"]))["status"] == "completed"

    from app.core.database import AsyncSessionLocal
    from app.models.contract_termination_snapshot import ContractTerminationSnapshot

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(ContractTerminationSnapshot).where(
                ContractTerminationSnapshot.contract_id == seed["contract_id"]
            )
        )
        await db.commit()

    detail = await app_client.get(
        f"/api/contracts/{seed['contract_id']}", headers=app_auth_headers
    )
    assert detail.json()["can_reverse_termination"] is True
    assert detail.json()["can_return_after_break"] is False

    preview = await app_client.get(
        f"/api/contracts/{seed['contract_id']}/termination-reversal",
        headers=app_auth_headers,
    )
    body = preview.json()
    assert body["source"] == "history"
    [order] = body["orders"]
    assert order["end_date_source"] == "history"
    assert order["end_date_target"] is None

    resp = await app_client.post(
        f"/api/contracts/{seed['contract_id']}/termination-reversal",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    line = await _line(seed["line_id"])
    assert (line["status"], line["end_date"], line["md_remaining"]) == (
        "active",
        None,
        Decimal("259"),
    )
    assert await _pending_cases(seed["contract_id"]) == []
    detail = await app_client.get(
        f"/api/contracts/{seed['contract_id']}", headers=app_auth_headers
    )
    assert detail.json()["terminated_at"] is None
    assert detail.json()["termination_reversed_at"] is not None


@pytest.mark.asyncio
async def test_reversal_reapplies_md_import_uploaded_while_ended(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    seed = await _seed_active_md_consultant()
    _enable_multi(monkeypatch, seed["client_id"])
    await _terminate(app_client, app_auth_headers, seed["contract_id"])

    from app.core.database import AsyncSessionLocal
    from app.models.md_consumption import (
        IMPORT_ROW_UNMATCHED,
        ClientOrderMdConsumption,
        MdConsumptionImport,
        MdConsumptionImportRow,
    )

    period = _THIS_MONTH_START.strftime("%Y-%m")
    async with AsyncSessionLocal() as db:
        batch = MdConsumptionImport(period_month=period, filename="raport.xlsx")
        db.add(batch)
        await db.flush()
        row = MdConsumptionImportRow(
            import_id=batch.id,
            row_number=2,
            consultant_name=seed["candidate_name"],
            md_reported=Decimal("7"),
            status=IMPORT_ROW_UNMATCHED,
        )
        db.add(row)
        await db.commit()
        row_id = row.id

    preview = await app_client.get(
        f"/api/contracts/{seed['contract_id']}/termination-reversal",
        headers=app_auth_headers,
    )
    [planned] = preview.json()["md_imports"]
    assert planned["row_id"] == row_id and planned["period_month"] == period

    resp = await app_client.post(
        f"/api/contracts/{seed['contract_id']}/termination-reversal",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text

    async with AsyncSessionLocal() as db:
        stored = await db.get(MdConsumptionImportRow, row_id)
        consumption = await db.scalar(
            select(ClientOrderMdConsumption).where(
                ClientOrderMdConsumption.order_id == seed["line_id"],
                ClientOrderMdConsumption.period_month == period,
            )
        )
    assert stored.status == "applied" and stored.matched_order_id == seed["line_id"]
    assert consumption is not None and Decimal(str(consumption.md_reported)) == 7
    assert (await _line(seed["line_id"]))["md_remaining"] == Decimal("252")


@pytest.mark.asyncio
async def test_reversal_refuses_a_contract_that_was_never_terminated(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    seed = await _seed_active_md_consultant()
    _enable_multi(monkeypatch, seed["client_id"])
    resp = await app_client.post(
        f"/api/contracts/{seed['contract_id']}/termination-reversal",
        headers=app_auth_headers,
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "nothing_to_reverse"


# ── Powrót po przerwie ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_return_after_break_creates_a_linked_draft_and_a_draft_assignment(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    seed = await _seed_active_md_consultant()
    _enable_multi(monkeypatch, seed["client_id"])
    await _terminate(app_client, app_auth_headers, seed["contract_id"])

    too_early = await app_client.post(
        f"/api/contracts/{seed['contract_id']}/return-after-break",
        json={"start_date": _ENDED_ON.isoformat()},
        headers=app_auth_headers,
    )
    assert too_early.status_code == 422

    start = _TODAY + timedelta(days=10)
    resp = await app_client.post(
        f"/api/contracts/{seed['contract_id']}/return-after-break",
        json={"start_date": start.isoformat()},
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    new_id = resp.json()["contract_id"]
    [new_order] = resp.json()["orders"]
    assert new_order["kind"] == "group"

    new = (
        await app_client.get(f"/api/contracts/{new_id}", headers=app_auth_headers)
    ).json()
    assert new["status"] == "draft"
    assert new["returned_from_contract_id"] == seed["contract_id"]
    assert new["start_date"] == start.isoformat()
    assert new["end_date"] is None

    old = (
        await app_client.get(
            f"/api/contracts/{seed['contract_id']}", headers=app_auth_headers
        )
    ).json()
    assert old["status"] == "ended"  # poprzedni kontrakt bez zmian
    assert old["return_contract_id"] == new_id
    assert old["can_return_after_break"] is False
    assert (await _line(seed["line_id"]))["status"] == "completed"

    groups = await app_client.get(
        f"/api/clients/{seed['client_id']}/order-groups", headers=app_auth_headers
    )
    [group] = [g for g in groups.json()["groups"] if g["id"] == seed["group_id"]]
    [draft] = [ln for ln in group["lines"] if ln["contract_id"] == new_id]
    assert draft["status"] == "draft"
    assert draft["returned_from_contract_id"] == seed["contract_id"]
    assert draft["start_date"] == start.isoformat()

    again = await app_client.post(
        f"/api/contracts/{seed['contract_id']}/return-after-break",
        json={"start_date": start.isoformat()},
        headers=app_auth_headers,
    )
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "return_already_created"

    # Uzupełnienie szkicu przypisania (budżet + stawki) wprowadza osobę do
    # aktywnej obsady, jak linię dodaną od razu z kompletem.
    filled = await app_client.patch(
        f"/api/clients/{seed['client_id']}/order-groups/{seed['group_id']}"
        f"/lines/{draft['id']}",
        json={
            "rate_cost": "480.00",
            "rate_revenue": "600.00",
            "input_mode": "md",
            "input_value": "100",
        },
        headers=app_auth_headers,
    )
    assert filled.status_code == 200, filled.text
    assert filled.json()["status"] == "active"


@pytest.mark.asyncio
async def test_return_after_break_requires_an_ended_contract(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    seed = await _seed_active_md_consultant()
    _enable_multi(monkeypatch, seed["client_id"])
    resp = await app_client.post(
        f"/api/contracts/{seed['contract_id']}/return-after-break",
        json={"start_date": (_TODAY + timedelta(days=3)).isoformat()},
        headers=app_auth_headers,
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "contract_not_ended"


# ── Kto może ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role,expected",
    [
        (UserRole.finance, 200),
        (UserRole.talent_community_manager, 200),
        (UserRole.delivery_lead, 403),
        (UserRole.recruiter, 403),
    ],
)
async def test_only_admin_finance_and_tcm_reverse_a_termination(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch, role, expected
):
    seed = await _seed_active_md_consultant()
    _enable_multi(monkeypatch, seed["client_id"])
    await _terminate(app_client, app_auth_headers, seed["contract_id"])
    _user_id, headers = await make_user(role)
    resp = await app_client.post(
        f"/api/contracts/{seed['contract_id']}/termination-reversal",
        headers=headers,
    )
    assert resp.status_code == expected, resp.text


# ── Korekta danych ze zgłoszenia ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_one_shot_repair_reverses_the_reported_contract_once(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    seed = await _seed_active_md_consultant()
    _enable_multi(monkeypatch, seed["client_id"])
    await _terminate(app_client, app_auth_headers, seed["contract_id"])
    await app_client.patch(
        f"/api/contracts/{seed['contract_id']}/status",
        json={"status": "active"},
        headers=app_auth_headers,
    )

    from app.core.database import AsyncSessionLocal
    from app.models.contract_termination_snapshot import ContractTerminationSnapshot
    from app.services.contract_termination_reversal_repair import (
        TARGETS,
        run_termination_reversal_repair,
    )
    from app.services.order_write_errors import commit_order_write

    assert TARGETS == ((408, 65586, 115),)
    async with AsyncSessionLocal() as db:
        # Zakończenie sprzed 0365 nie ma migawki — korekta idzie z historii.
        await db.execute(
            delete(ContractTerminationSnapshot).where(
                ContractTerminationSnapshot.contract_id == seed["contract_id"]
            )
        )
        await db.commit()

    marker = f"test_reversal_repair_{uuid.uuid4().hex[:8]}"
    targets = (
        (seed["contract_id"], seed["candidate_id"] + 1, seed["client_id"]),
        (seed["contract_id"], seed["candidate_id"], seed["client_id"]),
    )
    async with AsyncSessionLocal() as db:
        summary = await run_termination_reversal_repair(
            db, targets=targets, marker=marker
        )
        await commit_order_write(db)
    assert summary["reversed"] == 1
    assert summary["results"][0]["skipped"] == "identity_mismatch"
    assert summary["results"][1]["restored_order_ids"] == [seed["line_id"]]
    line = await _line(seed["line_id"])
    assert (line["status"], line["end_date"], line["md_remaining"]) == (
        "active",
        None,
        Decimal("259"),
    )

    async with AsyncSessionLocal() as db:
        again = await run_termination_reversal_repair(
            db, targets=targets, marker=marker
        )
    assert again is None
