"""„Szczegóły administracyjne” podpisanego kontraktu (decyzje Artura 06.11.2026).

* Płace (i osoby z oznaczaniem podpisu) zmieniają replacement, „za kogo”
  i „kandydat wskazany przez klienta” — z powodem, ze śladem w historii
  kontraktu i audycie Płac,
* bez uprawnienia 403, bez powodu 422, osoba nie zastępuje samej siebie (422),
* zapis od razu uzgadnia premie: gwarancja DL anuluje premię DL (``guarantee``),
  „kandydat od klienta” — wszystkie (``client_referral``).

Dane fikcyjne; stawki zmyślone.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.core.security import create_access_token
from app.models.activity import Activity
from app.models.contract import Contract, ContractStatus
from app.models.hr_ops import HrAuditEvent
from app.models.job import Job
from app.models.section_permission import UserActionOverride
from tests.test_hr_bonus_automation import (  # noqa: F401  (fikstura)
    _bonuses,
    _person,
    _placement,
    _reconcile,
    payroll_on,
)

pytestmark = pytest.mark.usefixtures("payroll_on")


async def _headers(*, action: str = "payroll", access: str = "manage") -> dict:
    async with AsyncSessionLocal() as db:
        user = await _person(db, "recruiter")
        db.add(UserActionOverride(user_id=user.id, action=action, access=access))
        await db.commit()
        token = create_access_token(subject=user.id, role="recruiter")
    return {"Authorization": f"Bearer {token}"}


def _url(contract_id: int) -> str:
    return f"/api/hr/payroll/contracts/{contract_id}/admin-details"


async def _same_dl_replacement() -> tuple[dict, dict]:
    """Zastąpiona osoba po ok. 200 dniach, zatrudniona przez tego samego DL-a."""

    today = business_today()
    replaced = await _placement(
        started_days_ago=260,
        status=ContractStatus.ended,
        end_date=today - timedelta(days=60),
    )
    world = await _placement(started_days_ago=40)
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, world["contract"])
        job = await db.get(Job, contract.job_id)
        job.delivery_lead_id = replaced["dl"]
        await db.commit()
    return replaced, {**world, "dl": replaced["dl"]}


@pytest.mark.asyncio
async def test_replacement_with_reason_keeps_dl_bonus(app_client) -> None:
    replaced, world = await _same_dl_replacement()
    await _reconcile(world["contract"])
    assert (await _bonuses(world["contract"]))["dl"].status == "proposed"
    headers = await _headers()

    response = await app_client.put(
        _url(world["contract"]),
        json={
            "is_replacement": True,
            "replaced_contract_id": replaced["contract"],
            "is_client_referral": False,
            "reason": "  zastępstwo potwierdzone przez Delivery  ",
        },
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_replacement"] is True
    assert body["replaced"]["contract_id"] == replaced["contract"]
    assert body["changed"] == [
        "is_client_referral",
        "is_replacement",
        "replaced_contract_id",
    ]
    found = await _bonuses(world["contract"])
    # Zastępstwo nie wpływa na premie (decyzja 09.11.2026).
    assert found["dl"].status == "proposed"
    assert found["recruiter"].status == "proposed"
    async with AsyncSessionLocal() as db:
        activity = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "contract",
                Activity.entity_id == world["contract"],
                Activity.action == "admin_details_changed",
            )
        )
        audit = await db.scalar(
            select(HrAuditEvent).where(
                HrAuditEvent.entity_type == "contract",
                HrAuditEvent.entity_id == str(world["contract"]),
                HrAuditEvent.action == "admin_details_changed",
            )
        )
    assert activity is not None
    assert activity.details["reason"] == "zastępstwo potwierdzone przez Delivery"
    assert activity.details["is_replacement"] == {"from": None, "to": True}
    assert audit is not None and audit.sensitivity == "payroll"

    got = await app_client.get(_url(world["contract"]), headers=headers)
    assert got.status_code == 200
    assert got.json()["replaced"]["contract_id"] == replaced["contract"]


@pytest.mark.asyncio
async def test_client_referral_cancels_all_and_no_restores(app_client) -> None:
    world = await _placement(started_days_ago=10)
    await _reconcile(world["contract"])
    headers = await _headers()
    body = {"is_replacement": False, "replaced_contract_id": None, "reason": "ERSTE"}

    response = await app_client.put(
        _url(world["contract"]),
        json={**body, "is_client_referral": True},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    found = await _bonuses(world["contract"])
    assert {b.cancel_reason for b in found.values()} == {"client_referral"}

    response = await app_client.put(
        _url(world["contract"]),
        json={**body, "is_client_referral": False},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    found = await _bonuses(world["contract"])
    assert {b.status for b in found.values()} == {"proposed"}


@pytest.mark.asyncio
async def test_signature_confirmer_may_edit(app_client) -> None:
    world = await _placement(started_days_ago=10)
    # Rekruter z „Umowy B2B: oznaczanie jako podpisane”, bez Płac.
    headers = await _headers(action="b2b_signature_confirmation")
    response = await app_client.put(
        _url(world["contract"]),
        json={
            "is_replacement": False,
            "is_client_referral": True,
            "reason": "od klienta",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_without_permission_is_refused(app_client) -> None:
    world = await _placement(started_days_ago=10)
    headers = await _headers(action="b2b_signature_confirmation", access="none")
    body = {"is_replacement": False, "is_client_referral": True, "reason": "od klienta"}
    response = await app_client.put(_url(world["contract"]), json=body, headers=headers)
    assert response.status_code == 403
    assert (
        await app_client.get(_url(world["contract"]), headers=headers)
    ).status_code == 403
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, world["contract"])
    assert contract.is_client_referral is None


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["", "  ", "ab"])
async def test_reason_is_required(app_client, reason: str) -> None:
    world = await _placement(started_days_ago=10)
    headers = await _headers()
    response = await app_client.put(
        _url(world["contract"]),
        json={"is_replacement": False, "is_client_referral": True, "reason": reason},
        headers=headers,
    )
    assert response.status_code == 422
    missing = await app_client.put(
        _url(world["contract"]),
        json={"is_replacement": False, "is_client_referral": True},
        headers=headers,
    )
    assert missing.status_code == 422


@pytest.mark.asyncio
async def test_person_cannot_replace_themselves(app_client) -> None:
    world = await _placement(started_days_ago=10)
    # Drugi kontrakt tej samej osoby (inny klient) — nadal ta sama osoba.
    other = await _placement(
        started_days_ago=200,
        status=ContractStatus.ended,
        end_date=business_today() - timedelta(days=30),
    )
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, world["contract"])
        previous = await db.get(Contract, other["contract"])
        previous.candidate_id = contract.candidate_id
        await db.commit()
    headers = await _headers()

    for replaced_id in (other["contract"], world["contract"]):
        response = await app_client.put(
            _url(world["contract"]),
            json={
                "is_replacement": True,
                "replaced_contract_id": replaced_id,
                "is_client_referral": False,
                "reason": "zastępstwo",
            },
            headers=headers,
        )
        assert response.status_code == 422, response.text
        assert "samej siebie" in response.text


@pytest.mark.asyncio
async def test_replacement_yes_needs_the_person(app_client) -> None:
    world = await _placement(started_days_ago=10)
    response = await app_client.put(
        _url(world["contract"]),
        json={
            "is_replacement": True,
            "is_client_referral": False,
            "reason": "zastępstwo",
        },
        headers=await _headers(),
    )
    assert response.status_code == 422
    assert "za kogo" in response.text


@pytest.mark.asyncio
async def test_bonus_recipient_cannot_change_own_contract(app_client) -> None:
    """Rekruter z „oznaczaniem podpisu” nie cofa „kandydata od klienta”
    na kontrakcie, z którego sam dostaje premię (przegląd kodu 06.11.2026)."""

    world = await _placement(started_days_ago=10)
    await _reconcile(world["contract"])
    payroll = await _headers()
    body = {"is_replacement": False, "replaced_contract_id": None, "reason": "ERSTE"}
    response = await app_client.put(
        _url(world["contract"]),
        json={**body, "is_client_referral": True},
        headers=payroll,
    )
    assert response.status_code == 200, response.text

    async with AsyncSessionLocal() as db:
        db.add(
            UserActionOverride(
                user_id=world["recruiter"],
                action="b2b_signature_confirmation",
                access="manage",
            )
        )
        await db.commit()
    own = {
        "Authorization": "Bearer "
        + create_access_token(subject=world["recruiter"], role="recruiter")
    }
    response = await app_client.put(
        _url(world["contract"]),
        json={**body, "is_client_referral": False, "reason": "pomyłka"},
        headers=own,
    )
    assert response.status_code == 403
    assert "Płace" in response.text
    found = await _bonuses(world["contract"])
    assert {b.cancel_reason for b in found.values()} == {"client_referral"}
    # Odczyt zostaje: widzi, dlaczego premii nie ma.
    assert (
        await app_client.get(_url(world["contract"]), headers=own)
    ).status_code == 200
