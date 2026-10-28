"""„Nowe osoby do ustawienia” (0612, decyzje Artura 28.10.2026).

Pierwsze logowanie przez Microsoft zakłada konto „Konsultant/Kontraktor”;
Head of Recruitment i admini dostają dzwonek i mail, osoba stoi w „Czeka na
Ciebie”, a okno „Ustaw” zmienia rolę na Rekrutera, nadaje kategorie
i przełożonego. Baza testowa jest wspólna — testy asertują tylko po swoich
kontach.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.services import new_person_setup
from app.services.new_person_setup_schema import BACKFILL_SQL, COLUMN_DDL, ENUM_DDL
from app.services.notification_mail_card import build_card

_DB = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="wymaga PostgreSQL")
ENTRYPOINT = Path(__file__).resolve().parent.parent / "entrypoint.sh"


# ── Bez bazy ──────────────────────────────────────────────────────────────────


def test_entrypoint_mirrors_the_migration_ddl() -> None:
    text = ENTRYPOINT.read_text(encoding="utf-8")
    for statement in (ENUM_DDL, COLUMN_DDL, BACKFILL_SQL):
        assert f'"{statement}"' in text


def test_mail_buttons_open_the_window_and_never_decide() -> None:
    card = build_card(
        notification_type="new_person_signed_in",
        kind="new_person",
        title="Nowa osoba w NEXUSIE: Osoba Testowa",
        message="Pierwsze logowanie…",
        link=new_person_setup.setup_link(42),
        required=False,
    )
    assert card.action == "Zdecyduj, kim jest nowa osoba"
    assert [b.label for b in card.buttons] == ["Zdecyduj", "Zostaw jako Konsultanta"]
    assert card.buttons[0].path == "/dashboard?nowa-osoba=42#czeka-na-ciebie"
    assert card.buttons[1].path == "/dashboard?nowa-osoba=42&zostaw=1#czeka-na-ciebie"
    assert not any(b.path.startswith("/api") for b in card.buttons)


# ── Z bazą ────────────────────────────────────────────────────────────────────


async def _user(
    role: str, *, roles: list[str] | None = None, pending: bool = False
) -> tuple[int, dict[str, str]]:
    from datetime import datetime, timezone

    from app.core.database import AsyncSessionLocal
    from app.core.security import create_access_token
    from app.models.user import User, UserRole

    tag = uuid.uuid4().hex[:8]
    values = roles or [role]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"np-{role}-{tag}@example.com",
            name=f"NP {role} {tag}",
            role=UserRole(role),
            roles=values,
            is_active=True,
            profile_completed=True,
            setup_pending_since=datetime.now(timezone.utc) if pending else None,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        token = create_access_token(
            user.id,
            role,
            roles=values,
            authorization_version=user.authorization_version,
        )
        return user.id, {"Authorization": f"Bearer {token}"}


async def _category_id(slug: str = "security_quality") -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.competence_category import CompetenceCategory

    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(CompetenceCategory.id).where(CompetenceCategory.slug == slug)
        )


@_DB
@pytest.mark.asyncio
async def test_first_login_marks_the_account_and_rings_hor_and_admins() -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.notification import Notification, NotificationType
    from app.models.user import User

    hor_id, _ = await _user("head_of_recruitment")
    recruiter_id, _ = await _user("recruiter")
    newcomer_id, _ = await _user("employee")
    async with AsyncSessionLocal() as db:
        newcomer = await db.get(User, newcomer_id)
        sent = await new_person_setup.mark_and_notify(db, newcomer)
        await db.commit()
        assert sent >= 1
        assert newcomer.setup_pending_since is not None
        rows = (
            await db.execute(
                select(Notification.user_id, Notification.link).where(
                    Notification.notification_type
                    == NotificationType.new_person_signed_in,
                    Notification.related_entity_id == newcomer_id,
                )
            )
        ).all()
    recipients = {user_id for user_id, _ in rows}
    assert hor_id in recipients
    assert recruiter_id not in recipients
    assert {link for _, link in rows} == {new_person_setup.setup_link(newcomer_id)}


@_DB
@pytest.mark.asyncio
async def test_account_with_another_role_does_not_wait() -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.user import User

    recruiter_id, _ = await _user("recruiter")
    async with AsyncSessionLocal() as db:
        user = await db.get(User, recruiter_id)
        assert await new_person_setup.mark_and_notify(db, user) == 0
        assert user.setup_pending_since is None


@_DB
@pytest.mark.asyncio
async def test_hor_makes_a_recruiter_with_category_and_manager(
    app_client: AsyncClient,
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.activity import Activity
    from app.models.competence_category import UserCompetenceCategory
    from app.models.hr_profile import EmployeeProfile
    from app.models.user import User

    hor_id, hor = await _user("head_of_recruitment")
    newcomer_id, _ = await _user("employee", pending=True)
    qa = await _category_id()

    board = (await app_client.get("/api/board-tasks", headers=hor)).json()
    row = next(r for r in board["new_people"] if r["user_id"] == newcomer_id)
    assert row["needs_decision"] is True

    resp = await app_client.post(
        f"/api/people-setup/{newcomer_id}",
        json={
            "decision": "recruiter",
            "first_category_id": qa,
            "manager_user_id": hor_id,
        },
        headers=hor,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["role_granted"] is True

    async with AsyncSessionLocal() as db:
        user = await db.get(User, newcomer_id)
        assert user.roles == ["recruiter"]
        assert user.profile_completed is False  # onboarding rekrutera
        assert user.setup_pending_since is None
        priorities = (
            await db.scalars(
                select(UserCompetenceCategory.priority).where(
                    UserCompetenceCategory.user_id == newcomer_id,
                    UserCompetenceCategory.competence_category_id == qa,
                )
            )
        ).all()
        assert priorities == [1]
        manager = await db.scalar(
            select(EmployeeProfile.manager_user_id).where(
                EmployeeProfile.user_id == newcomer_id
            )
        )
        assert manager == hor_id
        actions = set(
            (
                await db.scalars(
                    select(Activity.action).where(
                        Activity.entity_type == "user",
                        Activity.entity_id == newcomer_id,
                        Activity.user_id == hor_id,
                    )
                )
            ).all()
        )
    assert {"role_changed", "new_person_setup_decided"} <= actions

    board = (await app_client.get("/api/board-tasks", headers=hor)).json()
    assert newcomer_id not in {r["user_id"] for r in board["new_people"]}


@_DB
@pytest.mark.asyncio
async def test_hor_cannot_pick_any_manager_and_nothing_is_saved(
    app_client: AsyncClient,
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.user import User

    _, hor = await _user("head_of_recruitment")
    other_id, _ = await _user("recruiter")
    newcomer_id, _ = await _user("employee", pending=True)
    resp = await app_client.post(
        f"/api/people-setup/{newcomer_id}",
        json={"decision": "recruiter", "manager_user_id": other_id},
        headers=hor,
    )
    assert resp.status_code == 403
    async with AsyncSessionLocal() as db:
        user = await db.get(User, newcomer_id)
        assert user.roles == ["employee"]
        assert user.setup_pending_since is not None


@_DB
@pytest.mark.asyncio
async def test_keep_as_consultant_only_clears_the_marker(
    app_client: AsyncClient,
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.user import User

    _, hor = await _user("head_of_recruitment")
    newcomer_id, _ = await _user("employee", pending=True)
    resp = await app_client.post(
        f"/api/people-setup/{newcomer_id}",
        json={"decision": "employee"},
        headers=hor,
    )
    assert resp.status_code == 200, resp.text
    async with AsyncSessionLocal() as db:
        user = await db.get(User, newcomer_id)
        assert user.roles == ["employee"]
        assert user.setup_pending_since is None


@_DB
@pytest.mark.asyncio
async def test_other_roles_stay_with_the_admin(app_client: AsyncClient) -> None:
    _, hor = await _user("head_of_recruitment")
    finance_id, _ = await _user("finance")
    resp = await app_client.post(
        f"/api/people-setup/{finance_id}",
        json={"decision": "recruiter"},
        headers=hor,
    )
    assert resp.status_code == 422
    assert "Osoby i role" in resp.json()["detail"]


@_DB
@pytest.mark.asyncio
async def test_recruiter_cannot_set_people_up(app_client: AsyncClient) -> None:
    _, recruiter = await _user("recruiter")
    newcomer_id, _ = await _user("employee", pending=True)
    resp = await app_client.post(
        f"/api/people-setup/{newcomer_id}",
        json={"decision": "recruiter"},
        headers=recruiter,
    )
    assert resp.status_code == 403
    board = (await app_client.get("/api/board-tasks", headers=recruiter)).json()
    assert board["new_people"] == []


@_DB
@pytest.mark.asyncio
async def test_recruiter_without_category_is_listed_with_what_is_missing(
    app_client: AsyncClient,
) -> None:
    _, hor = await _user("head_of_recruitment")
    recruiter_id, _ = await _user("recruiter")
    board = (await app_client.get("/api/board-tasks", headers=hor)).json()
    row = next(r for r in board["new_people"] if r["user_id"] == recruiter_id)
    assert row["needs_decision"] is False
    assert "categories" in row["missing"]

    qa = await _category_id()
    resp = await app_client.post(
        f"/api/people-setup/{recruiter_id}",
        json={"decision": "recruiter", "first_category_id": qa},
        headers=hor,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["role_granted"] is False
    board = (await app_client.get("/api/board-tasks", headers=hor)).json()
    row = next((r for r in board["new_people"] if r["user_id"] == recruiter_id), None)
    assert row is None or "categories" not in row["missing"]


@_DB
@pytest.mark.asyncio
async def test_role_change_in_people_and_roles_clears_the_marker(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.user import User

    newcomer_id, _ = await _user("employee", pending=True)
    resp = await app_client.put(
        f"/api/admin/users/{newcomer_id}",
        json={"role": "delivery_lead", "roles": ["delivery_lead"]},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    async with AsyncSessionLocal() as db:
        assert (await db.get(User, newcomer_id)).setup_pending_since is None


@_DB
@pytest.mark.asyncio
async def test_hor_cannot_promote_a_consultant_who_is_not_waiting(
    app_client: AsyncClient,
) -> None:
    """Przegląd kodu 28.10: HoR decyduje tylko o NOWYM koncie — konsultant
    zostawiony świadomie (bez znacznika) nie staje się rekruterem."""
    from app.core.database import AsyncSessionLocal
    from app.models.user import User

    _, hor = await _user("head_of_recruitment")
    consultant_id, _ = await _user("employee")
    for decision in ("recruiter", "employee"):
        resp = await app_client.post(
            f"/api/people-setup/{consultant_id}",
            json={"decision": decision},
            headers=hor,
        )
        assert resp.status_code == 422, resp.text
    async with AsyncSessionLocal() as db:
        assert (await db.get(User, consultant_id)).roles == ["employee"]


@_DB
@pytest.mark.asyncio
async def test_hor_cannot_take_over_someone_elses_manager_slot(
    app_client: AsyncClient,
) -> None:
    """Przegląd kodu 28.10: przełożonego HoR ustawia tylko osobie, która go
    nie ma — nie przejmuje cudzego zespołu ani konta admina/HoR."""
    from app.core.database import AsyncSessionLocal
    from app.models.hr_profile import EmployeeProfile
    from app.models.user import User
    from app.services.hr import account_profiles
    from app.services.hr import structure as hr_structure

    other_hor_id, _ = await _user("head_of_recruitment")
    hor_id, hor = await _user("head_of_recruitment")
    recruiter_id, _ = await _user("recruiter")
    leader_id, _ = await _user(
        "admin", roles=["admin", "head_of_recruitment", "recruiter"]
    )
    async with AsyncSessionLocal() as db:
        actor = await db.get(User, other_hor_id)
        for uid in (recruiter_id, leader_id):
            await account_profiles.ensure_profile(
                db, await db.get(User, uid), actor_id=None, source="test"
            )
        await hr_structure.reassign(
            db, user_ids=[recruiter_id], manager_user_id=other_hor_id, actor=actor
        )
        await db.commit()

    for target in (recruiter_id, leader_id):
        resp = await app_client.post(
            f"/api/people-setup/{target}",
            json={"decision": "recruiter", "manager_user_id": hor_id},
            headers=hor,
        )
        assert resp.status_code in (403, 422), resp.text
    async with AsyncSessionLocal() as db:
        manager = await db.scalar(
            select(EmployeeProfile.manager_user_id).where(
                EmployeeProfile.user_id == recruiter_id
            )
        )
    assert manager == other_hor_id
