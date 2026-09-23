"""Edytor „Cele KPI" (plan PR3, 23.09.2026) — precedencja, aliasy, historia, dostęp.

Testy na żywym Postgresie przez prawdziwe trasy. `kpi_role_defaults` jest
GLOBALNA (próg Wyścigu Rekomendacji czyta ją przy każdym odczycie), więc każdy
test przywraca katalog w `finally` — inaczej zostawiłby odstępstwo innym suitom.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.kpi_target import KpiRoleDefault, UserKpiTarget
from app.models.kpi_target_event import KpiTargetEvent
from app.models.user import User, UserRole

pytestmark = pytest.mark.asyncio

URL = "/api/kpi-targets"


async def _login_as(client: AsyncClient, role: UserRole) -> tuple[int, dict]:
    unique = uuid.uuid4().hex[:8]
    email = f"kpi-editor-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Kpi"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            name=f"KPI {role.value} {unique}",
            password_hash=hash_password(password),
            role=role,
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        user_id = user.id
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return user_id, {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _role_rows(role: UserRole, ids: tuple[str, ...]) -> list[tuple[str, int]]:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(KpiRoleDefault.kpi_id, KpiRoleDefault.target_value).where(
                    KpiRoleDefault.role == role, KpiRoleDefault.kpi_id.in_(ids)
                )
            )
        ).all()
    return sorted((r.kpi_id, int(r.target_value)) for r in rows)


async def _reset_role(role: UserRole, ids: tuple[str, ...]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(KpiRoleDefault).where(
                KpiRoleDefault.role == role, KpiRoleDefault.kpi_id.in_(ids)
            )
        )
        await db.commit()


def _cell(matrix: dict, role: str, kpi_id: str) -> dict:
    row = next(r for r in matrix["roles"] if r["role"] == role)
    return row["targets"][kpi_id]


async def test_recruiter_gets_403_and_hor_can_edit(app_client: AsyncClient) -> None:
    _, recruiter = await _login_as(app_client, UserRole.recruiter)
    resp = await app_client.get(URL, headers=recruiter)
    assert resp.status_code == 403
    resp = await app_client.put(
        f"{URL}/role-default",
        json={"role": "recruiter", "kpi_id": "weekly_cvs_sent", "target_value": 99},
        headers=recruiter,
    )
    assert resp.status_code == 403
    resp = await app_client.get(f"{URL}/history", headers=recruiter)
    assert resp.status_code == 403

    _, hor = await _login_as(app_client, UserRole.head_of_recruitment)
    resp = await app_client.get(URL, headers=hor)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert {r["role"] for r in body["roles"]} == {"recruiter", "sourcer", "tac"}
    assert {k["kpi_id"] for k in body["kpis"]} >= {"daily_first_verifications"}


async def test_role_default_equal_to_catalog_deletes_the_row(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    ids = ("weekly_cvs_sent",)
    try:
        resp = await app_client.put(
            f"{URL}/role-default",
            json={"role": "recruiter", "kpi_id": "weekly_cvs_sent", "target_value": 20},
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        cell = _cell(resp.json(), "recruiter", "weekly_cvs_sent")
        assert cell == {"catalog_default": 15, "override": 20, "effective": 20}
        assert await _role_rows(UserRole.recruiter, ids) == [("weekly_cvs_sent", 20)]

        # 15 = katalog → odstępstwo znika (lustro normalizacji 0346).
        resp = await app_client.put(
            f"{URL}/role-default",
            json={"role": "recruiter", "kpi_id": "weekly_cvs_sent", "target_value": 15},
            headers=app_auth_headers,
        )
        assert resp.status_code == 200
        assert _cell(resp.json(), "recruiter", "weekly_cvs_sent")["override"] is None
        assert await _role_rows(UserRole.recruiter, ids) == []

        history = (
            await app_client.get(f"{URL}/history", headers=app_auth_headers)
        ).json()["items"]
        mine = [
            h
            for h in history
            if h["kpi_id"] == "weekly_cvs_sent" and h["role"] == "recruiter"
        ][:2]
        assert [(h["action"], h["from_value"], h["to_value"]) for h in mine] == [
            ("reset", 20, None),
            ("set", None, 20),
        ]
        assert mine[0]["actor_name"] == "Pytest Admin"
        assert mine[0]["role_label"] == "Rekruter"
    finally:
        await _reset_role(UserRole.recruiter, ids)


async def test_alias_rows_are_rewritten_to_the_canonical_id(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    ids = ("daily_first_verifications", "verifications_daily")
    await _reset_role(UserRole.sourcer, ids)
    async with AsyncSessionLocal() as db:
        db.add(
            KpiRoleDefault(
                role=UserRole.sourcer, kpi_id="verifications_daily", target_value=7
            )
        )
        await db.commit()
    try:
        before = (await app_client.get(URL, headers=app_auth_headers)).json()
        assert _cell(before, "sourcer", "daily_first_verifications")["override"] == 7

        resp = await app_client.put(
            f"{URL}/role-default",
            json={
                "role": "sourcer",
                # stary id z panelu „Moje KPI" — zapis idzie pod kanonicznym
                "kpi_id": "verifications_daily",
                "target_value": 6,
            },
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        assert await _role_rows(UserRole.sourcer, ids) == [
            ("daily_first_verifications", 6)
        ]
    finally:
        await _reset_role(UserRole.sourcer, ids)


async def test_personal_target_precedence_and_reset(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    subject_id, _ = await _login_as(app_client, UserRole.recruiter)
    async with AsyncSessionLocal() as db:
        db.add(
            UserKpiTarget(
                user_id=subject_id, kpi_id="placements_monthly", target_value=3
            )
        )
        await db.commit()

    def person(matrix: dict) -> dict:
        return next(u for u in matrix["users"] if u["user_id"] == subject_id)[
            "targets"
        ]["monthly_placements"]

    # Ta sama wartość: bez wpisu w historii, ale wiersz aliasu przepisany.
    resp = await app_client.put(
        f"{URL}/user-target",
        json={"user_id": subject_id, "kpi_id": "monthly_placements", "target_value": 3},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert person(resp.json()) == {"effective": 3, "override": 3, "source": "user"}
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(UserKpiTarget.kpi_id).where(UserKpiTarget.user_id == subject_id)
            )
        ).all()
        events = (
            await db.execute(
                select(KpiTargetEvent).where(
                    KpiTargetEvent.subject_user_id == subject_id
                )
            )
        ).all()
    assert [r.kpi_id for r in rows] == ["monthly_placements"]
    assert events == []

    # Osobisty cel równy katalogowi ZOSTAJE — to decyzja o tej osobie.
    resp = await app_client.put(
        f"{URL}/user-target",
        json={"user_id": subject_id, "kpi_id": "monthly_placements", "target_value": 1},
        headers=app_auth_headers,
    )
    assert person(resp.json()) == {"effective": 1, "override": 1, "source": "user"}

    resp = await app_client.put(
        f"{URL}/user-target",
        json={
            "user_id": subject_id,
            "kpi_id": "monthly_placements",
            "target_value": None,
        },
        headers=app_auth_headers,
    )
    cell = person(resp.json())
    assert cell["override"] is None and cell["source"] == "role"

    history = (await app_client.get(f"{URL}/history", headers=app_auth_headers)).json()[
        "items"
    ]
    mine = [h for h in history if h["subject_user_id"] == subject_id]
    assert [(h["action"], h["from_value"], h["to_value"]) for h in mine] == [
        ("reset", 1, None),
        ("set", 3, 1),
    ]


async def test_invalid_payloads_are_refused_in_polish(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    resp = await app_client.put(
        f"{URL}/role-default",
        json={"role": "recruiter", "kpi_id": "nie_ma_takiego", "target_value": 1},
        headers=app_auth_headers,
    )
    assert resp.status_code == 422
    assert "Nieznany wskaźnik" in resp.json()["detail"]
    resp = await app_client.put(
        f"{URL}/role-default",
        json={"role": "admin", "kpi_id": "weekly_cvs_sent", "target_value": 1},
        headers=app_auth_headers,
    )
    assert resp.status_code == 422
    resp = await app_client.put(
        f"{URL}/user-target",
        json={"user_id": 2_000_000_000, "kpi_id": "weekly_cvs_sent", "target_value": 1},
        headers=app_auth_headers,
    )
    assert resp.status_code == 404
