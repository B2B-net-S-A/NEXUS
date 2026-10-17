"""Menedżer u klienta na kontrakcie (D8, etap 2 „Ludzi w NEXUSIE”, 17.10.2026).

Zakres: ``client_pm_contact_id`` w PATCH i w odpowiedzi szczegółów (imię,
stanowisko), 422 dla kontaktu innego klienta, nowa osoba bez duplikatu
kontaktu, podpowiedź „Przypnij: X” tylko przy dokładnym imieniu i nazwisku,
hiring manager rekrutacji jako domyślny menedżer — przy ręcznym zakładaniu
kontraktu z ``job_id`` i w automacie „Zatrudniony”.

Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Optional

import pytest
from sqlalchemy import func, select

import app.models  # noqa: F401  (rejestracja wszystkich mapperów)
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.core.security import create_access_token
from app.models.candidate import Candidate
from app.models.client import Client, ClientStatus
from app.models.contact import Contact
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.job import Job, JobStatus
from app.models.user import User, UserRole
from app.services.contract_client_manager import FOREIGN_CONTACT_DETAIL, text_hint

pytestmark = pytest.mark.asyncio


def _tag() -> str:
    return uuid.uuid4().hex[:8]


def headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def make_admin() -> User:
    tag = _tag()
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"pm-admin-{tag}@example.com",
            name=f"Administratorka {tag}",
            role=UserRole.admin,
            roles=["admin"],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        return user


async def make_client() -> int:
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Bank Przykładowy {_tag()}", status=ClientStatus.active)
        db.add(client)
        await db.commit()
        return client.id


async def make_contact(
    client_id: int, name: str, position: Optional[str] = "Head of Data"
) -> int:
    async with AsyncSessionLocal() as db:
        contact = Contact(client_id=client_id, name=name, position=position)
        db.add(contact)
        await db.commit()
        return contact.id


async def make_candidate() -> int:
    tag = _tag()
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Jan", lastname=f"Przykładowy-{tag}", email=f"pm-{tag}@example.com"
        )
        db.add(candidate)
        await db.commit()
        return candidate.id


async def make_contract(
    client_id: int, *, line_manager: Optional[str] = None, pm_name: Optional[str] = None
) -> int:
    candidate_id = await make_candidate()
    async with AsyncSessionLocal() as db:
        contract = Contract(
            candidate_id=candidate_id,
            client_id=client_id,
            status=ContractStatus.active,
            start_date=business_today() - timedelta(days=30),
            rate_candidate=Decimal("100.000"),
            rate_client=Decimal("130.000"),
            rate_unit=RateUnit.hourly,
            line_manager=line_manager,
            client_pm_name=pm_name,
        )
        db.add(contract)
        await db.commit()
        return contract.id


async def make_job(client_id: int, hm_contact_id: Optional[int]) -> int:
    async with AsyncSessionLocal() as db:
        job = Job(
            title=f"Data Engineer {_tag()}",
            description="Opis",
            status=JobStatus.published,
            client_id=client_id,
            hiring_manager_contact_id=hm_contact_id,
        )
        db.add(job)
        await db.commit()
        return job.id


async def stored_manager(contract_id: int) -> Optional[int]:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(Contract.client_pm_contact_id).where(Contract.id == contract_id)
        )


# ── PATCH i odczyt ──────────────────────────────────────────────────────────


async def test_manager_from_other_client_is_rejected(app_client) -> None:
    admin = await make_admin()
    client_id = await make_client()
    other_client = await make_client()
    foreign = await make_contact(other_client, "Piotr Obcy")
    contract_id = await make_contract(client_id)

    response = await app_client.patch(
        f"/api/contracts/{contract_id}",
        headers=headers(admin),
        json={"client_pm_contact_id": foreign},
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == FOREIGN_CONTACT_DETAIL
    assert await stored_manager(contract_id) is None


async def test_manager_of_the_client_is_saved_and_named_in_detail(app_client) -> None:
    admin = await make_admin()
    client_id = await make_client()
    manager = await make_contact(client_id, "Zofia Przykładowa", "Head of Data")
    contract_id = await make_contract(client_id)

    saved = await app_client.patch(
        f"/api/contracts/{contract_id}",
        headers=headers(admin),
        json={"client_pm_contact_id": manager},
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["client_pm_contact_id"] == manager
    assert body["client_pm_contact_name"] == "Zofia Przykładowa"
    assert body["client_pm_contact_position"] == "Head of Data"

    detail = await app_client.get(
        f"/api/contracts/{contract_id}", headers=headers(admin)
    )
    assert detail.json()["client_pm_contact_name"] == "Zofia Przykładowa"

    cleared = await app_client.patch(
        f"/api/contracts/{contract_id}",
        headers=headers(admin),
        json={"client_pm_contact_id": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["client_pm_contact_id"] is None
    assert await stored_manager(contract_id) is None


async def test_new_person_becomes_client_contact_without_duplicate(app_client) -> None:
    admin = await make_admin()
    client_id = await make_client()
    contract_id = await make_contract(client_id)
    second_contract = await make_contract(client_id)

    first = await app_client.patch(
        f"/api/contracts/{contract_id}",
        headers=headers(admin),
        json={
            "client_pm_new_person": {
                "name": "Marek Nowy",
                "position": "Kierownik zespołu",
            }
        },
    )
    assert first.status_code == 200, first.text
    contact_id = first.json()["client_pm_contact_id"]
    assert first.json()["client_pm_contact_name"] == "Marek Nowy"

    again = await app_client.patch(
        f"/api/contracts/{second_contract}",
        headers=headers(admin),
        json={"client_pm_new_person": {"name": "nowy  MAREK"}},
    )
    assert again.status_code == 200, again.text
    assert again.json()["client_pm_contact_id"] == contact_id
    async with AsyncSessionLocal() as db:
        count = await db.scalar(
            select(func.count())
            .select_from(Contact)
            .where(Contact.client_id == client_id)
        )
    assert count == 1


async def test_new_person_needs_full_name_and_excludes_contact_id(app_client) -> None:
    admin = await make_admin()
    client_id = await make_client()
    manager = await make_contact(client_id, "Ewa Kowalska")
    contract_id = await make_contract(client_id)

    one_word = await app_client.patch(
        f"/api/contracts/{contract_id}",
        headers=headers(admin),
        json={"client_pm_new_person": {"name": "Marek"}},
    )
    assert one_word.status_code == 422
    assert one_word.json()["detail"] == "Podaj imię i nazwisko menedżera u klienta."

    both = await app_client.patch(
        f"/api/contracts/{contract_id}",
        headers=headers(admin),
        json={
            "client_pm_contact_id": manager,
            "client_pm_new_person": {"name": "Marek Nowy"},
        },
    )
    assert both.status_code == 422
    assert await stored_manager(contract_id) is None


async def test_hint_only_for_exact_name_and_never_saved(app_client) -> None:
    admin = await make_admin()
    client_id = await make_client()
    manager = await make_contact(client_id, "Michał Rogalski", "Line Manager")
    exact = await make_contract(client_id, line_manager="  michał   ROGALSKI ")
    abbreviated = await make_contract(client_id, line_manager="Michał R.")
    from_pm = await make_contract(client_id, pm_name="Michał Rogalski")

    detail = (
        await app_client.get(f"/api/contracts/{exact}", headers=headers(admin))
    ).json()
    assert detail["client_pm_contact_id"] is None
    assert detail["client_pm_contact_hint"] == {
        "contact_id": manager,
        "name": "Michał Rogalski",
        "position": "Line Manager",
        "source": "line_manager",
        "text": "michał ROGALSKI",
    }
    assert await stored_manager(exact) is None
    short = (
        await app_client.get(f"/api/contracts/{abbreviated}", headers=headers(admin))
    ).json()
    assert short["client_pm_contact_hint"] is None
    pm = (
        await app_client.get(f"/api/contracts/{from_pm}", headers=headers(admin))
    ).json()
    assert pm["client_pm_contact_hint"]["source"] == "client_pm_name"


async def test_text_hint_prefers_line_manager_and_lowest_id() -> None:
    first = Contact(id=7, client_id=1, name="Anna Przykładowa")
    twin = Contact(id=3, client_id=1, name="anna przykładowa")
    other = Contact(id=5, client_id=1, name="Jan Przykładowy")
    hint = text_hint(
        [first, twin, other],
        line_manager="Anna Przykładowa",
        client_pm_name="Jan Przykładowy",
    )
    assert hint is not None and hint["contact_id"] == 3
    assert text_hint([first], line_manager="Anna", client_pm_name=None) is None


# ── Hiring manager jako domyślny menedżer ───────────────────────────────────


async def test_manual_contract_from_job_takes_hiring_manager(app_client) -> None:
    admin = await make_admin()
    client_id = await make_client()
    hm = await make_contact(client_id, "Hanna Menedżerska")
    job_id = await make_job(client_id, hm)
    no_hm_job = await make_job(client_id, None)

    created = await app_client.post(
        "/api/contracts",
        headers=headers(admin),
        json={
            "candidate_id": await make_candidate(),
            "client_id": client_id,
            "job_id": job_id,
            "start_date": business_today().isoformat(),
            "contract_type": "b2b",
            "rate_unit": "hourly",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["client_pm_contact_id"] == hm
    assert created.json()["client_pm_contact_name"] == "Hanna Menedżerska"

    without = await app_client.post(
        "/api/contracts",
        headers=headers(admin),
        json={
            "candidate_id": await make_candidate(),
            "client_id": client_id,
            "job_id": no_hm_job,
            "start_date": business_today().isoformat(),
            "contract_type": "b2b",
            "rate_unit": "hourly",
        },
    )
    assert without.status_code == 201, without.text
    assert without.json()["client_pm_contact_id"] is None


async def test_hire_automation_takes_hiring_manager() -> None:
    from app.services.b2b_contract_automation import ensure_b2b_employment_draft

    admin = await make_admin()
    client_id = await make_client()
    hm = await make_contact(client_id, "Hanna Zatrudniająca")
    job_id = await make_job(client_id, hm)
    candidate_id = await make_candidate()
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        result = await ensure_b2b_employment_draft(
            db,
            candidate_id=candidate_id,
            job=job,
            actor_id=admin.id,
            require_b2b=False,
            ensure_detail=False,
            validate_terms=False,
            default_start_date=business_today(),
        )
        await db.commit()
        contract_id = result.contract.id
    assert await stored_manager(contract_id) == hm
