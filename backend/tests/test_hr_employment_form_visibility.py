"""Forma umowy: sama osoba, jej przełożony, admin i Finanse (decyzja Artura 19.10.2026).

Kadry bez Płac dostają kartotekę bez formy — w katalogu, w kartotece,
w „Strukturze”, w cudzym „Moim zespole” i w odpowiedzi na własny zapis.
Formę mogą zmienić także Kadry (zapis bez podglądu); Finanse zmieniają ją
osobną trasą, bo kartotekę edytują Kadry.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.core.database import AsyncSessionLocal
from app.models.hr_profile import EmployeeProfile
from app.services.hr import people
from tests.test_hr_time_support import (  # noqa: F401 — fikstury
    grant,
    headers,
    make_user,
    time_on,
)

FORM_KEYS = set(people.FORM_FIELDS)


async def _world():
    async with AsyncSessionLocal() as db:
        boss = await make_user(db, "delivery_lead", employment_type="uop")
        person = await make_user(
            db,
            "recruiter",
            employment_type="zlecenie",
            manager_user_id=boss.id,
            student_contribution_exempt=True,
            contribution_exempt_until=date(2091, 6, 30),
        )
        colleague = await make_user(db, "recruiter", employment_type="b2b")
        hr = await make_user(db, "recruiter", profile=False)
        await grant(db, hr, "people_admin")
        finance = await make_user(db, "finance", profile=False)
        await grant(db, finance, "payroll")
        await db.commit()
    return {
        "boss": boss,
        "person": person,
        "colleague": colleague,
        "hr": hr,
        "finance": finance,
    }


def _row(listing, user_id: int) -> dict:
    return next(item for item in listing.json()["items"] if item["user_id"] == user_id)


@pytest.mark.asyncio
@pytest.mark.usefixtures("time_on")
async def test_people_admin_without_payroll_never_gets_the_form(app_client) -> None:
    world = await _world()
    hr = headers(world["hr"])
    person = world["person"].id

    card = await app_client.get(f"/api/hr/people/{person}", headers=hr)
    assert card.status_code == 200, card.text
    assert card.json()["scope"] == "full"
    assert card.json()["employment_type"] is None
    assert not FORM_KEYS & set(card.json())

    row = _row(await app_client.get("/api/hr/people", headers=hr), person)
    assert row["scope"] == "full" and row["employment_type"] is None
    assert not FORM_KEYS & set(row)

    tree = await app_client.get("/api/hr/structure", headers=hr)
    assert tree.status_code == 200, tree.text
    node = next(p for p in tree.json()["people"] if p["user_id"] == person)
    assert node["employment_type"] is None
    assert node["student"] is None and node["contributions_from"] is None

    team = await app_client.get(f"/api/hr/team?manager={world['boss'].id}", headers=hr)
    assert team.status_code == 200, team.text
    member = next(p for p in team.json()["people"] if p["user_id"] == person)
    assert member["employment_type"] is None and member["student"] is None

    # Kadry zmieniają formę bez podglądu — zapis działa, odpowiedź jej nie zdradza.
    saved = await app_client.patch(
        f"/api/hr/admin/profiles/{person}",
        json={"employment_type": "b2b"},
        headers=hr,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["employment_type"] is None
    async with AsyncSessionLocal() as db:
        profile = await people.profile_of(db, person)
        assert profile.employment_type == "b2b"


@pytest.mark.asyncio
@pytest.mark.usefixtures("time_on")
async def test_finance_manager_and_the_person_see_the_form(app_client) -> None:
    world = await _world()
    person = world["person"].id

    as_finance = await app_client.get(
        f"/api/hr/people/{person}", headers=headers(world["finance"])
    )
    assert as_finance.status_code == 200, as_finance.text
    assert as_finance.json()["scope"] == "full"
    assert as_finance.json()["employment_type"] == "zlecenie"
    assert as_finance.json()["contributions_from"] == "2091-07-01"
    listing = await app_client.get("/api/hr/people", headers=headers(world["finance"]))
    assert _row(listing, world["colleague"].id)["employment_type"] == "b2b"

    as_boss = await app_client.get(
        f"/api/hr/people/{person}", headers=headers(world["boss"])
    )
    assert as_boss.json()["employment_type"] == "zlecenie"
    # Przełożony: forma i znacznik studenta, bez dat (przegląd 17.10.2026).
    assert as_boss.json()["student_contribution_exempt"] is True
    assert "contributions_from" not in as_boss.json()

    own = await app_client.get("/api/hr/me", headers=headers(world["person"]))
    assert own.json()["employment_type"] == "zlecenie"

    # Współpracownik bez przełożeństwa: wizytówka, bez formy.
    stranger = await app_client.get(
        f"/api/hr/people/{person}", headers=headers(world["colleague"])
    )
    assert stranger.json()["scope"] == "card"
    assert "employment_type" not in stranger.json()


@pytest.mark.asyncio
@pytest.mark.usefixtures("time_on")
async def test_finance_changes_the_form_on_its_own_route(app_client) -> None:
    world = await _world()
    url = f"/api/hr/people/{world['colleague'].id}/employment-type"

    refused = await app_client.patch(
        url, json={"employment_type": "uop"}, headers=headers(world["boss"])
    )
    assert refused.status_code == 403

    changed = await app_client.patch(
        url,
        json={"employment_type": "uop", "leave_seniority_years": 11},
        headers=headers(world["finance"]),
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["employment_type"] == "uop"
    assert changed.json()["suggested_entitlement_days"] == 26

    by_hr = await app_client.patch(
        url, json={"employment_type": "b2b"}, headers=headers(world["hr"])
    )
    assert by_hr.status_code == 200, by_hr.text
    assert by_hr.json()["employment_type"] is None


@pytest.mark.asyncio
@pytest.mark.usefixtures("time_on")
async def test_pending_form_reads_as_to_fill_in_until_someone_saves_it(
    app_client,
) -> None:
    world = await _world()
    async with AsyncSessionLocal() as db:
        fresh = await make_user(
            db,
            "recruiter",
            employment_type_pending=True,
            created_from_account=True,
        )
        await db.commit()

    card = await app_client.get(
        f"/api/hr/people/{fresh.id}", headers=headers(world["finance"])
    )
    # Wartość to domyślne B2B (nim liczą urlopy i czas); ekrany mówią „do uzupełnienia”.
    assert card.json()["employment_type"] == "b2b"
    assert card.json()["employment_type_pending"] is True
    assert card.json()["manager_pending"] is True
    # Znacznik „do uzupełnienia” nie zdradza formy — Kadry też go widzą.
    as_hr = await app_client.get(
        f"/api/hr/people/{fresh.id}", headers=headers(world["hr"])
    )
    assert as_hr.json()["employment_type_pending"] is True

    # Zapis tej samej wartości co domyślna (B2B) i tak potwierdza formę.
    saved = await app_client.patch(
        f"/api/hr/people/{fresh.id}/employment-type",
        json={"employment_type": "b2b"},
        headers=headers(world["finance"]),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["employment_type"] == "b2b"
    assert saved.json()["employment_type_pending"] is False
    async with AsyncSessionLocal() as db:
        profile = await db.get(
            EmployeeProfile, (await people.profile_of(db, fresh.id)).id
        )
        assert profile.employment_type_pending is False


@pytest.mark.asyncio
@pytest.mark.usefixtures("time_on")
async def test_pool_hint_and_former_manager_do_not_leak_the_form(app_client) -> None:
    world = await _world()
    async with AsyncSessionLocal() as db:
        senior = await make_user(db, employment_type="uop", leave_seniority_years=12)
        gone = await make_user(
            db,
            "recruiter",
            manager_user_id=world["boss"].id,
            employment_status="exited",
        )
        await db.commit()

    # Podpowiedź 20/26 jest tylko przy UoP — Kadry bez Płac jej nie dostają.
    pool = await app_client.put(
        f"/api/hr/admin/profiles/{senior.id}/entitlements/2091",
        json={"entitlement_days": 26},
        headers=headers(world["hr"]),
    )
    assert pool.status_code == 200, pool.text
    assert pool.json()["suggested_entitlement_days"] is None

    # Były przełożony osoby, która odeszła: wizytówka, nie pełna kartoteka.
    card = await app_client.get(
        f"/api/hr/people/{gone.id}", headers=headers(world["boss"])
    )
    assert card.status_code == 200, card.text
    assert card.json()["scope"] == "card"
