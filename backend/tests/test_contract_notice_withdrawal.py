"""„Wycofaj wypowiedzenie” (zgłoszenie Finansów 17.11.2026).

Zgłoszenie: umowa B2B skrócona aneksem „Wcześniejsze zakończenie” (15.12 →
31.10), nocny proces zakończył ją 01.11 i uciął przypisanie na zamówieniu.
Konsultant wycofał wypowiedzenie i pracuje dalej, a NEXUS nie miał drogi
powrotu: „Cofnij zakończenie” wracało do daty 31.10 i blokowało się radą
„przedłuż aneksem”, a „Przedłuż” dla B2B był wyłączony i odsyłał z powrotem.

Testy idą tą samą drogą co produkcja: aneks wypowiedzenia → nocne
zakończenie (to samo co ``contract_alerts._promote_statuses`` dla jednego
kontraktu) → podgląd → wycofanie.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.scheduling import business_today
from app.models.user import UserRole
from tests._jarvis_helpers import make_user
from tests.test_contract_termination_reversal import (
    _enable_multi,
    _line,
    _seed_active_md_consultant,
)


async def _give_notice(seed: dict, *, original_end: date, notice_end: date) -> int:
    """Stan po aneksie wypowiedzenia: linia do ``original_end``, umowa
    „Kończąca się” do ``notice_end``, aneks jak sprzed 24.09.2026."""
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder
    from app.models.contract import Contract, ContractStatus
    from app.models.contract_amendment import ContractAmendment, ContractAmendmentType

    async with AsyncSessionLocal() as db:
        line = await db.get(ClientOrder, seed["line_id"])
        line.end_date = original_end
        contract = await db.get(Contract, seed["contract_id"])
        contract.end_date = notice_end
        contract.status = ContractStatus.ending
        amendment = ContractAmendment(
            contract_id=contract.id,
            amendment_type=ContractAmendmentType.early_termination,
            old_values={"end_date": original_end.isoformat(), "status": "active"},
            new_values={"end_date": notice_end.isoformat(), "status": "ending"},
            effective_date=notice_end - timedelta(days=90),
            reason="przysłał wypowiedzenie, 3 msc",
        )
        db.add(amendment)
        await db.commit()
        return amendment.id


async def _end_overnight(contract_id: int) -> None:
    """To, co nocny proces robi z jednym kontraktem po minionej dacie końca."""
    from app.core.database import AsyncSessionLocal
    from app.models.contract import Contract, ContractStatus
    from app.services.contract_order_offboarding import (
        apply_contract_order_offboarding,
    )
    from app.services.contract_termination_snapshot import ContractStateBefore

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        state_before = ContractStateBefore.of(contract)
        contract.status = ContractStatus.ended
        await apply_contract_order_offboarding(
            db,
            contract_id=contract.id,
            effective_date=contract.end_date,
            actor_id=None,
            today=business_today(),
            contract_before=state_before,
        )
        await db.commit()


async def _ended_after_notice(monkeypatch) -> dict:
    seed = await _seed_active_md_consultant()
    _enable_multi(monkeypatch, seed["client_id"])
    today = business_today()
    seed["original_end"] = today + timedelta(days=28)
    seed["notice_end"] = today - timedelta(days=17)
    seed["notice_id"] = await _give_notice(
        seed, original_end=seed["original_end"], notice_end=seed["notice_end"]
    )
    await _end_overnight(seed["contract_id"])
    line = await _line(seed["line_id"])
    assert (line["status"], line["end_date"]) == ("completed", seed["notice_end"])
    return seed


async def _amendments(app_client: AsyncClient, headers: dict, contract_id: int) -> list:
    resp = await app_client.get(
        f"/api/contracts/{contract_id}/amendments", headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_undo_termination_points_to_notice_withdrawal_instead_of_an_annex(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Zgłoszenie: blokada radziła „przedłuż aneksem”, a „Przedłuż” odsyłał
    z powrotem do „Cofnij zakończenie”. Teraz wskazuje wycofanie wypowiedzenia."""
    seed = await _ended_after_notice(monkeypatch)
    preview = await app_client.get(
        f"/api/contracts/{seed['contract_id']}/termination-reversal",
        headers=app_auth_headers,
    )
    assert preview.status_code == 200, preview.text
    [blocker] = [
        b for b in preview.json()["blockers"] if b["code"] == "end_date_passed"
    ]
    assert "Wycofaj wypowiedzenie" in blocker["message"]
    assert "aneksem" not in blocker["message"]
    assert blocker["notice_amendment_id"] == seed["notice_id"]

    rows = await _amendments(app_client, app_auth_headers, seed["contract_id"])
    [notice] = [r for r in rows if r["id"] == seed["notice_id"]]
    assert (notice["withdrawable"], notice["withdrawn"]) == (True, False)


@pytest.mark.asyncio
async def test_withdrawal_after_nightly_end_restores_contract_and_order(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    seed = await _ended_after_notice(monkeypatch)
    url = f"/api/contracts/{seed['contract_id']}/notice-withdrawal"

    preview = await app_client.get(url, headers=app_auth_headers)
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["notice"]["amendment_id"] == seed["notice_id"]
    assert body["notice"]["end_before_notice"] == seed["original_end"].isoformat()
    assert body["indefinite_allowed"] is True
    assert body["reversal"]["blockers"] == []
    [order] = body["reversal"]["orders"]
    assert order["end_date_target"] == seed["original_end"].isoformat()

    resp = await app_client.post(
        url, json={"end_date": None, "note": "wycofał"}, headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text

    contract = (
        await app_client.get(
            f"/api/contracts/{seed['contract_id']}", headers=app_auth_headers
        )
    ).json()
    assert (contract["status"], contract["end_date"], contract["terminated_at"]) == (
        "active",
        None,
        None,
    )
    line = await _line(seed["line_id"])
    assert (line["status"], line["end_date"]) == ("active", seed["original_end"])

    rows = await _amendments(app_client, app_auth_headers, seed["contract_id"])
    [notice] = [r for r in rows if r["id"] == seed["notice_id"]]
    assert (notice["withdrawable"], notice["withdrawn"]) == (False, True)
    [entry] = [r for r in rows if r["amendment_type"] == "custom_change"]
    assert entry["new_values"]["annex_title"] == "Wycofanie wypowiedzenia"
    assert entry["new_values"]["withdrawn_amendment_id"] == seed["notice_id"]
    assert entry["reason"] == "wycofał"

    # Drugi raz nie ma czego wycofać, a wycofany aneks nie jest już
    # „ręcznym zakończeniem” umowy B2B.
    again = await app_client.post(url, json={}, headers=app_auth_headers)
    assert again.status_code == 409, again.text
    assert again.json()["detail"]["code"] == "no_notice"

    from app.core.database import AsyncSessionLocal
    from app.services.b2b_contract_end_date import has_early_termination_amendment

    async with AsyncSessionLocal() as db:
        assert not await has_early_termination_amendment(db, seed["contract_id"])


@pytest.mark.asyncio
async def test_withdrawal_before_the_end_only_moves_the_contract_date(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Wypowiedzenie jeszcze biegnie: zamówień nikt nie ruszał, wraca tylko
    umowa — z datą sprzed wypowiedzenia, którą wybrał człowiek."""
    seed = await _seed_active_md_consultant()
    _enable_multi(monkeypatch, seed["client_id"])
    today = business_today()
    original_end = today + timedelta(days=60)
    notice_id = await _give_notice(
        seed, original_end=original_end, notice_end=today + timedelta(days=10)
    )

    resp = await app_client.post(
        f"/api/contracts/{seed['contract_id']}/notice-withdrawal",
        json={"end_date": original_end.isoformat()},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["reversal"] is None
    contract = (
        await app_client.get(
            f"/api/contracts/{seed['contract_id']}", headers=app_auth_headers
        )
    ).json()
    assert (contract["status"], contract["end_date"]) == (
        "active",
        original_end.isoformat(),
    )
    line = await _line(seed["line_id"])
    assert (line["status"], line["end_date"]) == ("active", original_end)
    rows = await _amendments(app_client, app_auth_headers, seed["contract_id"])
    assert [r["withdrawn"] for r in rows if r["id"] == notice_id] == [True]


@pytest.mark.asyncio
async def test_withdrawal_refuses_a_past_date_and_an_open_end_outside_b2b(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    seed = await _ended_after_notice(monkeypatch)
    url = f"/api/contracts/{seed['contract_id']}/notice-withdrawal"
    past = await app_client.post(
        url,
        json={"end_date": (business_today() - timedelta(days=1)).isoformat()},
        headers=app_auth_headers,
    )
    assert past.status_code == 422, past.text
    assert past.json()["detail"]["code"] == "end_date_passed"

    other = await _seed_active_md_consultant(contract_type="uzlecenie")
    _enable_multi(monkeypatch, other["client_id"], seed["client_id"])
    today = business_today()
    await _give_notice(
        other,
        original_end=today + timedelta(days=60),
        notice_end=today + timedelta(days=5),
    )
    open_end = await app_client.post(
        f"/api/contracts/{other['contract_id']}/notice-withdrawal",
        json={"end_date": None},
        headers=app_auth_headers,
    )
    assert open_end.status_code == 422, open_end.text
    assert open_end.json()["detail"]["code"] == "end_date_required"

    # Nic się nie zmieniło.
    line = await _line(seed["line_id"])
    assert line["status"] == "completed"


@pytest.mark.asyncio
async def test_contract_without_notice_has_nothing_to_withdraw(
    app_client: AsyncClient, app_auth_headers: dict
):
    seed = await _seed_active_md_consultant()
    resp = await app_client.get(
        f"/api/contracts/{seed['contract_id']}/notice-withdrawal",
        headers=app_auth_headers,
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "no_notice"


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
async def test_only_admin_finance_and_tcm_withdraw_a_notice(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch, role, expected
):
    seed = await _ended_after_notice(monkeypatch)
    _user_id, headers = await make_user(role)
    resp = await app_client.post(
        f"/api/contracts/{seed['contract_id']}/notice-withdrawal",
        json={"end_date": None},
        headers=headers,
    )
    assert resp.status_code == expected, resp.text


@pytest.mark.asyncio
async def test_one_shot_repair_withdraws_the_reported_notice_once(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    seed = await _ended_after_notice(monkeypatch)

    from app.core.database import AsyncSessionLocal
    from app.models.app_setting import AppSetting
    from app.services.contract_notice_withdrawal_repair import (
        TARGETS,
        run_notice_withdrawal_repair,
    )
    from app.services.order_write_errors import commit_order_write

    assert TARGETS == ((216, 33818, 11),)
    marker = f"test_notice_withdrawal_{uuid.uuid4().hex[:8]}"
    targets = (
        (seed["contract_id"], seed["candidate_id"] + 1, seed["client_id"]),
        (seed["contract_id"], seed["candidate_id"], seed["client_id"]),
    )
    async with AsyncSessionLocal() as db:
        summary = await run_notice_withdrawal_repair(db, targets=targets, marker=marker)
        await commit_order_write(db)
    assert summary["withdrawn"] == 1
    assert summary["results"][0]["skipped"] == "identity_mismatch"
    assert summary["results"][1]["restored_order_ids"] == [seed["line_id"]]
    line = await _line(seed["line_id"])
    assert (line["status"], line["end_date"]) == ("active", seed["original_end"])

    async with AsyncSessionLocal() as db:
        assert (
            await run_notice_withdrawal_repair(db, targets=targets, marker=marker)
            is None
        )
        await db.rollback()
        stored = await db.scalar(select(AppSetting).where(AppSetting.key == marker))
        assert stored is not None
