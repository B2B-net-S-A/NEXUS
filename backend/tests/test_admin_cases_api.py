"""Sprawy administracja@ (E6): dostęp, zapis, komentarze, powiadomienie o przypisaniu.

* obsługa = uprawnienie „Sprawy” (domyślnie Talent Community Manager) albo admin,
* osoba przypisana bez uprawnienia widzi i komentuje tylko swoje sprawy,
* reszta 403, wyłączony moduł 404.

Baza testowa nie jest czyszczona między testami — asercje dotyczą wyłącznie
spraw i kont założonych w danym teście. Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select, update

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.core.security import create_access_token
from app.models.admin_case import AdminCase
from app.models.app_setting import AppSetting
from app.models.hr_ops import HrAuditEvent
from app.models.notification import Notification, NotificationType
from app.models.section_permission import UserActionOverride
from app.models.user import User, UserRole
from app.services.admin_cases.queries import week_end
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _user(db, role: str, *, active: bool = True) -> User:
    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"cases-{marker}@example.com",
        name=f"Osoba Przykładowa {marker}",
        role=UserRole(role),
        roles=[role],
        is_active=active,
        profile_completed=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _set_modules(value: dict) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, HR_MODULES_SETTING)
        if row is None:
            db.add(AppSetting(key=HR_MODULES_SETTING, value=value))
        else:
            row.value = value
        await db.commit()


async def _modules_fixture(value: dict):
    async with AsyncSessionLocal() as db:
        previous = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == HR_MODULES_SETTING)
        )
    await _set_modules(value)
    yield
    await _set_modules(previous or {key: False for key in HR_MODULE_KEYS})


@pytest_asyncio.fixture
async def modules_on():
    async for _ in _modules_fixture({key: True for key in HR_MODULE_KEYS}):
        yield


@pytest_asyncio.fixture
async def modules_off():
    async for _ in _modules_fixture({key: False for key in HR_MODULE_KEYS}):
        yield


@pytest_asyncio.fixture
async def team():
    """TCM (obsługa z roli), rekruter z nadanym „Sprawy”, zwykły rekruter, admin."""
    async with AsyncSessionLocal() as db:
        tcm = await _user(db, "talent_community_manager")
        granted = await _user(db, "recruiter")
        db.add(UserActionOverride(user_id=granted.id, action="cases", access="manage"))
        plain = await _user(db, "recruiter")
        other = await _user(db, "recruiter")
        admin = await _user(db, "admin")
        await db.commit()
    return {
        "tcm": tcm,
        "granted": granted,
        "plain": plain,
        "other": other,
        "admin": admin,
    }


async def _create(app_client, actor: User, **payload) -> dict:
    body = {"title": "Faktura za szkolenie BHP", "area": "administration", **payload}
    response = await app_client.post("/api/cases", json=body, headers=_headers(actor))
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_tcm_and_granted_handle_cases_recruiter_is_refused(
    app_client, modules_on, team
) -> None:
    created = await _create(app_client, team["tcm"], priority="P1")
    assert created["status"] == "new"
    assert created["priority"] == "P1"
    assert created["due_on"] is not None  # termin z SLA
    assert created["can_manage"] is True

    as_granted = await app_client.get(
        f"/api/cases/{created['id']}", headers=_headers(team["granted"])
    )
    assert as_granted.status_code == 200

    for path in ("/api/cases", f"/api/cases/{created['id']}"):
        refused = await app_client.get(path, headers=_headers(team["plain"]))
        assert refused.status_code == 403, path
    create_refused = await app_client.post(
        "/api/cases",
        json={"title": "Coś do zrobienia"},
        headers=_headers(team["plain"]),
    )
    assert create_refused.status_code == 403
    assert create_refused.json()["detail"]["permission"] == "cases"


@pytest.mark.asyncio
async def test_switched_off_module_is_404_except_for_admin(
    app_client, modules_off, team
) -> None:
    response = await app_client.get("/api/cases", headers=_headers(team["tcm"]))
    assert response.status_code == 404
    assert response.json()["detail"] == "Ten moduł nie jest jeszcze włączony."
    created = await _create(app_client, team["admin"])
    assert created["source"] == "manual"


@pytest.mark.asyncio
async def test_assignee_without_permission_sees_and_comments_only_own_cases(
    app_client, modules_on, team
) -> None:
    own = await _create(
        app_client,
        team["tcm"],
        title="Ubezpieczenie OC",
        assignee_user_id=team["plain"].id,
    )
    foreign = await _create(
        app_client,
        team["tcm"],
        title="Post na LinkedIn",
        assignee_user_id=team["other"].id,
    )

    listing = await app_client.get("/api/cases", headers=_headers(team["plain"]))
    assert listing.status_code == 200
    ids = {item["id"] for item in listing.json()["items"]}
    assert own["id"] in ids
    assert foreign["id"] not in ids
    assert listing.json()["can_manage"] is False

    detail = await app_client.get(
        f"/api/cases/{own['id']}", headers=_headers(team["plain"])
    )
    assert detail.status_code == 200
    assert detail.json()["can_manage"] is False
    assert detail.json()["can_comment"] is True

    hidden = await app_client.get(
        f"/api/cases/{foreign['id']}", headers=_headers(team["plain"])
    )
    assert hidden.status_code == 403
    missing = await app_client.get(
        "/api/cases/99999999", headers=_headers(team["plain"])
    )
    assert missing.status_code == 403  # nie zdradza, czy cudza sprawa istnieje

    comment = await app_client.post(
        f"/api/cases/{own['id']}/comments",
        json={"body": "Dzwoniłam do klienta, czekam na polisę."},
        headers=_headers(team["plain"]),
    )
    assert comment.status_code == 201
    foreign_comment = await app_client.post(
        f"/api/cases/{foreign['id']}/comments",
        json={"body": "Nie moja sprawa"},
        headers=_headers(team["plain"]),
    )
    assert foreign_comment.status_code == 403

    # Przypisany nie zmienia sprawy ani jej nie zamyka.
    edit = await app_client.patch(
        f"/api/cases/{own['id']}",
        json={"status": "done"},
        headers=_headers(team["plain"]),
    )
    assert edit.status_code == 403
    close = await app_client.post(
        f"/api/cases/{own['id']}/close", headers=_headers(team["plain"])
    )
    assert close.status_code == 403

    after = await app_client.get(
        f"/api/cases/{own['id']}", headers=_headers(team["tcm"])
    )
    assert [c["body"] for c in after.json()["comments"]] == [
        "Dzwoniłam do klienta, czekam na polisę."
    ]
    assert after.json()["status"] == "new"


@pytest.mark.asyncio
async def test_assignment_notifies_assignee_but_not_self(
    app_client, modules_on, team
) -> None:
    to_other = await _create(
        app_client,
        team["tcm"],
        title="Onboarding: Anna Przykładowa",
        assignee_user_id=team["granted"].id,
    )
    to_self = await _create(
        app_client,
        team["tcm"],
        title="Aneks dla konsultanta",
        assignee_user_id=team["tcm"].id,
    )
    reassigned = await app_client.patch(
        f"/api/cases/{to_self['id']}",
        json={"assignee_user_id": team["plain"].id},
        headers=_headers(team["tcm"]),
    )
    assert reassigned.status_code == 200

    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(
                select(Notification).where(
                    Notification.notification_type
                    == NotificationType.admin_case_assigned,
                    Notification.related_entity_id.in_((to_other["id"], to_self["id"])),
                )
            )
        ).all()
    by_user = {(n.user_id, n.related_entity_id) for n in rows}
    assert (team["granted"].id, to_other["id"]) in by_user
    assert (team["plain"].id, to_self["id"]) in by_user
    assert all(n.user_id != team["tcm"].id for n in rows)
    link = next(n.link for n in rows if n.related_entity_id == to_other["id"])
    assert link == f"/people/cases/{to_other['id']}"


@pytest.mark.asyncio
async def test_edit_checklist_status_and_close(app_client, modules_on, team) -> None:
    created = await _create(app_client, team["tcm"])
    patch = await app_client.patch(
        f"/api/cases/{created['id']}",
        json={
            "status": "in_progress",
            "priority": "P3",
            "follow_up_on": "2026-11-05",
            "checklist": [
                {"text": "Zamówić badania", "done": True},
                {"text": "  ", "done": False},
                {"text": "Szkolenie BHP"},
            ],
            "expected_updated_at": created["updated_at"],
        },
        headers=_headers(team["tcm"]),
    )
    assert patch.status_code == 200, patch.text
    body = patch.json()
    assert body["status"] == "in_progress"
    assert body["checklist"] == [
        {"text": "Zamówić badania", "done": True},
        {"text": "Szkolenie BHP", "done": False},
    ]
    assert (body["checklist_done"], body["checklist_total"]) == (1, 2)

    stale = await app_client.patch(
        f"/api/cases/{created['id']}",
        json={"status": "waiting", "expected_updated_at": created["updated_at"]},
        headers=_headers(team["granted"]),
    )
    assert stale.status_code == 409

    done = await app_client.patch(
        f"/api/cases/{created['id']}",
        json={"status": "done"},
        headers=_headers(team["tcm"]),
    )
    assert done.json()["closed_at"] is not None
    reopened = await app_client.patch(
        f"/api/cases/{created['id']}",
        json={"status": "in_progress"},
        headers=_headers(team["tcm"]),
    )
    assert reopened.json()["closed_at"] is None

    closed = await app_client.post(
        f"/api/cases/{created['id']}/close", headers=_headers(team["tcm"])
    )
    assert closed.status_code == 200
    assert closed.json()["status"] == "closed"

    board = await app_client.get("/api/cases", headers=_headers(team["tcm"]))
    assert created["id"] not in {item["id"] for item in board.json()["items"]}
    archive = await app_client.get(
        "/api/cases", params={"include_closed": "true"}, headers=_headers(team["tcm"])
    )
    assert created["id"] in {item["id"] for item in archive.json()["items"]}

    async with AsyncSessionLocal() as db:
        actions = (
            await db.scalars(
                select(HrAuditEvent.action)
                .where(
                    HrAuditEvent.entity_type == "admin_case",
                    HrAuditEvent.entity_id == str(created["id"]),
                )
                .order_by(HrAuditEvent.id)
            )
        ).all()
    assert actions[0] == "case_created"
    assert actions[-1] == "case_closed"


@pytest.mark.asyncio
async def test_invalid_input_is_refused_with_polish_message(
    app_client, modules_on, team
) -> None:
    async with AsyncSessionLocal() as db:
        gone = await _user(db, "recruiter", active=False)
        await db.commit()
    inactive = await app_client.post(
        "/api/cases",
        json={"title": "Sprawa dla nieaktywnego", "assignee_user_id": gone.id},
        headers=_headers(team["tcm"]),
    )
    assert inactive.status_code == 422
    assert "aktywnego konta" in inactive.json()["detail"]

    short = await app_client.post(
        "/api/cases", json={"title": "ab"}, headers=_headers(team["tcm"])
    )
    assert short.status_code == 422

    wrong_area = await app_client.post(
        "/api/cases",
        json={"title": "Coś", "area": "kadry"},
        headers=_headers(team["tcm"]),
    )
    assert wrong_area.status_code == 422

    created = await _create(app_client, team["tcm"])
    cleared_title = await app_client.patch(
        f"/api/cases/{created['id']}",
        json={"title": None},
        headers=_headers(team["tcm"]),
    )
    assert cleared_title.status_code == 422
    empty_comment = await app_client.post(
        f"/api/cases/{created['id']}/comments",
        json={"body": "   "},
        headers=_headers(team["tcm"]),
    )
    assert empty_comment.status_code == 422
    missing = await app_client.patch(
        "/api/cases/99999999", json={"status": "done"}, headers=_headers(team["tcm"])
    )
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_list_filters_mine_area_and_search(app_client, modules_on, team) -> None:
    marker = uuid.uuid4().hex[:8]
    mine = await _create(
        app_client,
        team["granted"],
        title=f"Negocjacje stawki {marker}",
        area="negotiation",
        assignee_user_id=team["granted"].id,
    )
    theirs = await _create(
        app_client, team["granted"], title=f"Post kariera {marker}", area="marketing"
    )
    headers = _headers(team["granted"])

    only_mine = await app_client.get(
        "/api/cases", params={"mine": "true"}, headers=headers
    )
    ids = {item["id"] for item in only_mine.json()["items"]}
    assert mine["id"] in ids and theirs["id"] not in ids

    by_area = await app_client.get(
        "/api/cases", params={"area": "marketing", "q": marker}, headers=headers
    )
    assert [item["id"] for item in by_area.json()["items"]] == [theirs["id"]]

    by_text = await app_client.get("/api/cases", params={"q": marker}, headers=headers)
    assert {item["id"] for item in by_text.json()["items"]} == {
        mine["id"],
        theirs["id"],
    }

    wildcard = await app_client.get("/api/cases", params={"q": "%"}, headers=headers)
    assert all("%" in item["title"] for item in wildcard.json()["items"])


@pytest.mark.asyncio
async def test_chips_week_and_unassigned_filter_on_server_with_counts(
    app_client, modules_on, team
) -> None:
    """Chipy „Na ten tydzień” i „Bez osoby” (makieta 19.10.2026) i ich liczniki."""

    marker = uuid.uuid4().hex[:8]
    today = business_today()
    friday = week_end(today)
    late = await _create(
        app_client,
        team["granted"],
        title=f"Po terminie {marker}",
        area="onboarding",
        due_on=(today - timedelta(days=3)).isoformat(),
    )
    this_week = await _create(
        app_client,
        team["granted"],
        title=f"Do piątku {marker}",
        area="onboarding",
        due_on=friday.isoformat(),
        assignee_user_id=team["granted"].id,
    )
    later = await _create(
        app_client,
        team["granted"],
        title=f"Później {marker}",
        area="marketing",
        due_on=(friday + timedelta(days=7)).isoformat(),
    )
    headers = _headers(team["granted"])

    week = await app_client.get(
        "/api/cases", params={"week": "true", "q": marker}, headers=headers
    )
    assert week.status_code == 200, week.text
    assert {item["id"] for item in week.json()["items"]} == {
        late["id"],
        this_week["id"],
    }
    assert week.json()["week_end"] == friday.isoformat()
    assert week.json()["today"] == today.isoformat()

    nobody = await app_client.get(
        "/api/cases", params={"unassigned": "true", "q": marker}, headers=headers
    )
    assert {item["id"] for item in nobody.json()["items"]} == {late["id"], later["id"]}

    # Liczniki nie zależą od włączonych chipów ani obszaru — tylko zakres i szukanie.
    counts = (
        await app_client.get(
            "/api/cases",
            params={"q": marker, "area": "marketing", "week": "true"},
            headers=headers,
        )
    ).json()["counts"]
    assert counts == {
        "areas": {"onboarding": 2, "marketing": 1},
        "week": 2,
        "unassigned": 2,
        "mine_care": 0,
    }

    # Zrobiona sprawa nie wisi w „Na ten tydzień”.
    done = await app_client.patch(
        f"/api/cases/{late['id']}", json={"status": "done"}, headers=headers
    )
    assert done.status_code == 200, done.text
    week = await app_client.get(
        "/api/cases", params={"week": "true", "q": marker}, headers=headers
    )
    assert [item["id"] for item in week.json()["items"]] == [this_week["id"]]

    # „Weź” = przypisanie do siebie istniejącą zmianą sprawy; cudza wersja → 409.
    stale = later["updated_at"]
    taken = await app_client.patch(
        f"/api/cases/{later['id']}",
        json={"assignee_user_id": team["tcm"].id, "expected_updated_at": stale},
        headers=_headers(team["tcm"]),
    )
    assert taken.status_code == 200, taken.text
    assert taken.json()["assignee"]["id"] == team["tcm"].id
    again = await app_client.patch(
        f"/api/cases/{later['id']}",
        json={"assignee_user_id": team["granted"].id, "expected_updated_at": stale},
        headers=headers,
    )
    assert again.status_code == 409, again.text

    # Osoba bez uprawnienia nie widzi spraw bez osoby, nawet z chipem.
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(AdminCase)
            .where(AdminCase.id == this_week["id"])
            .values(assignee_user_id=team["plain"].id)
        )
        await db.commit()
    plain = await app_client.get(
        "/api/cases",
        params={"unassigned": "true", "q": marker},
        headers=_headers(team["plain"]),
    )
    assert plain.status_code == 200, plain.text
    assert plain.json()["items"] == []
    assert plain.json()["counts"]["unassigned"] == 0


@pytest.mark.asyncio
async def test_saving_form_with_departed_assignee_keeps_working(
    app_client, modules_on, team
) -> None:
    async with AsyncSessionLocal() as db:
        leaving = await _user(db, "recruiter")
        await db.commit()
    created = await _create(app_client, team["tcm"], assignee_user_id=leaving.id)
    async with AsyncSessionLocal() as db:
        account = await db.get(User, leaving.id)
        account.is_active = False
        await db.commit()

    # Formularz odsyła wszystkie pola, także dawne przypisanie — to nie błąd.
    saved = await app_client.patch(
        f"/api/cases/{created['id']}",
        json={"priority": "P1", "assignee_user_id": leaving.id},
        headers=_headers(team["tcm"]),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["priority"] == "P1"

    # Nowe przypisanie do nieaktywnego konta już tak.
    other = await _create(app_client, team["tcm"])
    refused = await app_client.patch(
        f"/api/cases/{other['id']}",
        json={"assignee_user_id": leaving.id},
        headers=_headers(team["tcm"]),
    )
    assert refused.status_code == 422


@pytest.mark.asyncio
async def test_pickers_are_for_handlers_and_carry_no_amounts(
    app_client, modules_on, team
) -> None:
    assignees = await app_client.get(
        "/api/cases/assignees", headers=_headers(team["tcm"])
    )
    assert assignees.status_code == 200
    by_id = {item["id"]: item for item in assignees.json()["items"]}
    assert by_id[team["granted"].id]["handler"] is True
    assert by_id[team["plain"].id]["handler"] is False

    options = await app_client.get(
        "/api/cases/contract-options",
        params={"q": "Przykładow"},
        headers=_headers(team["tcm"]),
    )
    assert options.status_code == 200
    for item in options.json()["items"]:
        assert set(item) == {
            "id",
            "candidate_name",
            "client_name",
            "start_date",
            "end_date",
        }

    for path in ("/api/cases/assignees", "/api/cases/contract-options?q=ab"):
        refused = await app_client.get(path, headers=_headers(team["plain"]))
        assert refused.status_code == 403, path
