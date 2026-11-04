"""Przełożony z katalogu Microsoft 365 — tylko podpowiedź (etap 2, D7, 17.10.2026).

Dzienna synchronizacja profili czyta ``/users/{upn}/manager`` i zapisuje UPN
w ``employee_profiles.m365_manager_upn``; ``manager_user_id`` nie zmienia się
nigdy. 404 = konto bez przełożonego w katalogu (podpowiedź znika), inny błąd
odczytu zostawia poprzednią podpowiedź, odmowa dla całej rejestracji przerywa
przebieg. Dane fikcyjne.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.core.database import AsyncSessionLocal
from app.models.app_setting import AppSetting
from app.models.hr_profile import EmployeeProfile
from app.services.hr.m365 import profile_sync
from app.services.hr.m365.directory import (
    GraphDirectoryOps,
    SimulatedDirectoryOps,
    manager_upn,
)
from app.services.hr.m365.ops import MailboxError
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING
from tests.hr.m365_helpers import at, make_user


class Directory:
    """Katalog w pamięci z przełożonymi; ``manager_errors`` wstrzykuje błąd."""

    def __init__(self) -> None:
        self.managers: dict[str, Optional[str]] = {}
        self.manager_errors: dict[str, MailboxError] = {}

    async def get_user(self, upn: str) -> dict[str, Any]:
        return {"jobTitle": None, "department": None, "accountEnabled": True}

    async def get_manager(self, upn: str) -> Optional[str]:
        if upn in self.manager_errors:
            raise self.manager_errors[upn]
        return self.managers.get(upn)

    async def aclose(self) -> None:
        return None


async def _set_modules(value: dict) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, HR_MODULES_SETTING)
        if row is None:
            db.add(AppSetting(key=HR_MODULES_SETTING, value=value))
        else:
            row.value = value
        await db.commit()


@pytest_asyncio.fixture
async def people_module():
    async with AsyncSessionLocal() as db:
        previous = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == HR_MODULES_SETTING)
        )
    await _set_modules({key: key == "people" for key in HR_MODULE_KEYS})
    yield
    await _set_modules(previous or {key: False for key in HR_MODULE_KEYS})


async def _fresh_run() -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("DELETE FROM hr_job_runs WHERE kind = :kind"),
            {"kind": profile_sync.JOB_KIND},
        )
        await db.commit()


async def _profile(db, user_id: int) -> EmployeeProfile:
    return await db.scalar(
        select(EmployeeProfile)
        .where(EmployeeProfile.user_id == user_id)
        .execution_options(populate_existing=True)
    )


async def _sync(directory, user_ids: list[int], day: date, mode: str = "live") -> dict:
    await _fresh_run()
    async with AsyncSessionLocal() as db:
        return await profile_sync.run_once(
            db, ops=directory, mode=mode, now=at(day, 7), user_ids=user_ids
        )


def test_manager_response_is_reduced_to_a_lowercase_upn() -> None:
    assert manager_upn({"userPrincipalName": " Szefowa@Example.com "}) == (
        "szefowa@example.com"
    )
    assert manager_upn({"userPrincipalName": ""}) is None
    assert manager_upn({"value": []}) is None
    assert manager_upn(None) is None


@pytest.mark.asyncio
async def test_graph_404_means_no_manager_other_errors_propagate() -> None:
    class Graph(GraphDirectoryOps):
        def __init__(self, error: MailboxError) -> None:
            super().__init__()
            self.error = error

        async def _send(self, method, path, *, params=None, body=None):
            raise self.error

    assert await Graph(MailboxError(404)).get_manager("a@example.com") is None
    with pytest.raises(MailboxError):
        await Graph(MailboxError(500)).get_manager("a@example.com")


@pytest.mark.asyncio
async def test_live_sync_stores_directory_manager_but_never_the_profile_manager(
    people_module,
) -> None:
    async with AsyncSessionLocal() as db:
        boss = await make_user(db)
        person = await make_user(db)
        (await _profile(db, person.id)).manager_user_id = boss.id
        await db.commit()
    directory = Directory()
    directory.managers[person.email] = "szefowa-z-katalogu@example.com"

    first = await _sync(directory, [person.id], date(2026, 10, 20))
    assert first["manager_changed"] == 1
    async with AsyncSessionLocal() as db:
        profile = await _profile(db, person.id)
        assert profile.m365_manager_upn == "szefowa-z-katalogu@example.com"
        assert profile.manager_user_id == boss.id, "katalog tylko podpowiada"

    # Błąd odczytu przełożonego: podpowiedź zostaje, przebieg idzie dalej.
    directory.manager_errors[person.email] = MailboxError(500)
    failed = await _sync(directory, [person.id], date(2026, 10, 21))
    assert failed["manager_errors"] == 1 and "failed" not in failed
    async with AsyncSessionLocal() as db:
        profile = await _profile(db, person.id)
        assert profile.m365_manager_upn == "szefowa-z-katalogu@example.com"

    # Brak przełożonego w katalogu (404 w Graph) — podpowiedź znika.
    directory.manager_errors.clear()
    directory.managers.pop(person.email)
    cleared = await _sync(directory, [person.id], date(2026, 10, 22))
    assert cleared["manager_changed"] == 1
    async with AsyncSessionLocal() as db:
        assert (await _profile(db, person.id)).m365_manager_upn is None

    # Odmowa dla całej rejestracji przerywa przebieg jak przy odczycie konta.
    directory.manager_errors[person.email] = MailboxError(403)
    forbidden = await _sync(directory, [person.id], date(2026, 10, 23))
    assert forbidden["failed"] == "forbidden"


@pytest.mark.asyncio
async def test_simulate_builds_the_manager_request_and_writes_nothing(
    people_module,
) -> None:
    async with AsyncSessionLocal() as db:
        person = await make_user(db)
        await db.commit()
    recorder = SimulatedDirectoryOps()
    result = await _sync(recorder, [person.id], date(2026, 10, 20), mode="simulate")
    assert [entry["path"] for entry in recorder.requests] == [
        f"/users/{person.email}",
        f"/users/{person.email}/manager",
    ]
    assert recorder.requests[1]["params"] == {"$select": "userPrincipalName"}
    assert result["manager_request"] == profile_sync.MANAGER_REQUEST_TEMPLATE
    assert "manager_changed" not in result
    async with AsyncSessionLocal() as db:
        assert (await _profile(db, person.id)).m365_manager_upn is None
