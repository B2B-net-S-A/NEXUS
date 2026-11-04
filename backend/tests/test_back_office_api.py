"""Kolejka back office'u: dostęp, „Biorę”, limit, zastępstwo, kroki, kwoty.

Baza testowa nie jest czyszczona między testami: asercje dotyczą wyłącznie kart
i kont założonych w danym teście. Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.core.security import create_access_token
from app.models.admin_case import AdminCase
from app.models.app_setting import AppSetting
from app.models.back_office import BoCard, BoTeamMember
from app.models.user import User, UserRole
from app.services.back_office import steps
from app.services.back_office.sync import sync_kinds
from app.services.back_office_schema import BACK_OFFICE_SETTING
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _user(role: str = "recruiter", *, teams: tuple[str, ...] = ()) -> User:
    marker = uuid.uuid4().hex[:10]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"bo-{marker}@example.com",
            name=f"Osoba Przykładowa {marker}",
            role=UserRole(role),
            roles=[role],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.flush()
        for team in teams:
            db.add(BoTeamMember(team=team, user_id=user.id))
        await db.commit()
        await db.refresh(user)
        return user


async def _card(**fields) -> BoCard:
    marker = uuid.uuid4().hex[:12]
    values = {
        "team": "orders",
        "lane": "gap",
        "source_kind": "gap",
        "source_key": f"test:{marker}",
        "title": "Przerwa po zamówieniu",
        "state": "new",
        "meta": {},
    }
    async with AsyncSessionLocal() as db:
        card = BoCard(**{**values, **fields})
        db.add(card)
        await db.commit()
        await db.refresh(card)
        return card


async def _set_modules(value: dict) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, HR_MODULES_SETTING)
        if row is None:
            db.add(AppSetting(key=HR_MODULES_SETTING, value=value))
        else:
            row.value = value
        await db.commit()


@pytest_asyncio.fixture
async def modules_on():
    async with AsyncSessionLocal() as db:
        previous = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == HR_MODULES_SETTING)
        )
        await db.execute(delete(BoTeamMember))
        await db.commit()
    await _set_modules({key: True for key in HR_MODULE_KEYS})
    yield
    await _set_modules(previous or {key: False for key in HR_MODULE_KEYS})
    async with AsyncSessionLocal() as db:
        await db.execute(delete(BoTeamMember))
        await db.execute(delete(BoCard).where(BoCard.source_key.like("test:%")))
        await db.commit()


@pytest.mark.asyncio
async def test_module_off_is_404_even_for_admin(app_client) -> None:
    async with AsyncSessionLocal() as db:
        previous = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == HR_MODULES_SETTING)
        )
    await _set_modules({key: key != "back_office" for key in HR_MODULE_KEYS})
    try:
        admin = await _user("admin")
        response = await app_client.get(
            "/api/back-office/board", headers=_headers(admin)
        )
        assert response.status_code == 404
    finally:
        await _set_modules(previous or {key: False for key in HR_MODULE_KEYS})


@pytest.mark.asyncio
async def test_people_outside_teams_get_403(app_client, modules_on) -> None:
    await _user("recruiter", teams=("care",))  # skład wpisany: bez domyślnych
    outsider = await _user("recruiter")
    response = await app_client.get(
        "/api/back-office/board", headers=_headers(outsider)
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_member_cannot_use_lead_routes(app_client, modules_on) -> None:
    member = await _user("recruiter", teams=("orders",))
    target = await _card()
    for method, url, body in (
        ("post", f"/api/back-office/cards/{target.id}/assign", {"user_id": member.id}),
        ("post", "/api/back-office/sync", {}),
        ("get", "/api/back-office/team", None),
        ("put", "/api/back-office/team/care", {"user_ids": []}),
        ("put", "/api/back-office/deputy", {"user_id": None}),
        ("post", f"/api/back-office/cards/{target.id}/review", {"decision": "current"}),
    ):
        kwargs = {"headers": _headers(member)}
        if body is not None:
            kwargs["json"] = body
        response = await getattr(app_client, method)(url, **kwargs)
        assert response.status_code == 403, url


@pytest.mark.asyncio
async def test_take_then_second_person_gets_409(app_client, modules_on) -> None:
    first = await _user("recruiter", teams=("orders",))
    second = await _user("recruiter", teams=("orders",))
    card = await _card()
    taken = await app_client.post(
        f"/api/back-office/cards/{card.id}/take", json={}, headers=_headers(first)
    )
    assert taken.status_code == 200
    assert taken.json()["assignee"]["id"] == first.id
    assert taken.json()["state"] == "in_progress"
    again = await app_client.post(
        f"/api/back-office/cards/{card.id}/take", json={}, headers=_headers(second)
    )
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "taken"


@pytest.mark.asyncio
async def test_stale_version_gets_409(app_client, modules_on) -> None:
    member = await _user("recruiter", teams=("orders",))
    card = await _card()
    response = await app_client.post(
        f"/api/back-office/cards/{card.id}/take",
        json={"expected_updated_at": "2020-01-01T00:00:00+00:00"},
        headers=_headers(member),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stale"


@pytest.mark.asyncio
async def test_limit_blocks_only_new_take(app_client, modules_on) -> None:
    member = await _user("recruiter", teams=("orders",))
    for _ in range(5):
        await _card(assignee_user_id=member.id, state="in_progress")
    extra = await _card()
    blocked = await app_client.post(
        f"/api/back-office/cards/{extra.id}/take", json={}, headers=_headers(member)
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "limit"
    # Kierownik może przydzielić ponad limit.
    lead = await _user("admin")
    assigned = await app_client.post(
        f"/api/back-office/cards/{extra.id}/assign",
        json={"user_id": member.id},
        headers=_headers(lead),
    )
    assert assigned.status_code == 200


@pytest.mark.asyncio
async def test_other_team_needs_substitute_and_sees_no_amounts(
    app_client, modules_on
) -> None:
    other = await _user("recruiter", teams=("care",))
    card = await _card()
    refused = await app_client.post(
        f"/api/back-office/cards/{card.id}/take", json={}, headers=_headers(other)
    )
    assert refused.status_code == 403
    ok = await app_client.post(
        f"/api/back-office/cards/{card.id}/take",
        json={"substitute": True},
        headers=_headers(other),
    )
    assert ok.status_code == 200
    assert ok.json()["substituting"] is True

    bonus = await _card(
        team="finance",
        lane="bonus",
        source_kind="bonus",
        title="Premie 10.2026",
        meta={"year": 2026, "month": 10, "count": 1},
    )
    detail = await app_client.get(
        f"/api/back-office/cards/{bonus.id}", headers=_headers(other)
    )
    assert detail.status_code == 200
    body = detail.json()
    assert body["amounts"] is None
    assert body["actions"] == []
    assert "bonuses" not in body


@pytest.mark.asyncio
async def test_priority_needs_override(app_client, modules_on) -> None:
    today = business_today()
    holder = await _user("recruiter", teams=("orders",))
    member = await _user("recruiter", teams=("orders",))
    card = await _card(
        priority_user_id=holder.id, priority_until=today + timedelta(days=3)
    )
    blocked = await app_client.post(
        f"/api/back-office/cards/{card.id}/take", json={}, headers=_headers(member)
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "priority"
    ok = await app_client.post(
        f"/api/back-office/cards/{card.id}/take",
        json={"override_priority": True},
        headers=_headers(member),
    )
    assert ok.status_code == 200


@pytest.mark.asyncio
async def test_waiting_needs_a_person_and_dismiss_needs_a_reason(
    app_client, modules_on
) -> None:
    member = await _user("recruiter", teams=("orders",))
    card = await _card()
    headers = _headers(member)
    missing = await app_client.post(
        f"/api/back-office/cards/{card.id}/state",
        json={"state": "waiting"},
        headers=headers,
    )
    assert missing.status_code == 422
    waiting = await app_client.post(
        f"/api/back-office/cards/{card.id}/state",
        json={"state": "waiting", "waiting_on": "klienta"},
        headers=headers,
    )
    assert waiting.status_code == 200
    assert waiting.json()["waiting_on"] == "klienta"
    empty = await app_client.post(
        f"/api/back-office/cards/{card.id}/dismiss", json={"body": " "}, headers=headers
    )
    assert empty.status_code == 422
    done = await app_client.post(
        f"/api/back-office/cards/{card.id}/dismiss",
        json={"body": "nie dotyczy tego zamówienia"},
        headers=headers,
    )
    assert done.status_code == 200
    assert done.json()["state"] == "done"


@pytest.mark.asyncio
async def test_case_card_mirrors_take_into_the_case(app_client, modules_on) -> None:
    member = await _user("talent_community_manager", teams=("care",))
    async with AsyncSessionLocal() as db:
        case = AdminCase(
            title=f"Pytanie o dostęp {uuid.uuid4().hex[:6]}",
            area="administration",
            status="new",
            source="manual",
            checklist=[],
        )
        db.add(case)
        await db.commit()
        await db.refresh(case)
        await sync_kinds(db, ["case"], today=business_today())
        await db.commit()
        card = await db.scalar(
            select(BoCard).where(BoCard.source_key == f"case:{case.id}")
        )
        assert card is not None and card.lane == "help"
        card_id = card.id
    taken = await app_client.post(
        f"/api/back-office/cards/{card_id}/take", json={}, headers=_headers(member)
    )
    assert taken.status_code == 200
    async with AsyncSessionLocal() as db:
        fresh = await db.get(AdminCase, case.id)
        assert fresh.assignee_user_id == member.id
        assert fresh.status == "in_progress"
        await db.delete(fresh)
        await db.execute(delete(BoCard).where(BoCard.id == card_id))
        await db.commit()


@pytest.mark.asyncio
async def test_all_steps_done_closes_the_case(app_client, modules_on) -> None:
    from app.models.contract import Contract  # noqa: F401 — relacje metadanych

    lead = await _user("admin")
    async with AsyncSessionLocal() as db:
        case = AdminCase(
            title=f"Koniec współpracy {uuid.uuid4().hex[:6]}",
            area="offboarding",
            status="new",
            source="contract",
            source_key=f"contract:{uuid.uuid4().int % 10**8 + 10**8}:end",
            checklist=[],
        )
        db.add(case)
        await db.commit()
        await db.refresh(case)
        today = business_today()
        await sync_kinds(db, ["case"], today=today)
        result = await steps.sync_steps(db, today=today)
        await db.commit()
        assert result["created"] >= len(steps.EXIT_STEPS)
        children = (
            await db.scalars(
                select(BoCard)
                .where(BoCard.case_id == case.id, BoCard.source_kind == "step")
                .order_by(BoCard.step_order)
            )
        ).all()
        assert {c.team for c in children} == {"care", "contracts", "orders", "finance"}
        ids = [c.id for c in children]
    for card_id in ids:
        done = await app_client.post(
            f"/api/back-office/cards/{card_id}/step-done", headers=_headers(lead)
        )
        assert done.status_code == 200
    async with AsyncSessionLocal() as db:
        fresh = await db.get(AdminCase, case.id)
        assert fresh.status == "done"
        await db.delete(fresh)
        await db.execute(delete(BoCard).where(BoCard.case_id == case.id))
        await db.execute(delete(BoCard).where(BoCard.source_key == f"case:{case.id}"))
        await db.commit()


@pytest.mark.asyncio
async def test_review_decisions_and_finish(app_client, modules_on) -> None:
    lead = await _user("admin")
    headers = _headers(lead)
    current = await _card(needs_review=True)
    response = await app_client.post(
        f"/api/back-office/cards/{current.id}/review",
        json={"decision": "current"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["needs_review"] is False

    moved = await _card(needs_review=True)
    bad = await app_client.post(
        f"/api/back-office/cards/{moved.id}/review",
        json={"decision": "move", "team": "care", "lane": "gap"},
        headers=headers,
    )
    assert bad.status_code == 422
    good = await app_client.post(
        f"/api/back-office/cards/{moved.id}/review",
        json={"decision": "move", "team": "care", "lane": "exit"},
        headers=headers,
    )
    assert good.status_code == 200
    assert (good.json()["team"], good.json()["lane"]) == ("care", "exit")

    finished = await app_client.post("/api/back-office/review/finish", headers=headers)
    assert finished.status_code == 200
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, BACK_OFFICE_SETTING)
        assert row.value["review_done_at"]
        await db.delete(row)
        await db.commit()


async def _case_card(*, area: str = "administration", **fields) -> tuple[int, int]:
    """Sprawa i jej karta po synchronizacji: (id sprawy, id karty)."""

    async with AsyncSessionLocal() as db:
        case = AdminCase(
            title=f"Sprawa testowa {uuid.uuid4().hex[:6]}",
            area=area,
            status="new",
            source="manual",
            checklist=[],
            **fields,
        )
        db.add(case)
        await db.commit()
        await db.refresh(case)
        await sync_kinds(db, ["case"], today=business_today())
        await db.commit()
        card = await db.scalar(
            select(BoCard).where(BoCard.source_key == f"case:{case.id}")
        )
        return case.id, card.id


@pytest.mark.asyncio
async def test_substitute_cannot_open_a_case_without_cases_access(
    app_client, modules_on
) -> None:
    """„Zastępuję” nie może być drogą do treści sprawy (assignee przechodzi ``may_read``)."""

    outsider = await _user("recruiter", teams=("orders",))
    case_id, card_id = await _case_card(area="negotiation")
    refused = await app_client.post(
        f"/api/back-office/cards/{card_id}/take",
        json={"substitute": True},
        headers=_headers(outsider),
    )
    assert refused.status_code == 403
    read = await app_client.get(f"/api/cases/{case_id}", headers=_headers(outsider))
    assert read.status_code == 403
    async with AsyncSessionLocal() as db:
        assert (await db.get(AdminCase, case_id)).assignee_user_id is None

    care = await _user("recruiter", teams=("care",))
    own_team_refused = await app_client.post(
        f"/api/back-office/cards/{card_id}/take",
        json={"substitute": True},
        headers=_headers(care),
    )
    assert own_team_refused.status_code == 403
    contracts = await _user("recruiter", teams=("contracts",))
    allowed = await app_client.post(
        f"/api/back-office/cards/{card_id}/take",
        json={},
        headers=_headers(contracts),
    )
    assert allowed.status_code == 200


@pytest.mark.asyncio
async def test_note_needs_the_team_or_the_person_on_the_card(
    app_client, modules_on
) -> None:
    from app.models.admin_case import AdminCaseComment

    outsider = await _user("recruiter", teams=("orders",))
    case_id, card_id = await _case_card()
    refused = await app_client.post(
        f"/api/back-office/cards/{card_id}/note",
        json={"body": "Notatka spoza zespołu"},
        headers=_headers(outsider),
    )
    assert refused.status_code == 403
    async with AsyncSessionLocal() as db:
        comments = await db.scalars(
            select(AdminCaseComment).where(AdminCaseComment.case_id == case_id)
        )
        assert comments.all() == []
    member = await _user("recruiter", teams=("care",))
    ok = await app_client.post(
        f"/api/back-office/cards/{card_id}/note",
        json={"body": "Notatka zespołu"},
        headers=_headers(member),
    )
    assert ok.status_code == 200


@pytest.mark.asyncio
async def test_hidden_case_shows_no_person_or_client(app_client, modules_on) -> None:
    card = await _card(
        team="contracts",
        lane="annex",
        source_kind="case",
        title="Nowa stawka od stycznia",
        person="Osoba Przykładowa",
        client_label="Klient Przykładowy",
        meta={"area": "negotiation"},
    )
    outsider = await _user("recruiter", teams=("orders",))
    hidden = await app_client.get(
        f"/api/back-office/cards/{card.id}", headers=_headers(outsider)
    )
    assert hidden.status_code == 200
    assert hidden.json()["title"].startswith("Sprawa:")
    assert hidden.json()["person"] is None
    assert hidden.json()["client"] is None
    contracts = await _user("recruiter", teams=("contracts",))
    seen = await app_client.get(
        f"/api/back-office/cards/{card.id}", headers=_headers(contracts)
    )
    assert seen.json()["person"] == "Osoba Przykładowa"


@pytest.mark.asyncio
async def test_take_reads_the_case_not_its_stale_mirror(app_client, modules_on) -> None:
    first = await _user("talent_community_manager", teams=("care",))
    second = await _user("talent_community_manager", teams=("care",))
    case_id, card_id = await _case_card()
    async with AsyncSessionLocal() as db:
        (await db.get(AdminCase, case_id)).assignee_user_id = first.id
        await db.commit()
    taken = await app_client.post(
        f"/api/back-office/cards/{card_id}/take", json={}, headers=_headers(second)
    )
    assert taken.status_code == 409
    assert taken.json()["detail"]["code"] == "taken"

    closed_id, closed_card = await _case_card()
    async with AsyncSessionLocal() as db:
        case = await db.get(AdminCase, closed_id)
        case.status = "closed"
        case.closed_at = case.created_at
        await db.commit()
    for path, body in (
        ("take", {}),
        ("state", {"state": "in_progress"}),
    ):
        refused = await app_client.post(
            f"/api/back-office/cards/{closed_card}/{path}",
            json=body,
            headers=_headers(second),
        )
        assert refused.status_code == 409, path
        assert refused.json()["detail"]["code"] == "closed"
    async with AsyncSessionLocal() as db:
        assert (await db.get(AdminCase, closed_id)).status == "closed"


@pytest.mark.asyncio
async def test_state_done_is_not_a_card_state_change(app_client, modules_on) -> None:
    member = await _user("recruiter", teams=("orders",))
    card = await _card()
    refused = await app_client.post(
        f"/api/back-office/cards/{card.id}/state",
        json={"state": "done"},
        headers=_headers(member),
    )
    assert refused.status_code == 422


@pytest.mark.asyncio
async def test_review_current_keeps_the_card_in_its_lane(
    app_client, modules_on
) -> None:
    lead = await _user("admin")
    card = await _card(needs_review=True)
    response = await app_client.post(
        f"/api/back-office/cards/{card.id}/review",
        json={"decision": "current"},
        headers=_headers(lead),
    )
    assert response.status_code == 200
    async with AsyncSessionLocal() as db:
        fresh = await db.get(BoCard, card.id)
        assert fresh.lane_locked is True
        assert fresh.needs_review is False


@pytest.mark.asyncio
async def test_reopened_dismissed_case_returns_and_does_not_stop_the_sync(
    app_client, modules_on
) -> None:
    lead = await _user("admin")
    case_id, card_id = await _case_card()
    dismissed = await app_client.post(
        f"/api/back-office/cards/{card_id}/dismiss",
        json={"body": "Nieaktualna"},
        headers=_headers(lead),
    )
    assert dismissed.status_code == 200
    async with AsyncSessionLocal() as db:
        case = await db.get(AdminCase, case_id)
        assert case.status == "closed"
        case.status = "new"
        case.closed_at = None
        await db.commit()
    async with AsyncSessionLocal() as db:
        result = await sync_kinds(db, ["case"], today=business_today())
        await db.commit()
        assert result["failed"] == []
        fresh = await db.get(BoCard, card_id)
        assert fresh.state == "new"
        assert fresh.closed_at is None
        assert "dismissed" not in fresh.meta


async def _exit_case() -> tuple[int, str]:
    key = f"contract:{uuid.uuid4().int % 10**8 + 10**8}:end"
    async with AsyncSessionLocal() as db:
        case = AdminCase(
            title=f"Koniec współpracy {uuid.uuid4().hex[:6]}",
            area="offboarding",
            status="new",
            source="contract",
            source_key=key,
            checklist=[],
        )
        db.add(case)
        await db.commit()
        await db.refresh(case)
        await sync_kinds(db, ["case"], today=business_today())
        await steps.sync_steps(db, today=business_today())
        await db.commit()
        return case.id, key


async def _set_case_status(case_id: int, status: str) -> None:
    async with AsyncSessionLocal() as db:
        case = await db.get(AdminCase, case_id)
        case.status = status
        case.closed_at = case.created_at if status in ("done", "closed") else None
        await db.commit()


async def _sync_steps_pass() -> None:
    async with AsyncSessionLocal() as db:
        today = business_today()
        await sync_kinds(db, ["case"], today=today)
        await steps.sync_steps(db, today=today)
        await db.commit()


@pytest.mark.asyncio
async def test_reopened_exit_case_gets_its_steps_back(app_client, modules_on) -> None:
    case_id, _ = await _exit_case()
    await _set_case_status(case_id, "closed")
    await _sync_steps_pass()
    async with AsyncSessionLocal() as db:
        children = await db.scalars(
            select(BoCard).where(
                BoCard.case_id == case_id, BoCard.source_kind == "step"
            )
        )
        assert {c.state for c in children.all()} == {"done"}
    await _set_case_status(case_id, "new")
    await _sync_steps_pass()
    async with AsyncSessionLocal() as db:
        assert (await db.get(AdminCase, case_id)).status == "new"
        children = await db.scalars(
            select(BoCard).where(
                BoCard.case_id == case_id, BoCard.source_kind == "step"
            )
        )
        assert {c.state for c in children.all()} == {"new"}


@pytest.mark.asyncio
async def test_case_reopened_by_mail_after_all_steps_stays_open(
    app_client, modules_on
) -> None:
    lead = await _user("admin")
    case_id, _ = await _exit_case()
    async with AsyncSessionLocal() as db:
        ids = list(
            await db.scalars(
                select(BoCard.id).where(
                    BoCard.case_id == case_id, BoCard.source_kind == "step"
                )
            )
        )
    for card_id in ids:
        done = await app_client.post(
            f"/api/back-office/cards/{card_id}/step-done", headers=_headers(lead)
        )
        assert done.status_code == 200
    async with AsyncSessionLocal() as db:
        assert (await db.get(AdminCase, case_id)).status == "done"
    await _set_case_status(case_id, "new")
    await _sync_steps_pass()
    async with AsyncSessionLocal() as db:
        assert (await db.get(AdminCase, case_id)).status == "new"


@pytest.mark.asyncio
async def test_extended_contract_loses_the_valve_case_until_the_real_end(
    app_client, modules_on
) -> None:
    from app.models.contract import Contract
    from tests.care_announcements_seed import make_client, make_consultant

    client_id = await make_client()
    contract_id, _ = await make_consultant(client_id, end_in_days=10)
    key = f"contract:{contract_id}:end"

    async def set_end(days: int, *, terminated: bool = False) -> None:
        async with AsyncSessionLocal() as db:
            contract = await db.get(Contract, contract_id)
            contract.end_date = business_today() + timedelta(days=days)
            contract.terminated_at = contract.end_date if terminated else None
            await db.commit()

    async def status() -> str:
        async with AsyncSessionLocal() as db:
            return (
                await db.scalar(select(AdminCase).where(AdminCase.source_key == key))
            ).status

    await _sync_steps_pass()
    assert await status() == "new"

    await set_end(200)
    await _sync_steps_pass()
    assert await status() == "closed"

    await set_end(5)
    await _sync_steps_pass()
    assert await status() == "new"
    await _sync_steps_pass()
    async with AsyncSessionLocal() as db:
        case_id = await db.scalar(
            select(AdminCase.id).where(AdminCase.source_key == key)
        )
        children = await db.scalars(
            select(BoCard).where(
                BoCard.case_id == case_id, BoCard.source_kind == "step"
            )
        )
        assert "new" in {c.state for c in children.all()}

    await set_end(200, terminated=True)
    await _sync_steps_pass()
    assert await status() == "new"


@pytest.mark.asyncio
async def test_member_gets_new_case_card_without_the_lead_sync(
    app_client, modules_on
) -> None:
    member = await _user("recruiter", teams=("orders",))
    refused = await app_client.post(
        "/api/back-office/sync", json={}, headers=_headers(member)
    )
    assert refused.status_code == 403
    async with AsyncSessionLocal() as db:
        case = AdminCase(
            title=f"Nowa sprawa {uuid.uuid4().hex[:6]}",
            area="administration",
            status="new",
            source="manual",
            checklist=[],
        )
        db.add(case)
        await db.commit()
        await db.refresh(case)
    synced = await app_client.post(
        "/api/back-office/sync/cases", json={}, headers=_headers(member)
    )
    assert synced.status_code == 200
    assert synced.json()["failed"] == []
    async with AsyncSessionLocal() as db:
        assert await db.scalar(
            select(BoCard.id).where(BoCard.source_key == f"case:{case.id}")
        )
    outsider = await _user("recruiter")
    denied = await app_client.post(
        "/api/back-office/sync/cases", json={}, headers=_headers(outsider)
    )
    assert denied.status_code == 403
    board = await app_client.get("/api/back-office/board", headers=_headers(member))
    assert board.json()["me"]["cases_handler"] is False
