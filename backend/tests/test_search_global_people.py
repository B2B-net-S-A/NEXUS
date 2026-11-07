"""Kategoria „Ludzie” w `GET /api/search/global` (Jarvis, 07.11.2026).

Finanse pytały Jarvisa o raport godzin osoby z kontem pracownika, a wyszukiwarka
znała tylko kandydatów — Jarvis odpowiedział „nie ma” (produkcja, 06.11.2026).
Bramka jak katalog `GET /api/hr/people`: kartoteka albo uprawnienie z grupy
„Ludzie”, przy otwartym module. Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

import uuid

import pytest

from app.core.database import AsyncSessionLocal
from app.models.hr_profile import EmployeeProfile
from app.models.user import User, UserRole
from tests.test_hr_people_api import _headers, modules_off, modules_on  # noqa: F401


async def _account(
    db, role: str, *, name: str | None = None, profile: dict | None = None
) -> User:
    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"people-search-{marker}@example.com",
        name=name or f"Osoba {marker}",
        role=UserRole(role),
        roles=[role],
        is_active=True,
    )
    db.add(user)
    await db.flush()
    if profile is not None:
        db.add(EmployeeProfile(user_id=user.id, **profile))
        await db.flush()
    return user


async def _search(app_client, user: User, q: str) -> dict:
    resp = await app_client.get(
        "/api/search/global", params={"q": q}, headers=_headers(user)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
@pytest.mark.usefixtures("modules_on")
async def test_finance_finds_employee_account_without_polish_letters(
    app_client,
) -> None:
    nonce = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        finance = await _account(db, "finance")
        worker = await _account(
            db,
            "employee",
            name=f"Mirosława Żak{nonce}",
            profile={"job_title": "Specjalistka ds. płac"},
        )
        await db.commit()

    body = await _search(app_client, finance, f"Miroslawa Zak{nonce}")
    assert body["people"] == [
        {
            "id": worker.id,
            "name": f"Mirosława Żak{nonce}",
            "subtitle": "Specjalistka ds. płac",
            "url": f"/people/{worker.id}",
        }
    ]
    assert "people" not in {s["category"] for s in body["skipped"]}


@pytest.mark.asyncio
@pytest.mark.usefixtures("modules_on")
async def test_account_without_profile_or_people_permission_skips_people(
    app_client,
) -> None:
    """Rekruter bez kartoteki nie czyta katalogu: pusto znaczy „nie widzisz”."""
    nonce = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        recruiter = await _account(db, "recruiter")
        await _account(db, "employee", name=f"Ukryta {nonce}", profile={})
        await db.commit()

    body = await _search(app_client, recruiter, f"Ukryta {nonce}")
    assert body["people"] == []
    assert "people" in {s["category"] for s in body["skipped"]}


@pytest.mark.asyncio
@pytest.mark.usefixtures("modules_on")
async def test_people_search_leaves_out_exited_and_accounts_without_profile(
    app_client,
) -> None:
    nonce = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        finance = await _account(db, "finance")
        await _account(
            db,
            "employee",
            name=f"Odeszła {nonce}",
            profile={"employment_status": "exited"},
        )
        await _account(db, "recruiter", name=f"Bez kartoteki {nonce}")
        await db.commit()

    assert (await _search(app_client, finance, nonce))["people"] == []


@pytest.mark.asyncio
@pytest.mark.usefixtures("modules_off")
async def test_people_search_closed_with_module_off(app_client) -> None:
    nonce = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        finance = await _account(db, "finance")
        await _account(db, "employee", name=f"Wyłączony {nonce}", profile={})
        await db.commit()

    assert (await _search(app_client, finance, f"Wyłączony {nonce}"))["people"] == []
