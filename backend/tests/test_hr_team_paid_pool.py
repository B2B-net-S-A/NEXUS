"""„Mój zespół”: ``leave.has_paid_pool`` jak w saldzie osoby (17.10.2026).

Front decyduje po nim, czy pokazać „zostało” (pula płatnych dni > 0), czy
zaplanowane nieobecności. Znaczenie to samo co w ``GET /api/hr/leave/balance``
— pula zerowa (B2B bez umownych dni) to dni bez wynagrodzenia, więc
``has_pool`` bywa ``true`` przy ``has_paid_pool = false``. Dane fikcyjne.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.hr_profile import LeaveEntitlement
from tests.test_hr_team_api import (  # noqa: F401 — fikstura
    BASE,
    _headers,
    _user,
    _world,
    modules,
)


@pytest.mark.asyncio
async def test_team_leave_has_paid_pool_matches_own_balance(
    app_client,
    modules,  # noqa: F811
) -> None:
    world = await _world()
    async with AsyncSessionLocal() as db:
        zero_pool = await _user(db, manager_user_id=world["boss"].id)  # B2B
        db.add(
            LeaveEntitlement(
                user_id=zero_pool.id,
                year=business_today().year,
                entitlement_days=Decimal("0"),
            )
        )
        await db.commit()

    response = await app_client.get(BASE, headers=_headers(world["boss"]))
    assert response.status_code == 200, response.text
    rows = {row["user_id"]: row["leave"] for row in response.json()["people"]}
    expected = {
        world["sick"].id: (True, True),  # UoP z pulą 20 dni
        world["contractor"].id: (False, False),  # B2B bez puli
        zero_pool.id: (True, False),  # B2B z pulą 0 — dni bez wynagrodzenia
    }
    for user_id, (has_pool, has_paid_pool) in expected.items():
        assert rows[user_id]["has_pool"] is has_pool, user_id
        assert rows[user_id]["has_paid_pool"] is has_paid_pool, user_id

    for person in (world["sick"], world["contractor"], zero_pool):
        own = await app_client.get("/api/hr/leave/balance", headers=_headers(person))
        assert own.status_code == 200, own.text
        assert own.json()["has_paid_pool"] is rows[person.id]["has_paid_pool"]
