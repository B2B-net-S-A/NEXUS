"""Akcje na wielu szansach naraz z listy Szans (decyzja Artura 11.11.2026, „mniej kliknięć”).

Każda szansa przechodzi reguły pojedynczej zmiany: krok u opiekuna bez dotyku, opiekuna
zmienia tylko opiekun albo admin, a jego otwarte zadania idą za szansą, zamknięcie to etap
przegranej z opcjonalnym powodem. Szansa spoza reguły trafia do ``skipped``, reszta się zapisuje.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.core.database import AsyncSessionLocal
from app.core.scheduling import DEFAULT_TZ, business_today
from app.models.sales import SalesOpportunity
from app.models.user import User
from app.services.sales import bulk
from tests.test_sales_companies_api import _headers, _user
from tests.test_sales_offers import (
    _activity,
    _deactivate,
    _now,
    _opportunity,
    _owner_events,
    _owner_of,
    _tasks,
)

BULK = "/api/sales/opportunities/bulk"


async def _bulk(app_client: Any, user: User, **payload: Any) -> Any:
    return await app_client.post(BULK, json=payload, headers=_headers(user))


async def _opp(opportunity_id: int) -> SalesOpportunity:
    async with AsyncSessionLocal() as db:
        opp = await db.get(SalesOpportunity, opportunity_id)
        assert opp is not None
        return opp


def _reasons(body: dict[str, Any]) -> dict[int, str]:
    return {skip["id"]: skip["reason"] for skip in body["skipped"]}


# ── krok ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_plan_step_creates_a_task_with_the_owner_and_skips_closed_archived_and_missing(
    app_client,
) -> None:
    rep = await _user("sales_edit")
    owner = await _user("sales_edit")
    mine = await _opportunity(rep.id, stage="lead")
    theirs = await _opportunity(owner.id, stage="lead")
    lost = await _opportunity(rep.id, stage="lost", status="lost")
    archived = await _opportunity(rep.id, stage="lead", archived_at=_now())
    touched_before = (await _opp(mine)).last_activity_at

    resp = await _bulk(
        app_client,
        rep,
        ids=[mine, theirs, lost, archived, 999_999_999],
        action="plan",
        days=3,
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["done"] == [mine, theirs]
    assert _reasons(body) == {
        lost: bulk.CLOSED,
        archived: bulk.ARCHIVED,
        999_999_999: bulk.NOT_FOUND,
    }
    expected_due = datetime.combine(
        business_today() + timedelta(days=3), time(9), tzinfo=ZoneInfo(DEFAULT_TZ)
    )
    [task] = await _tasks(mine)
    assert task.subject == "Zadzwonić"
    assert task.due_at == expected_due
    assert task.assignee_user_id == rep.id
    assert task.created_by_user_id == rep.id
    assert task.done_at is None
    [their_task] = await _tasks(theirs)
    # Krok przy cudzej szansie trafia do jej opiekuna, jak z karty.
    assert their_task.assignee_user_id == owner.id
    # Sam zaplanowany krok nie jest dotykiem szansy.
    assert (await _opp(mine)).last_activity_at == touched_before
    assert await _tasks(lost) == []


@pytest.mark.asyncio
async def test_plan_step_for_an_inactive_owner_stays_with_the_person_who_clicked(
    app_client,
) -> None:
    rep = await _user("sales_edit")
    gone = await _user("sales_edit")
    opp = await _opportunity(gone.id, stage="lead")
    await _deactivate(gone)

    resp = await _bulk(
        app_client, rep, ids=[opp], action="plan", days=1, subject="  Oddzwonić  "
    )

    assert resp.status_code == 200, resp.text
    [task] = await _tasks(opp)
    assert task.assignee_user_id == rep.id
    assert task.subject == "Oddzwonić"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"action": "plan"},  # bez terminu
        {"action": "plan", "days": 2},  # termin spoza terminów modułu
        {"action": "plan", "days": 1, "subject": "   "},
        {"action": "owner"},  # bez nowego opiekuna
        {"action": "archive", "days": 1},  # nieznana akcja
    ],
)
async def test_incomplete_request_is_refused_and_writes_nothing(
    app_client, payload: dict[str, Any]
) -> None:
    rep = await _user("sales_edit")
    opp = await _opportunity(rep.id, stage="lead")

    resp = await _bulk(app_client, rep, ids=[opp], **payload)

    assert resp.status_code == 422
    assert await _tasks(opp) == []


@pytest.mark.asyncio
async def test_too_many_or_no_ids_are_refused(app_client) -> None:
    rep = await _user("sales_edit")
    too_many = list(range(1, bulk.MAX_IDS + 2))
    assert (
        await _bulk(app_client, rep, ids=too_many, action="plan", days=1)
    ).status_code == 422
    assert (
        await _bulk(app_client, rep, ids=[], action="plan", days=1)
    ).status_code == 422


@pytest.mark.asyncio
async def test_without_sales_edit_bulk_is_closed(app_client) -> None:
    viewer = await _user("sales_view")
    opp = await _opportunity(None, stage="lead")

    resp = await _bulk(app_client, viewer, ids=[opp], action="plan", days=1)

    assert resp.status_code == 403
    assert await _tasks(opp) == []


# ── opiekun ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_owner_change_moves_open_tasks_and_skips_someone_elses_opportunity(
    app_client,
) -> None:
    rep = await _user("sales_edit")
    colleague = await _user("sales_edit")
    other = await _user("sales_edit")
    mine = await _opportunity(rep.id, stage="lead")
    unowned = await _opportunity(None, stage="lead")
    theirs = await _opportunity(other.id, stage="lead")
    my_task = await _activity(
        kind="task",
        subject="Wysłać ofertę",
        opportunity_id=mine,
        due_at=_now() + timedelta(days=2),
        assignee_user_id=rep.id,
        created_by_user_id=rep.id,
    )

    resp = await _bulk(
        app_client,
        rep,
        ids=[mine, unowned, theirs],
        action="owner",
        owner_user_id=colleague.id,
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["done"] == [mine, unowned]
    assert _reasons(body) == {theirs: bulk.NOT_OWNER}
    assert await _owner_of(mine) == colleague.id
    assert await _owner_of(unowned) == colleague.id
    assert await _owner_of(theirs) == other.id
    [task] = await _tasks(mine)
    assert task.id == my_task
    assert task.assignee_user_id == colleague.id
    assert len(await _owner_events(mine)) == 1


@pytest.mark.asyncio
async def test_admin_changes_the_owner_of_someone_elses_opportunity(app_client) -> None:
    admin = await _user("sales_edit", role="admin")
    other = await _user("sales_edit")
    colleague = await _user("sales_edit")
    theirs = await _opportunity(other.id, stage="lead")

    resp = await _bulk(
        app_client, admin, ids=[theirs], action="owner", owner_user_id=colleague.id
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["done"] == [theirs]
    assert await _owner_of(theirs) == colleague.id


@pytest.mark.asyncio
async def test_inactive_new_owner_is_refused_for_the_whole_request(app_client) -> None:
    rep = await _user("sales_edit")
    gone = await _user("sales_edit")
    await _deactivate(gone)
    opp = await _opportunity(rep.id, stage="lead")

    resp = await _bulk(
        app_client, rep, ids=[opp], action="owner", owner_user_id=gone.id
    )

    assert resp.status_code == 422
    assert await _owner_of(opp) == rep.id


# ── zamknięcie ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_close_moves_to_lost_with_an_optional_reason(app_client) -> None:
    rep = await _user("sales_edit")
    first = await _opportunity(rep.id, stage="lead")
    second = await _opportunity(rep.id, stage="qualified")
    already = await _opportunity(rep.id, stage="lost", status="lost")

    resp = await _bulk(
        app_client,
        rep,
        ids=[first, second, already],
        action="close",
        lost_reason=" brak budżetu ",
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["done"] == [first, second]
    assert _reasons(body) == {already: bulk.CLOSED}
    for opportunity_id in (first, second):
        opp = await _opp(opportunity_id)
        assert opp.status == "lost"
        assert opp.lost_reason == "brak budżetu"


@pytest.mark.asyncio
async def test_close_without_reason_keeps_reason_empty(app_client) -> None:
    rep = await _user("sales_edit")
    opp = await _opportunity(rep.id, stage="lead")

    resp = await _bulk(app_client, rep, ids=[opp], action="close")

    assert resp.status_code == 200, resp.text
    closed = await _opp(opp)
    assert closed.status == "lost"
    assert closed.lost_reason is None


@pytest.mark.asyncio
async def test_close_with_a_stage_missing_in_the_pipeline_skips_the_opportunity(
    app_client,
) -> None:
    rep = await _user("sales_edit")
    opp = await _opportunity(rep.id, stage="lead")

    resp = await _bulk(
        app_client, rep, ids=[opp], action="close", stage_key="nie-ma-takiego"
    )

    assert resp.status_code == 200, resp.text
    assert _reasons(resp.json()) == {opp: bulk.OTHER_PIPELINE}
    assert (await _opp(opp)).status == "open"
