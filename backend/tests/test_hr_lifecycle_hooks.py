"""Haki spraw wejścia i odejścia dla modułów Spraw i Sprzętu (przegląd 17.10.2026).

* hak Spraw pyta o przełącznik modułu ``cases`` jak hak Sprzętu o swój —
  przy wyłączonym module nie woła modułu Spraw wcale (ani założenie, ani
  zamknięcie sprawy „Odejście: …”),
* odczyt nazw do odpowiedzi nie zmienia zbioru, który dostał.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.app_setting import AppSetting
from app.models.hr_lifecycle import LifecycleCase
from app.models.user import User, UserRole
from app.services.admin_cases import hooks as case_hooks
from app.services.hr import lifecycle_hooks, lifecycle_payloads
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING


async def _set_modules(value: dict) -> object:
    async with AsyncSessionLocal() as db:
        previous = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == HR_MODULES_SETTING)
        )
        row = await db.get(AppSetting, HR_MODULES_SETTING)
        if row is None:
            db.add(AppSetting(key=HR_MODULES_SETTING, value=value))
        else:
            row.value = value
        await db.commit()
    return previous


@pytest.mark.asyncio
@pytest.mark.parametrize("event", ["offboarding_started", "offboarding_cancelled"])
async def test_cases_hook_stays_out_while_the_cases_module_is_off(
    monkeypatch, event: str
) -> None:
    calls: list[str] = []

    async def spy(db, user_id, case_id):  # noqa: ANN001
        calls.append(event)

    monkeypatch.setattr(case_hooks, "open_case_for_offboarding", spy)
    monkeypatch.setattr(case_hooks, "close_case_for_cancelled_offboarding", spy)
    case = LifecycleCase(id=1, kind="offboarding", user_id=1, status="active")

    previous = await _set_modules({key: key != "cases" for key in HR_MODULE_KEYS})
    try:
        async with AsyncSessionLocal() as db:
            await lifecycle_hooks._cases_hook(db, case, event)
        assert calls == []

        await _set_modules({key: True for key in HR_MODULE_KEYS})
        async with AsyncSessionLocal() as db:
            await lifecycle_hooks._cases_hook(db, case, event)
        assert calls == [event]
    finally:
        await _set_modules(previous or {key: False for key in HR_MODULE_KEYS})


@pytest.mark.asyncio
async def test_names_lookup_leaves_the_callers_set_alone() -> None:
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"anna.przykladowa.{uuid.uuid4().hex[:8]}@example.com",
            name="Anna Przykładowa",
            role=UserRole.recruiter,
            roles=["recruiter"],
            is_active=True,
        )
        db.add(user)
        await db.flush()
        ids = {user.id, None}
        names = await lifecycle_payloads._names(db, ids)
        await db.rollback()

    assert names == {user.id: "Anna Przykładowa"}
    assert None in ids and len(ids) == 2
