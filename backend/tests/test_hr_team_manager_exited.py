"""Przełożony, który odszedł, nie ma podwładnych (przegląd 17.10.2026).

Kadry zamykają kartotekę przełożonego (``exited``) w edycji kartoteki, a konto
zostaje aktywne do wyłączenia. Do poprawki taka osoba dalej widziała „Mój
zespół” z rodzajem nieobecności (D6) i przechodziła bramki akceptacji, bo
``people.direct_report_ids`` liczył podwładnych po samym ``manager_user_id``,
a ``validate_managers`` przyjmował ją jako nowego przełożonego. Reguła jak
w ``recipients.supervisor_of``: przełożony = aktywne konto i kartoteka ≠
``exited`` — w każdym zakresie (zespół, akceptacje, kolejki, pełna kartoteka).

Dane fikcyjne (repo jest publiczne); świat jak w ``tests/test_hr_team_api.py``.
"""

from __future__ import annotations

import pytest
from sqlalchemy import update

from app.core.database import AsyncSessionLocal
from app.models.user import User
from app.services.hr import people, recipients, team
from tests.test_hr_team_api import (  # noqa: F401 — fikstura
    BASE,
    _grant,
    _headers,
    _user,
    _world,
    modules,
)

EXITED_DETAIL = (
    "Wybrany przełożony zakończył współpracę — wybierz osobę, która pracuje."
)


async def _kadry() -> User:
    async with AsyncSessionLocal() as db:
        hr = await _user(db, "recruiter", profile=False)
        await _grant(db, hr, "people_admin")
        await db.commit()
    return hr


@pytest.mark.asyncio
async def test_exited_manager_loses_team_approvals_and_full_profiles(
    app_client,
    modules,  # noqa: F811
) -> None:
    world = await _world()
    hr = await _kadry()
    boss = world["boss"]
    patched = await app_client.patch(
        f"/api/hr/admin/profiles/{boss.id}",
        json={"employment_status": "exited"},
        headers=_headers(hr),
    )
    assert patched.status_code == 200, patched.text
    async with AsyncSessionLocal() as db:
        assert (await db.get(User, boss.id)).is_active is True
        sick_profile = await people.profile_of(db, world["sick"].id)
        supervisor = await recipients.supervisor_of(db, sick_profile)
        assert supervisor.kind != "manager"
        assert await people.direct_report_ids(db, boss.id) == set()
        fresh_boss = await db.get(User, boss.id)
        assert await people.viewer_scope(db, fresh_boss, sick_profile) != "full"

    # „Mój zespół” z rodzajem nieobecności — już nie.
    team_response = await app_client.get(BASE, headers=_headers(boss))
    assert team_response.status_code == 403, team_response.text
    # Akceptacje urlopów i kolejka timesheetów — bramka przełożonego też odmawia.
    approvals = await app_client.get(
        "/api/hr/leave/approvals/pending", headers=_headers(boss)
    )
    assert approvals.status_code == 403, approvals.text
    decide = await app_client.post(
        f"/api/hr/leave/approvals/{world['pending']}/approve", headers=_headers(boss)
    )
    assert decide.status_code == 403, decide.text
    config = await app_client.get("/api/hr/config", headers=_headers(boss))
    assert config.status_code == 200, config.text
    assert config.json()["me"]["is_manager"] is False
    assert config.json()["me"]["direct_reports"] == 0

    # Kadry: zespół takiej osoby jest pusty, a na liście przełożonych jej nie ma.
    other = await app_client.get(
        BASE, params={"manager": boss.id}, headers=_headers(hr)
    )
    assert other.status_code == 200, other.text
    assert other.json()["people"] == []
    listed = await app_client.get(f"{BASE}/managers", headers=_headers(hr))
    assert listed.status_code == 200
    assert boss.id not in {item["user_id"] for item in listed.json()["items"]}
    assert world["other_boss"].id in {
        item["user_id"] for item in listed.json()["items"]
    }


@pytest.mark.asyncio
async def test_inactive_account_has_no_reports(modules) -> None:  # noqa: F811
    world = await _world()
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(User).where(User.id == world["boss"].id).values(is_active=False)
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        assert await people.direct_report_ids(db, world["boss"].id) == set()
        assert await team.reports_of(db, world["boss"].id) == []
        # Żywy przełożony obok — bez zmian.
        assert await people.direct_report_ids(db, world["other_boss"].id) == {
            world["stranger"].id
        }


@pytest.mark.asyncio
async def test_exited_person_rejected_as_manager_in_profile_and_structure(
    app_client,
    modules,  # noqa: F811
) -> None:
    world = await _world()
    hr = await _kadry()
    async with AsyncSessionLocal() as db:
        gone = await _user(db, "recruiter", employment_status="exited")
        await db.commit()

    profile = await app_client.patch(
        f"/api/hr/admin/profiles/{world['stranger'].id}",
        json={"manager_user_id": gone.id},
        headers=_headers(hr),
    )
    assert profile.status_code == 422, profile.text
    assert profile.json()["detail"] == EXITED_DETAIL

    moved = await app_client.post(
        "/api/hr/structure/reassign",
        json={"user_ids": [world["stranger"].id], "manager_user_id": gone.id},
        headers=_headers(hr),
    )
    assert moved.status_code == 422, moved.text
    assert moved.json()["detail"] == EXITED_DETAIL
    async with AsyncSessionLocal() as db:
        stranger = await people.profile_of(db, world["stranger"].id)
    assert stranger.manager_user_id == world["other_boss"].id


@pytest.mark.asyncio
async def test_unchanged_exited_manager_does_not_block_profile_edit(
    app_client,
    modules,  # noqa: F811
) -> None:
    """Formularz kartoteki wysyła przełożonego zawsze — edycja telefonu osoby,
    której przełożony odszedł, przechodzi (przepięcie to osobna decyzja)."""

    world = await _world()
    hr = await _kadry()
    boss = world["boss"]
    closed = await app_client.patch(
        f"/api/hr/admin/profiles/{boss.id}",
        json={"employment_status": "exited"},
        headers=_headers(hr),
    )
    assert closed.status_code == 200, closed.text
    edited = await app_client.patch(
        f"/api/hr/admin/profiles/{world['contractor'].id}",
        json={"manager_user_id": boss.id, "phone": "+48 500 000 000"},
        headers=_headers(hr),
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["phone"] == "+48 500 000 000"
